#!/usr/bin/env python3
"""Build a USB-specific offline Recovery kit. Run on a functioning macOS host.

Does not install packages on the host, format disks, patch macOS, or edit EFI.
Only --deploy writes the prepared kit to the selected USB.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import uuid

BASE = Path(__file__).resolve().parent
BUILD = "25G241"
VERSION = "26.7.1"
MODEL = "MacBookPro11,3"
ASSETS_SHA = "784d2c7fb06953e422056237174da0f02381ce6e1059fbfb97486c5cdcfabd4b"
KDK_PKG_SHA = "9d2c3e45fce5c69024b2c913e1bb7ee9aa6a1d9e4c75724c501c9798589a3444"
DOWNLOADS = {
    "AutoPkg-Assets.pkg": (
        "https://github.com/dortania/OpenCore-Legacy-Patcher/releases/download/3.0.0-rc.3/AutoPkg-Assets.pkg",
        ASSETS_SHA,
    ),
    "KDK-25G241.dmg": (
        "https://github.com/dortania/KdkSupportPkg/releases/download/25G241/Kernel_Debug_Kit_26.7.1_build_25G241.dmg",
        "9045a521c8ae362d4cb2cc54701b03462686e0069518a0b66cfe2028f87dfe9b",
    ),
}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require_hash(path, expected):
    path = Path(path).resolve(strict=True)
    if not path.is_file() or digest(path) != expected:
        raise ValueError("Pinned SHA-256 mismatch: " + str(path))
    return path


def run(args, **kwargs):
    print("Running:", args[0], *args[1:3], flush=True)
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def disk_info(path):
    return plistlib.loads(subprocess.check_output(["/usr/sbin/diskutil", "info", "-plist", str(path)]))


def validate_usb(path):
    path = Path(path).resolve(strict=True)
    info = disk_info(path)
    if info.get("Internal") is not False or info.get("FilesystemType") != "hfs":
        raise ValueError("Select an external HFS+ macOS installer USB, not an internal disk.")
    if Path(info.get("MountPoint", "")).resolve() != path:
        raise ValueError("--usb must be the volume's mount point, not a subdirectory.")
    partition = str(uuid.UUID(info["DiskUUID"])).upper()
    version = plistlib.loads((path / "System/Library/CoreServices/SystemVersion.plist").read_bytes())
    if version.get("ProductVersion") != VERSION or version.get("ProductBuildVersion") != BUILD:
        raise ValueError("Installer must be exactly macOS " + VERSION + " (" + BUILD + ").")
    return path, partition


def download(name, cache):
    url, expected = DOWNLOADS[name]
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / name
    if dest.exists():
        return require_hash(dest, expected)
    print("Downloading official asset:", url, flush=True)
    fd, tmp = tempfile.mkstemp(prefix=name + ".", suffix=".part", dir=str(cache))
    try:
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(url, timeout=120) as response:
            shutil.copyfileobj(response, out, length=1024 * 1024)
        require_hash(tmp, expected)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return dest


def root_owner(member):
    member.uid = member.gid = 0
    member.uname, member.gname = "root", "wheel"
    return member


def create_archive(dest, root, paths):
    with tarfile.open(dest, "w:gz", compresslevel=1) as archive:
        for relative in paths:
            archive.add(root / relative, arcname=str(relative), filter=root_owner)


def assemble(output, partition, assets, kdk_pkg, work):
    assets_expanded, kdk_expanded = work / "assets", work / "kdk"
    run(["/usr/sbin/pkgutil", "--expand-full", assets, assets_expanded])
    run(["/usr/sbin/pkgutil", "--expand-full", kdk_pkg, kdk_expanded])
    payload = assets_expanded / "AutoPkg-Assets.pkg/Payload"
    app = Path("Library/Application Support/Dortania/OpenCore-Patcher.app")
    helper = Path("Library/PrivilegedHelperTools/com.dortania.opencore-legacy-patcher.privileged-helper")
    info = plistlib.loads((payload / app / "Contents/Info.plist").read_bytes())
    if info.get("Github", {}).get("Branch") != "refs/tags/3.0.0-rc.3":
        raise ValueError("Assets do not contain the expected RC3 app.")
    run(["/usr/bin/codesign", "--verify", "--deep", "--strict", payload / app])
    if not (payload / helper).is_file():
        raise ValueError("OCLP privileged helper is missing.")
    kdk_payload = kdk_expanded / "KDK.pkg/Payload"
    kdk_info = plistlib.loads((kdk_payload / "System/Library/CoreServices/SystemVersion.plist").read_bytes())
    if kdk_info.get("ProductBuildVersion") != BUILD:
        raise ValueError("KDK does not match " + BUILD)
    sdk = kdk_expanded / "KDK_SDK.pkg/Payload"
    if not sdk.is_dir():
        raise ValueError("KDK SDK payload is missing.")
    shutil.copytree(sdk, kdk_payload, symlinks=True, dirs_exist_ok=True)
    package = plistlib.loads((BASE / "kit/local.mbp113-repair.plist").read_bytes())
    kit = output / "MBP113-Repair"
    kit.mkdir(parents=True)
    shutil.copy2(BASE / "kit/repair.sh", output / "repair.sh")
    for name in ["startup-repair.sh", "recovery-tool.c"]:
        shutil.copy2(BASE / "kit" / name, kit / name)
    common = (BASE / "kit/common.sh").read_text().replace("__USB_PARTITION_UUID__", partition)
    (kit / "common.sh").write_text(common)
    (kit / "local.mbp113-repair.plist").write_bytes(plistlib.dumps(package))
    run(["/usr/bin/xcrun", "clang", "-arch", "x86_64", "-mmacosx-version-min=10.13", "-O2",
         "-Wall", "-Wextra", "-Werror", "-Wno-deprecated-declarations", "-framework", "CoreFoundation",
         kit / "recovery-tool.c", "-o", kit / "recovery-tool"])
    run(["/usr/bin/codesign", "--force", "--sign", "-", kit / "recovery-tool"])
    create_archive(kit / "RC3-runtime.tar.gz", payload, [app, helper])
    kdk_root = work / ("KDK_" + VERSION + "_" + BUILD + ".kdk")
    shutil.move(str(kdk_payload), str(kdk_root))
    create_archive(output / ("KDK-" + BUILD + ".tar.gz"), work, [Path(kdk_root.name)])
    packages = output / "Library/Packages"
    packages.mkdir(parents=True)
    shutil.copy2(assets, packages / "AutoPkg-Assets.pkg")
    shutil.copy2(kdk_pkg, packages / "KDK.pkg")
    files = sorted(p for p in output.rglob("*") if p.is_file())
    manifest = "".join(digest(p) + "  " + p.relative_to(output).as_posix() + "\n" for p in files)
    (kit / "SHA256SUMS").write_text(manifest)
    run([kit / "recovery-tool", "sha-check", "MBP113-Repair/SHA256SUMS"], cwd=str(output))


def deploy(output, usb):
    # Only these explicitly documented paths are written. The installer app,
    # shared-support image, EFI, and other volumes are never replaced here.
    for relative in ["MBP113-Repair", "repair.sh", "Library", "Library/Packages",
                     "Library/Packages/AutoPkg-Assets.pkg", "Library/Packages/KDK.pkg", "KDK-25G241.tar.gz"]:
        if (usb / relative).is_symlink():
            raise ValueError("Refusing a symlinked USB destination: " + relative)
    kit = usb / "MBP113-Repair"
    if kit.exists() or (usb / "repair.sh").exists():
        raise ValueError("A recovery kit already exists on the USB. Preserve it before deploying another version.")
    for relative in ["Library/Packages/AutoPkg-Assets.pkg", "Library/Packages/KDK.pkg", "KDK-25G241.tar.gz"]:
        src, dest = output / relative, usb / relative
        if dest.exists() and (not dest.is_file() or digest(dest) != digest(src)):
            raise ValueError("Existing USB file differs; refusing to overwrite: " + str(dest))
    needed = sum(p.stat().st_size for p in output.rglob("*") if p.is_file() and not (usb / p.relative_to(output)).exists())
    if shutil.disk_usage(usb).free < needed + 64 * 1024 * 1024:
        raise ValueError("Not enough free space on USB for kit plus logging reserve.")
    for relative in ["Library/Packages/AutoPkg-Assets.pkg", "Library/Packages/KDK.pkg", "KDK-25G241.tar.gz"]:
        src, dest = output / relative, usb / relative
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    shutil.copytree(output / "MBP113-Repair", kit)
    shutil.copy2(output / "repair.sh", usb / "repair.sh")
    run([kit / "recovery-tool", "sha-check", "MBP113-Repair/SHA256SUMS"], cwd=str(usb))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usb", required=True, type=Path, help="Mounted external Tahoe 26.7.1 installer volume")
    parser.add_argument("--assets-pkg", type=Path)
    parser.add_argument("--kdk-pkg", type=Path, help="KernelDebugKit.pkg from the official matching DMG")
    parser.add_argument("--download", action="store_true", help="Fetch pinned official assets and matching KDK DMG")
    parser.add_argument("--cache", type=Path, default=BASE / "build/downloads")
    parser.add_argument("--output", type=Path, default=BASE / "build/USB-Kit")
    parser.add_argument("--deploy", action="store_true", help="Also copy the verified kit to the selected USB")
    args = parser.parse_args()
    usb, partition = validate_usb(args.usb)
    output = args.output.resolve()
    # Keep multi-GB expanded/generated payloads off the installer USB.
    if output == usb or usb in output.parents or output.exists():
        raise ValueError("Choose a new, non-existing output directory on the host Mac, outside the USB.")
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < 15 * 1024 ** 3:
        raise ValueError("At least 15 GiB host free space is required.")
    assets, kdk_pkg = args.assets_pkg, args.kdk_pkg
    image = None
    try:
        if args.download:
            if assets is None:
                assets = download("AutoPkg-Assets.pkg", args.cache.resolve())
            if kdk_pkg is None:
                dmg = download("KDK-25G241.dmg", args.cache.resolve())
                result = subprocess.check_output(["/usr/bin/hdiutil", "attach", "-readonly", "-nobrowse", "-plist", str(dmg)])
                entities = plistlib.loads(result)["system-entities"]
                mounts = [e["mount-point"] for e in entities if "mount-point" in e]
                if len(mounts) != 1:
                    raise ValueError("Expected one KDK image mount.")
                image = mounts[0]
                kdk_pkg = Path(image) / "KernelDebugKit.pkg"
        if assets is None or kdk_pkg is None:
            raise ValueError("Use --download, or provide both --assets-pkg and --kdk-pkg.")
        assets = require_hash(assets, ASSETS_SHA)
        kdk_pkg = require_hash(kdk_pkg, KDK_PKG_SHA)
        with tempfile.TemporaryDirectory(prefix="mbp113-build-", dir=str(output.parent)) as work:
            output.mkdir()
            assemble(output, partition, assets, kdk_pkg, Path(work))
        if args.deploy:
            # Revalidate after the long build: USB may have been disconnected.
            current_usb, current_partition = validate_usb(usb)
            if current_partition != partition:
                raise ValueError("USB identity changed during the build.")
            deploy(output, current_usb)
        print("Verified kit:", output)
        print("USB GPT identity was bound locally; it is not part of the public source.")
    finally:
        if image:
            subprocess.run(["/usr/bin/hdiutil", "detach", image], check=False)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit("STOP: " + str(exc))
