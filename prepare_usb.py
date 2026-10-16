#!/usr/bin/env python3
"""Prepare a verified Tahoe installer USB for MacBookPro11,3; never erase/install macOS."""
import argparse
import datetime
import json
import os
import tempfile
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
    core = safe_path(efi, 'OC/OpenCore.efi')
    if not core.is_file() or not core.stat().st_size:
        raise ValueError('Missing OpenCore boot file: OC/OpenCore.efi. '
                         'Use OCLP Build and Install OpenCore for MacBookPro11,3 on this USB EFI, then rerun.')
    # RC3 normally installs the Apple bootstrap on genuine Macs. Its optional
    # boot_efi setting moves that file into the standard UEFI fallback path.
    # Both are supported; never invent/copy a second loader to satisfy a check.
    layouts = []
    for label, root, relative in [
        ('Apple', config_path.parents[2], 'System/Library/CoreServices/boot.efi'),
        ('UEFI', efi, 'BOOT/BOOTx64.efi'),
    ]:
        path = safe_path(root, relative)
        if path.is_file() and path.stat().st_size:
            layouts.append(label)
    if not layouts:
        raise ValueError('No supported OCLP bootstrap found on this USB EFI: expected '
                         'System/Library/CoreServices/boot.efi or EFI/BOOT/BOOTx64.efi. '
                         'Use OCLP Build and Install OpenCore for MacBookPro11,3 on this USB EFI, then rerun.')
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
    return ' + '.join(layouts)


def ensure_writable_efi(usb, config):
    """Remount only the already validated same-USB EFI; never force-unmount."""
    fix_efi.validate_config(usb, config)
    info = builder.disk_info(config.parents[2])
    if info.get('WritableVolume') is not False:
        return config
    if info.get('WritableMedia') is False:
        raise ValueError('USB EFI media is read-only; check physical write protection or use a writable USB.')
    device = info.get('DeviceIdentifier')
    if not device or not re.fullmatch(r'disk[0-9]+s[0-9]+', device):
        raise ValueError('Read-only EFI cannot be safely identified for remounting.')
    original = config.read_bytes()
    subprocess.run(['/usr/sbin/diskutil', 'unmount', device], check=True, capture_output=True, text=True)
    subprocess.run(['/usr/sbin/diskutil', 'mount', device], check=True, capture_output=True, text=True)
    current = builder.disk_info(device)
    if info.get('DiskUUID') and current.get('DiskUUID') != info['DiskUUID']:
        raise ValueError('EFI identity changed while remounting; stopping.')
    mount = current.get('MountPoint')
    if not mount or current.get('WritableVolume') is False:
        raise ValueError('USB EFI is still read-only after remounting.')
    path = fix_efi.validate_config(usb, Path(mount) / 'EFI/OC/config.plist')
    if path.read_bytes() != original:
        raise ValueError('EFI config changed while remounting; review it before retrying.')
    return path


def check_write_access(usb, config):
    # Remove both probes immediately. These test filesystem write access,
    # including read-only mounts, before downloading or replacing packages.
    for directory in [usb, safe_path(usb, 'Library'), safe_path(usb, 'Library/Packages'), config.parent]:
        if not directory.exists():
            continue
        probe = None
        try:
            fd, probe = tempfile.mkstemp(prefix='.mbp113-preflight-', dir=str(directory))
            os.close(fd)
        finally:
            if probe is not None:
                os.unlink(probe)


def check_build_tools(recovery_kit=False):
    if sys.version_info < (3, 9):
        raise ValueError('Python 3.9 or newer is required on the working Mac.')
    if not recovery_kit:
        return
    result = subprocess.run(['/usr/bin/xcrun', '--find', 'clang'], capture_output=True, text=True)
    if result.returncode:
        raise ValueError('Optional Recovery kit needs Xcode Command Line Tools: run xcode-select --install.')


