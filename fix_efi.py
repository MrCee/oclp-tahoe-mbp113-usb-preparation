#!/usr/bin/env python3
"""Apply only the reported DataHub change to the selected USB's OCLP config."""
import argparse
import copy
import datetime
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile

from build_kit import MODEL, disk_info, validate_usb

APPLE_GUID = "7C436110-AB2A-4BBB-A880-FE41995C9F82"
OCLP_GUID = "4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102"
BOARD = "Mac-2BD1B31983FE1663"


def update_config(original, normal_boot=False):
    config = copy.deepcopy(original)
    target = config.get("#Revision", {}).get("Original-Model")
    nvram_target = config.get("NVRAM", {}).get("Add", {}).get(OCLP_GUID, {}).get("OCLP-Model")
    if target != MODEL or nvram_target not in (None, MODEL):
        raise ValueError("OCLP must already have been built for " + MODEL)
    platform = config.get("PlatformInfo")
    if not isinstance(platform, dict) or not isinstance(platform.get("DataHub"), dict):
        raise ValueError("Expected existing OCLP PlatformInfo/DataHub structure.")
    platform["DataHub"]["SystemProductName"] = MODEL
    platform["DataHub"]["BoardProduct"] = BOARD
    platform["UpdateDataHub"] = True
    if normal_boot:
        apple = config.get("NVRAM", {}).get("Add", {}).get(APPLE_GUID)
        if not isinstance(apple, dict) or not isinstance(apple.get("boot-args"), str):
            raise ValueError("Expected existing Apple NVRAM boot-args.")
        apple["boot-args"] = " ".join(a for a in apple["boot-args"].split() if a != "-x")
        deleted = config["NVRAM"].setdefault("Delete", {}).setdefault(APPLE_GUID, [])
        if not isinstance(deleted, list):
            raise ValueError("Expected an NVRAM Delete list for Apple variables.")
        if "boot-args" not in deleted:
            deleted.append("boot-args")
    return config


def validate_config(usb, config_path):
    path = Path(config_path).resolve(strict=True)
    if path.name != "config.plist" or path.parent.name != "OC" or path.parent.parent.name != "EFI":
        raise ValueError("Select the existing EFI/OC/config.plist file.")
    mount = path.parent
    while not os.path.ismount(str(mount)) and mount != mount.parent:
        mount = mount.parent
    if path != mount / "EFI/OC/config.plist":
        raise ValueError("Config must be at the EFI volume root, not a nested backup folder.")
    usb_info, efi_info = disk_info(usb), disk_info(mount)
    if not usb_info.get("ParentWholeDisk") or efi_info.get("Content") != "EFI" or efi_info.get("Internal") is not False or efi_info.get("ParentWholeDisk") != usb_info.get("ParentWholeDisk"):
        raise ValueError("Selected config must be on the EFI partition of the same external USB.")
    update_config(plistlib.loads(path.read_bytes()))
    return path


def apply_config(path, normal_boot=False, expected_bytes=None):
    original_bytes = path.read_bytes()
    if expected_bytes is not None and original_bytes != expected_bytes:
        raise ValueError("EFI config changed during preparation; review it before retrying.")
    original = plistlib.loads(original_bytes)
    changed = update_config(original, normal_boot)
    if changed == original:
        print("Already set; no write needed.")
        return
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = path.with_name("config.before-datahub-" + stamp + ".plist")
    with backup.open("xb") as out:
        out.write(original_bytes)
        out.flush()
        os.fsync(out.fileno())
    fd, temp = tempfile.mkstemp(prefix=".config-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(plistlib.dumps(changed, sort_keys=False))
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temp, path.stat().st_mode & 0o777)
        os.replace(temp, path)
        if plistlib.loads(path.read_bytes()) != changed:
            raise ValueError("Config read-back failed; restore " + str(backup))
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    print("Updated reported DataHub fields" + (" and normal-boot NVRAM settings." if normal_boot else "."))
    print("Original config backup:", backup)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usb", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path, help="EFI/OC/config.plist on the same USB")
    parser.add_argument("--normal-boot", action="store_true", help="Remove -x and replace saved boot-args on the next OpenCore boot")
    args = parser.parse_args()
    usb, _ = validate_usb(args.usb)
    path = validate_config(usb, args.config)
    apply_config(path, args.normal_boot)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit("STOP: " + str(exc))
