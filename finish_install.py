#!/usr/bin/env python3
"""Preserve the model fixes after OCLP installs OpenCore to this Mac's internal EFI."""
import argparse
import datetime
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys

import build_kit as builder
import fix_efi
from prepare_usb import check_boot_files, safe_path


def validate_host():
    model = subprocess.check_output(['/usr/sbin/sysctl', '-n', 'hw.model'], text=True).strip()
    build = subprocess.check_output(['/usr/bin/sw_vers', '-buildVersion'], text=True).strip()
    if model != builder.MODEL or build != builder.BUILD:
        raise ValueError('Run this on the installed MacBookPro11,3 running ' + builder.BUILD
                         + ', not the preparation Mac or Recovery. No EFI changed.')


def internal_efi():
    """Follow the running APFS system to its physical disk; never assume disk0."""
    root = builder.disk_info('/')
    stores = root.get('APFSPhysicalStores', [])
    if root.get('Internal') is not True or root.get('FilesystemType') != 'apfs' or len(stores) != 1:
        raise ValueError('Expected the running system on one internal APFS physical store.')
    store_id = stores[0].get('APFSPhysicalStore', '')
    if not re.fullmatch(r'disk[0-9]+s[0-9]+', store_id):
        raise ValueError('Cannot identify the running system physical store safely.')
    store = builder.disk_info(store_id)
    parent = store.get('ParentWholeDisk', '')
    if store.get('Internal') is not True or not re.fullmatch(r'disk[0-9]+', parent):
        raise ValueError('Running APFS storage is not a verified internal physical disk.')
    listing = plistlib.loads(subprocess.check_output(['/usr/sbin/diskutil', 'list', '-plist', parent]))
    candidates = []
    for disk in listing.get('AllDisksAndPartitions', []):
        if disk.get('DeviceIdentifier') != parent:
            continue
        for part in disk.get('Partitions', []):
            device = part.get('DeviceIdentifier', '')
            if not re.fullmatch(r'disk[0-9]+s[0-9]+', device):
                continue
            info = builder.disk_info(device)
            if (info.get('Content') == 'EFI' and info.get('Internal') is True
                    and info.get('ParentWholeDisk') == parent and info.get('DiskUUID')):
                candidates.append(info)
    if len(candidates) != 1:
        raise ValueError('Expected exactly one EFI on the running system internal disk.')
    return candidates[0]


def same_efi(original, current):
    for key in ('DeviceIdentifier', 'DiskUUID', 'ParentWholeDisk', 'Content', 'Internal'):
        if original.get(key) != current.get(key):
            raise ValueError('Internal EFI identity changed; stopping without a config write.')


def mounted_config(info, check=False):
    device = info['DeviceIdentifier']
    if not info.get('MountPoint'):
        command = ['/usr/sbin/diskutil', 'mount']
        if check:
            command.append('readOnly')
        subprocess.run(command + [device], check=True)
    current = builder.disk_info(device)
    same_efi(info, current)
    mount = current.get('MountPoint')
    if not mount or not os.path.ismount(mount):
        raise ValueError('The internal EFI did not mount; run with sudo.')
    if not check and current.get('WritableVolume') is False:
        raise ValueError('Internal EFI is read-only. Unmount that EFI normally, then rerun; no force-unmount is attempted.')
    config = safe_path(Path(mount), 'EFI/OC/config.plist')
    if not config.is_file():
        raise ValueError('Internal OpenCore is missing. In OCLP RC3, Build and Install OpenCore '
                         'for MacBookPro11,3 to the INTERNAL disk EFI first, then rerun before rebooting.')
    return config


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Audit only; mount an unmounted internal EFI read-only')
    args = parser.parse_args(argv)
    if sys.version_info < (3, 9):
        raise ValueError('Python 3.9 or newer is required on the target MacBook.')
    validate_host()
    initial = internal_efi()
    config = mounted_config(initial, args.check)
    before = config.read_bytes()
    expected = fix_efi.update_config(plistlib.loads(before), normal_boot=True)
    layout = check_boot_files(config)
    if args.check:
        if plistlib.loads(before) != expected:
            raise ValueError('Internal EFI needs the model/normal-boot fixes. Rerun without --check.')
        print('PASS: internal EFI files and model settings verify. A USB-free reboot still needs testing.')
        return
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    log_dir = safe_path(builder.BASE, 'build/internal-efi/' + stamp)
    log_dir.mkdir(parents=True)
    # Keep a host copy before the backed-up atomic EFI edit, even if verification fails.
    (log_dir / 'config.before.plist').write_bytes(before)
    report = {'status': 'incomplete', 'model': builder.MODEL, 'build': builder.BUILD,
              'efi_device': initial['DeviceIdentifier'], 'boot_layout': layout,
              'usb_free_boot_verified': False}
    try:
        validate_host()
        same_efi(initial, internal_efi())
        same_efi(initial, builder.disk_info(config.parents[2]))
        if mounted_config(initial) != config:
            raise ValueError('Internal EFI mount changed; stopping.')
        backup = fix_efi.apply_config(config, normal_boot=True, expected_bytes=before)
        report['efi_backup'] = str(backup) if backup else None
        report['boot_layout'] = check_boot_files(config)
        if plistlib.loads(config.read_bytes()) != expected:
            raise ValueError('Internal EFI settings did not verify. Keep the working USB connected.')
        report['status'] = 'configuration-verified-awaiting-boot-test'
    except Exception as exc:
        report['error'] = str(exc)
        raise
    finally:
        (log_dir / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print('Internal EFI backup/report:', log_dir)
    print('PASS: internal EFI configuration verified; this is NOT a USB-free boot result.')
    print('Shut down, unplug the USB, start holding Option, and select INTERNAL EFI Boot, then Macintosh HD.')
    print('If boot fails, reconnect the unchanged USB and boot through its EFI Boot. Do not erase Tahoe.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, plistlib.InvalidFileException) as exc:
        raise SystemExit('STOP: ' + str(exc))