def next_actions(error):
    message = str(error).lower()
    if 'read-only' in message or 'permission' in message or getattr(error, 'errno', None) in (13, 30):
        return ['Run preparation with sudo and check that the USB is writable. Keep its contents and backups.',
                'If the EFI is busy, close windows using it and rerun; the tool never force-unmounts a busy volume.']
    if any(term in message for term in ['bootstrap', 'missing opencore', 'missing enabled', 'built for', 'target model']):
        return ['Select MacBookPro11,3 in OCLP RC3, Build and Install OpenCore onto this USB EFI, then rerun preparation.',
                'Do not recreate the macOS installer just to repair an incomplete OpenCore EFI.']
    if 'installer must be exactly' in message:
        return ['Use the supported Tahoe 26.7.1 installer, build 25G241. Other builds need separate review.']
    if 'sha-256' in message or 'checksum' in message:
        return ['Keep the reported file for inspection and use the exact official package linked in the README.',
                'Do not bypass checksum verification; rerun with a verified local package or corrected cache.']
    if any(term in message for term in ['download', 'urlopen', 'timed out', 'network', 'http error', 'dns', 'ssl']):
        return ['Check internet access and rerun; completed verified downloads are reused.',
                'If downloading remains unavailable, supply the pinned official packages with --assets-pkg and --kdk-pkg as shown in the README.']
    if 'space' in message:
        return ['Free space on the volume named in the error, retain backups, and rerun the same command.']
    if 'xcode' in message or 'clang' in message or 'xcrun' in message:
        return ['Install Xcode Command Line Tools for --with-recovery-kit, or omit that flag for installer-only preparation.']
    if 'changed' in message or 'same external usb' in message:
        return ['Reconnect the intended USB, close other tools modifying its EFI, and rerun the command against its current mount.']
    if isinstance(error, subprocess.CalledProcessError) and 'diskutil' in str(error.cmd):
        return ['Close windows using the USB EFI, check its mount in Disk Utility, and rerun with sudo. No force-unmount is attempted.']
    return ['Read prepare.log for the failed step; retain the saved backups and report.',
            'Correct the reported cause and rerun the same preparation command. Do not run repair.sh as a substitute for USB preparation.']


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
    parser.add_argument('--with-recovery-kit', action='store_true', help='Also build the experimental Recovery fallback; requires Xcode Command Line Tools')
    parser.add_argument('--assets-pkg', type=Path)
    parser.add_argument('--kdk-pkg', type=Path)
    parser.add_argument('--cache', type=Path, default=builder.BASE / 'build/downloads')
    args = parser.parse_args(argv)
    usb, partition = builder.validate_usb(args.usb)
    cache = args.cache.resolve()
    if cache == usb or usb in cache.parents:
        raise ValueError("Download cache must be on the host, outside the installer USB.")
    config = fix_efi.validate_config(usb, args.config or find_config(usb, read_only=args.check))
    boot_layout = check_boot_files(config)
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
              'status': 'incomplete', 'steps': [], 'boot_layout': boot_layout,
              'phase': 'starting', 'next_steps': ['Retain the logs and backups, then rerun preparation after resolving the reported cause.'],
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
        log('Detected OpenCore boot layout: ' + boot_layout)
        log('Host log, report and package backups: ' + str(run_dir))
        report['phase'] = 'preflight'
        log('[1/4] Checking write access and preparation requirements.')
        config = ensure_writable_efi(usb, config)
        assert_same_usb(usb, partition)
        check_write_access(usb, config)
        try:
            verify_installer(usb)
            if args.with_recovery_kit:
                verify_payloads(usb, partition)
            log('Existing selected payloads verify; reusing them.')
            report['steps'].append('verified-existing-payloads')
            log('[2/4] Selected packages already verify; downloads are unnecessary.')
        except (OSError, ValueError) as reason:
            check_build_tools(args.with_recovery_kit)
            report['phase'] = 'packages'
            report['payload_preparation_reason'] = str(reason)
            if isinstance(reason, FileNotFoundError):
                status = ('Required installer packages or optional kit files are missing.' if args.with_recovery_kit
                          else 'Installer packages are missing.')
            else:
                status = 'Existing selected files need replacement.'
            log('[2/4] ' + status + ' Preparing verified official copies automatically.')
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
                last_line = ''
                for line in process.stdout:
                    log(line.rstrip('\n'))
                    if line.strip():
                        last_line = line.strip()
                if process.wait():
                    raise ValueError('Offline package preparation failed: ' + last_line + '; see prepare.log.')
            assert_same_usb(usb, partition)
            fix_efi.validate_config(usb, config)
            if config.read_bytes() != config_before:
                raise ValueError('EFI config changed during preparation; no deployment performed.')
            log('[2/4] Downloads and package checks complete. Backing up, copying and verifying files on USB; this can take a few minutes.')
            builder.deploy(output, usb, backup_dir=run_dir / 'usb-backups', recovery_kit=args.with_recovery_kit)
            report['steps'].append('deployed-selected-payloads-with-host-backups')
        assert_same_usb(usb, partition)
        fix_efi.validate_config(usb, config)
        report['phase'] = 'efi'
        log('[3/4] Backing up and applying the EFI configuration changes.')
        backup = fix_efi.apply_config(config, normal_boot=True, expected_bytes=config_before)
        report['efi_backup'] = str(backup) if backup else None
        report['phase'] = 'verification'
        log('[4/4] Verifying package hashes, permissions and boot configuration.')
        permissions(usb, repair=True, recovery_kit=args.with_recovery_kit)
        audit(usb, partition, config, recovery_kit=args.with_recovery_kit)
        report['status'] = 'verified'
        report['phase'] = 'complete'
        report['next_steps'] = ['Safely eject both USB volumes.', 'Follow README step 3 to install Tahoe through USB EFI Boot.']
        report['steps'].extend(['verified-efi-and-normal-boot', 'normalized-permissions', 'final-audit-passed'])
        report['efi_after'] = {'SystemProductName': builder.MODEL, 'BoardProduct': fix_efi.BOARD, 'UpdateDataHub': True}
        log('Next: eject the USB and follow the README installation steps.')
        log('This command does not erase the internal disk, install macOS, or guarantee a successful boot.')
    except Exception as exc:
        report['status'] = 'incomplete'
        report['error'] = str(exc)
        report['next_steps'] = next_actions(exc)
        for handle in log_handles:
            handle.write('STOP: ' + str(exc) + '\n')
            for action in report['next_steps']:
                handle.write('NEXT: ' + action + '\n')
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
                        report['phase'] = 'report-saving'
                        report['next_steps'] = ['Keep the USB connected and retain the host logs and backups.',
                                                'Resolve the USB write error and rerun preparation; require a final PASS.']
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
        print('STOP: ' + str(exc), file=sys.stderr)
        for action in next_actions(exc):
            print('NEXT: ' + action, file=sys.stderr)
        raise SystemExit(1)
