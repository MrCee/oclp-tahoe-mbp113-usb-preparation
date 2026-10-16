#!/usr/bin/env python3
"""Prepare or repair the supported USB in one command; never erase/install macOS."""
import argparse
import datetime
import json
from pathlib import Path, PurePosixPath
import plistlib
import re
import subprocess
import sys

import build_kit as builder
import fix_efi

REQUIRED = {
    'repair.sh', 'KDK-25G241.tar.gz',
    'Library/Packages/AutoPkg-Assets.pkg', 'Library/Packages/KDK.pkg',
    'MBP113-Repair/common.sh', 'MBP113-Repair/startup-repair.sh',
    'MBP113-Repair/recovery-tool', 'MBP113-Repair/recovery-tool.c',
    'MBP113-Repair/local.mbp113-repair.plist', 'MBP113-Repair/RC3-runtime.tar.gz',
}


def safe_path(root, relative):
    relative = PurePosixPath(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Unsafe relative path: ' + str(relative))
    path = root
    for part in relative.parts:
        path /= part
        if path.is_symlink():
            raise ValueError('Refusing a symlink at ' + str(path))
    return path


def find_config(usb, read_only=False):
    parent = builder.disk_info(usb).get('ParentWholeDisk')
    if not parent:
        raise ValueError('USB parent disk is missing.')
    listing = plistlib.loads(subprocess.check_output(['/usr/sbin/diskutil', 'list', '-plist', parent]))
    candidates = []
    for disk in listing.get('AllDisksAndPartitions', []):
        for part in disk.get('Partitions', []):
            info = builder.disk_info(part['DeviceIdentifier'])
            if info.get('Content') == 'EFI' and info.get('ParentWholeDisk') == parent and info.get('Internal') is False:
                candidates.append(part['DeviceIdentifier'])
    if len(candidates) != 1:
        raise ValueError('Expected exactly one EFI partition on the selected external USB.')
    device = candidates[0]
    info = builder.disk_info(device)
    if not info.get('MountPoint'):
        command = ['/usr/sbin/diskutil', 'mount']
        if read_only:
            command.append('readOnly')
        subprocess.run(command + [device], check=True)
        info = builder.disk_info(device)
    if not info.get('MountPoint'):
        raise ValueError('USB EFI did not mount; administrator access may be required.')
    return Path(info['MountPoint']) / 'EFI/OC/config.plist'


def check_boot_files(config_path):
    efi = config_path.parents[1]
    for relative in ['BOOT/BOOTx64.efi', 'OC/OpenCore.efi']:
        path = safe_path(efi, relative)
        if not path.is_file() or not path.stat().st_size:
            raise ValueError('Missing OpenCore boot file: ' + relative)
    config = plistlib.loads(config_path.read_bytes())
    for section, folder in [('ACPI', 'ACPI'), ('UEFI', 'Drivers')]:
        key = 'Drivers' if section == 'UEFI' else 'Add'
        for entry in config.get(section, {}).get(key, []):
            if not isinstance(entry, dict):
                raise ValueError('Expected current OCLP ' + section + ' entries.')
            if entry.get('Enabled'):
                path = safe_path(efi / 'OC' / folder, entry['Path'])
                if not path.is_file() or not path.stat().st_size:
                    raise ValueError('Missing enabled EFI file: ' + str(path.relative_to(efi)))
    for entry in config.get('Kernel', {}).get('Add', []):
        if not entry.get('Enabled'):
            continue
        bundle = safe_path(efi / 'OC/Kexts', entry['BundlePath'])
        for key in ['PlistPath', 'ExecutablePath']:
            if entry.get(key):
                path = safe_path(bundle, entry[key])
                if not path.is_file() or not path.stat().st_size:
                    raise ValueError('Missing enabled kext file: ' + str(path.relative_to(efi)))


def verify_installer(usb):
    builder.require_hash(safe_path(usb, 'Library/Packages/AutoPkg-Assets.pkg'), builder.ASSETS_SHA)
    builder.require_hash(safe_path(usb, 'Library/Packages/KDK.pkg'), builder.KDK_PKG_SHA)


def verify_payloads(usb, partition):
    builder.require_hash(safe_path(usb, 'Library/Packages/AutoPkg-Assets.pkg'), builder.ASSETS_SHA)
    builder.require_hash(safe_path(usb, 'Library/Packages/KDK.pkg'), builder.KDK_PKG_SHA)
    manifest = safe_path(usb, 'MBP113-Repair/SHA256SUMS')
    entries = {}
    for line in manifest.read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
        if not match or match[2] not in REQUIRED or match[2] in entries:
            raise ValueError('Unexpected, duplicate or malformed kit manifest entry.')
        entries[match[2]] = match[1]
    if set(entries) != REQUIRED:
        raise ValueError('Kit manifest is incomplete.')
    for relative, expected in entries.items():
        builder.require_hash(safe_path(usb, relative), expected)
    common = safe_path(usb, 'MBP113-Repair/common.sh').read_text()
    expected_common = (builder.BASE / 'kit/common.sh').read_text().replace('__USB_PARTITION_UUID__', partition)
    if common != expected_common:
        raise ValueError('Kit settings are outdated or bound to a different USB partition.')
    for source, relative in [
        ('repair.sh', 'repair.sh'), ('startup-repair.sh', 'MBP113-Repair/startup-repair.sh'),
        ('recovery-tool.c', 'MBP113-Repair/recovery-tool.c'),
    ]:
        if (builder.BASE / 'kit' / source).read_bytes() != safe_path(usb, relative).read_bytes():
            raise ValueError('Kit source differs from this release: ' + relative)
    if plistlib.loads((builder.BASE / 'kit/local.mbp113-repair.plist').read_bytes()) != plistlib.loads(
            safe_path(usb, 'MBP113-Repair/local.mbp113-repair.plist').read_bytes()):
        raise ValueError('Kit startup service differs from this release.')


def permissions(usb, repair=False, recovery_kit=False):
    targets = {'Library': 0o755, 'Library/Packages': 0o755,
               'Library/Packages/AutoPkg-Assets.pkg': 0o644, 'Library/Packages/KDK.pkg': 0o644}
    if recovery_kit:
        targets['MBP113-Repair'] = 0o755
        targets.update({relative: (0o755 if relative.endswith('/recovery-tool') else 0o644)
                        for relative in REQUIRED})
        targets['MBP113-Repair/SHA256SUMS'] = 0o644
    for relative, mode in targets.items():
        path = safe_path(usb, relative)
        if repair:
            path.chmod(mode)
        elif path.stat().st_mode & 0o777 != mode:
            raise ValueError('Unexpected permissions at ' + relative)


def audit(usb, partition, config, recovery_kit=False):
    check_boot_files(config)
    original = plistlib.loads(config.read_bytes())
    if fix_efi.update_config(original, normal_boot=True) != original:
        raise ValueError('DataHub or normal-boot NVRAM settings still need correction.')
    verify_installer(usb)
    permissions(usb, recovery_kit=recovery_kit)
    if recovery_kit:
        verify_payloads(usb, partition)
        builder.run([usb / 'MBP113-Repair/recovery-tool', 'sha-check', 'MBP113-Repair/SHA256SUMS'], cwd=str(usb))
        builder.run([usb / 'MBP113-Repair/recovery-tool', 'lint', usb / 'MBP113-Repair/local.mbp113-repair.plist'])


def assert_same_usb(usb, partition):
    if builder.validate_usb(usb)[1] != partition:
        raise ValueError('USB identity changed during preparation; stopping.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--usb', required=True, type=Path)
    parser.add_argument('--config', type=Path, help='Optional override; otherwise find/mount this USB EFI automatically')
    parser.add_argument('--check', action='store_true', help='Audit only; no files on USB/EFI are changed')
    parser.add_argument('--with-recovery-kit', action='store_true', help='Also build the optional Recovery fallback; requires Xcode Command Line Tools')
    parser.add_argument('--assets-pkg', type=Path)
    parser.add_argument('--kdk-pkg', type=Path)
    parser.add_argument('--cache', type=Path, default=builder.BASE / 'build/downloads')
    args = parser.parse_args(argv)
    usb, partition = builder.validate_usb(args.usb)
    cache = args.cache.resolve()
    if cache == usb or usb in cache.parents:
        raise ValueError("Download cache must be on the host, outside the installer USB.")
    config = fix_efi.validate_config(usb, args.config or find_config(usb, read_only=args.check))
    check_boot_files(config)
    config_before = config.read_bytes()
    fix_efi.update_config(plistlib.loads(config_before), normal_boot=True)
    if args.check:
        audit(usb, partition, config, recovery_kit=args.with_recovery_kit)
        print('PASS: installer packages, permissions, EFI paths, model and normal boot verified'
              + ('; Recovery kit verified.' if args.with_recovery_kit else '.'))
        return
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    run_dir = builder.BASE / 'build/runs' / stamp
    run_dir.mkdir(parents=True)
    report = {'model': builder.MODEL, 'build': builder.BUILD, 'usb_partition': partition,
              'status': 'incomplete', 'steps': [],
              'mode': 'installer-and-recovery-kit' if args.with_recovery_kit else 'installer-only', 'full_reinstall_required_in_reported_case': True}
    platform_before = plistlib.loads(config_before)['PlatformInfo']
    report['efi_before'] = {
        'SystemProductName': platform_before['DataHub'].get('SystemProductName'),
        'BoardProduct': platform_before['DataHub'].get('BoardProduct'),
        'UpdateDataHub': platform_before.get('UpdateDataHub'),
    }
    log_handles = [(run_dir / 'prepare.log').open('a')]
    usb_log_dir = None
    try:
        # Always establish persistent USB logging before changing prepared files.
        for volume in [usb, config.parents[2]]:
            try:
                log_dir = safe_path(volume, 'Repair-Logs/prepare-' + stamp)
                log_dir.mkdir(parents=True, exist_ok=False)
                log_handles.append((log_dir / 'prepare.log').open('a'))
                usb_log_dir = log_dir
                break
            except (OSError, ValueError):
                continue
        if usb_log_dir is None:
            raise ValueError('No writable log destination on this USB or its EFI.')

        def log(message):
            print(message, flush=True)
            for handle in log_handles:
                handle.write(message + '\n')
                handle.flush()

        log('Preparing ' + builder.MODEL + ' / ' + builder.BUILD + '; USB logs: ' + str(usb_log_dir))
        try:
            verify_installer(usb)
            if args.with_recovery_kit:
                verify_payloads(usb, partition)
            log('Existing selected payloads verify; reusing them.')
            report['steps'].append('verified-existing-payloads')
        except (OSError, ValueError) as reason:
            log('Preparing missing or changed payloads: ' + str(reason))
            output = run_dir / 'USB-Kit'
            command = [sys.executable, str(builder.BASE / 'build_kit.py'), '--usb', str(usb),
                       '--download', '--cache', str(cache), '--output', str(output)]
            if not args.with_recovery_kit:
                command.append('--installer-only')
            for option, supplied, relative, expected in [
                ('--assets-pkg', args.assets_pkg, 'Library/Packages/AutoPkg-Assets.pkg', builder.ASSETS_SHA),
                ('--kdk-pkg', args.kdk_pkg, 'Library/Packages/KDK.pkg', builder.KDK_PKG_SHA),
            ]:
                if supplied is None:
                    try:
                        supplied = builder.require_hash(safe_path(usb, relative), expected)
                    except (OSError, ValueError):
                        pass
                if supplied is not None:
                    command.extend([option, str(supplied.resolve())])
            with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as process:
                for line in process.stdout:
                    log(line.rstrip('\n'))
                if process.wait():
                    raise ValueError('Offline package preparation failed; see prepare.log.')
            assert_same_usb(usb, partition)
            fix_efi.validate_config(usb, config)
            if config.read_bytes() != config_before:
                raise ValueError('EFI config changed during preparation; no deployment performed.')
            builder.deploy(output, usb, backup_dir=run_dir / 'usb-backups', recovery_kit=args.with_recovery_kit)
            report['steps'].append('deployed-selected-payloads-with-host-backups')
        assert_same_usb(usb, partition)
        fix_efi.validate_config(usb, config)
        backup = fix_efi.apply_config(config, normal_boot=True, expected_bytes=config_before)
        report['efi_backup'] = str(backup) if backup else None
        permissions(usb, repair=True, recovery_kit=args.with_recovery_kit)
        audit(usb, partition, config, recovery_kit=args.with_recovery_kit)
        report['status'] = 'verified'
        report['steps'].extend(['verified-efi-and-normal-boot', 'normalized-permissions', 'final-audit-passed'])
        report['efi_after'] = {'SystemProductName': builder.MODEL, 'BoardProduct': fix_efi.BOARD, 'UpdateDataHub': True}
        log('Next: eject the USB and follow the README installation steps.')
        log('This command does not erase the internal disk, install macOS, or guarantee a successful boot.')
    except Exception as exc:
        report['status'] = 'incomplete'
        report['error'] = str(exc)
        for handle in log_handles:
            handle.write('STOP: ' + str(exc) + '\n')
        raise
    finally:
        try:
            encoded = json.dumps(report, indent=2) + '\n'
            (run_dir / 'report.json').write_text(encoded)
            if usb_log_dir is not None:
                try:
                    (usb_log_dir / 'report.json').write_text(encoded)
                except OSError as exc:
                    if report['status'] == 'verified':
                        report['status'] = 'incomplete'
                        report['error'] = 'USB report could not be saved: ' + str(exc)
                        (run_dir / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
                        raise OSError(report['error']) from exc
                    print('USB report copy failed; host report remains at ' + str(run_dir) + ': ' + str(exc))
            if report['status'] == 'verified':
                log('PASS: supported USB preparation and report saving complete.')
        finally:
            for handle in log_handles:
                handle.close()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, KeyError) as exc:
        raise SystemExit('STOP: ' + str(exc))
