"""One-command workflow on disposable USB/EFI fixtures, never real disks."""
import contextlib
import io
import json
from pathlib import Path
import plistlib
import shutil
import sys
import tempfile
import subprocess

REAL_POPEN = subprocess.Popen
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build_kit as builder
import fix_efi
import prepare_usb as prepare


class AllInOneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.usb, self.efi, self.host = [self.root / n for n in ('usb', 'efi', 'host')]
        for p in (self.usb, self.efi, self.host): p.mkdir()
        shutil.copytree(builder.BASE / 'kit', self.host / 'kit')
        self.partition = '11111111-2222-4333-8444-555555555555'
        self.config = self.efi / 'EFI/OC/config.plist'
        self.config.parent.mkdir(parents=True)
        self.original = {
            '#Revision': {'Original-Model': builder.MODEL},
            'PlatformInfo': {'DataHub': {'SystemProductName': '', 'BoardProduct': ''}, 'UpdateDataHub': False},
            'NVRAM': {'Add': {fix_efi.APPLE_GUID: {'boot-args': '-v -x keepsyms=1'}, fix_efi.OCLP_GUID: {'OCLP-Model': builder.MODEL}}},
            'ACPI': {'Add': [{'Enabled': True, 'Path': 'SSDT.aml'}]},
            'UEFI': {'Drivers': [{'Enabled': True, 'Path': 'OpenRuntime.efi'}]},
            'Kernel': {'Add': [{'Enabled': True, 'BundlePath': 'Lilu.kext', 'PlistPath': 'Contents/Info.plist', 'ExecutablePath': 'Contents/MacOS/Lilu'}]},
        }
        self.config.write_bytes(plistlib.dumps(self.original))
        for name in ('BOOT/BOOTx64.efi', 'OC/OpenCore.efi', 'OC/Drivers/OpenRuntime.efi', 'OC/ACPI/SSDT.aml',
                     'OC/Kexts/Lilu.kext/Contents/Info.plist', 'OC/Kexts/Lilu.kext/Contents/MacOS/Lilu'):
            p = self.efi / 'EFI' / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'boot fixture')
        version = self.usb / 'System/Library/CoreServices/SystemVersion.plist'
        version.parent.mkdir(parents=True)
        version.write_bytes(plistlib.dumps({'ProductVersion': builder.VERSION, 'ProductBuildVersion': builder.BUILD}))
        self.asset, self.kdk = b'assets fixture', b'kdk fixture'
        self.stack = contextlib.ExitStack(); self.addCleanup(self.stack.close)
        for target, name, value in [(builder, 'BASE', self.host), (builder, 'ASSETS_SHA', self.hash_bytes(self.asset)),
                                    (builder, 'KDK_PKG_SHA', self.hash_bytes(self.kdk))]:
            self.stack.enter_context(patch.object(target, name, value))
        self.stack.enter_context(patch.object(builder, 'disk_info', side_effect=self.disk_info))
        self.stack.enter_context(patch.object(fix_efi, 'disk_info', side_effect=self.disk_info))
        self.stack.enter_context(patch.object(fix_efi.os.path, 'ismount', side_effect=lambda p: Path(p) in (self.usb, self.efi)))
        self.stack.enter_context(patch.object(prepare, 'find_config', return_value=self.config))
        def native_run(args, **kwargs):
            with patch.object(subprocess, 'Popen', REAL_POPEN):
                return subprocess.run([str(a) for a in args], check=True, **kwargs)
        self.stack.enter_context(patch.object(builder, 'run', side_effect=native_run))
        self.child = self.stack.enter_context(patch.object(prepare.subprocess, 'Popen', side_effect=self.fake_build))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    @staticmethod
    def hash_bytes(data):
        import hashlib
        return hashlib.sha256(data).hexdigest()

    def disk_info(self, path):
        if Path(path) == self.usb:
            return {'Internal': False, 'FilesystemType': 'hfs', 'MountPoint': str(self.usb),
                    'DiskUUID': self.partition, 'ParentWholeDisk': 'disk99'}
        return {'Content': 'EFI', 'Internal': False, 'MountPoint': str(self.efi), 'ParentWholeDisk': 'disk99'}

    def payload(self, output):
        output.mkdir(parents=True, exist_ok=True)
        for relative in prepare.REQUIRED:
            p = output / relative; p.parent.mkdir(parents=True, exist_ok=True)
            name = Path(relative).name
            if relative == 'Library/Packages/AutoPkg-Assets.pkg': p.write_bytes(self.asset)
            elif relative == 'Library/Packages/KDK.pkg': p.write_bytes(self.kdk)
            elif name == 'common.sh': p.write_text((self.host / 'kit/common.sh').read_text().replace('__USB_PARTITION_UUID__', self.partition))
            elif (self.host / 'kit' / name).is_file(): shutil.copy2(self.host / 'kit' / name, p)
            else: p.write_bytes(b'archive fixture')
        self.manifest(output)
        prepare.permissions(output, repair=True)

    def manifest(self, output):
        (output / 'MBP113-Repair/SHA256SUMS').write_text(''.join(
            builder.digest(output / r) + '  ' + r + '\n' for r in sorted(prepare.REQUIRED)))

    def fake_build(self, command, **kwargs):
        self.payload(Path(command[command.index('--output') + 1]))
        class Process:
            stdout = ['fixture assembly completed\n']
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def wait(self): return 0
        return Process()

    def run_prepare(self, *extra):
        prepare.main(['--usb', str(self.usb), '--cache', str(self.host / 'cache'), *extra])

    def snapshot(self, root):
        return {str(p.relative_to(root)): (p.stat().st_mode & 0o777, p.read_bytes() if p.is_file() else None)
                for p in root.rglob('*')}

    def test_fresh_usb_download_build_deploy_efi_permissions_and_logs(self):
        old_boot = (self.efi / 'EFI/BOOT/BOOTx64.efi').read_bytes()
        self.run_prepare()
        self.child.assert_called_once()
        command = self.child.call_args.args[0]
        self.assertIn('--download', command)
        prepare.audit(self.usb, self.partition, self.config)
        config = plistlib.loads(self.config.read_bytes())
        self.assertEqual(config['NVRAM']['Add'][fix_efi.APPLE_GUID]['boot-args'], '-v keepsyms=1')
        self.assertIn('boot-args', config['NVRAM']['Delete'][fix_efi.APPLE_GUID])
        self.assertEqual((self.efi / 'EFI/BOOT/BOOTx64.efi').read_bytes(), old_boot)
        self.assertEqual(len(list(self.config.parent.glob('config.before-datahub-*.plist'))), 1)
        for root in (self.host / 'build/runs', self.usb / 'Repair-Logs'):
            report = json.loads(next(root.rglob('report.json')).read_text())
            self.assertEqual(report['status'], 'verified')
            self.assertTrue(next(root.rglob('prepare.log')).stat().st_size)

    def test_existing_kit_is_reused_and_rerun_is_idempotent(self):
        self.payload(self.usb)
        self.run_prepare(); first = self.config.read_bytes()
        self.run_prepare()
        self.child.assert_not_called()
        self.assertEqual(self.config.read_bytes(), first)
        self.assertEqual(len(list(self.config.parent.glob('config.before-datahub-*.plist'))), 1)

    def test_audit_only_changes_no_files_or_modes(self):
        self.payload(self.usb)
        self.config.write_bytes(plistlib.dumps(fix_efi.update_config(self.original, True)))
        before = (self.snapshot(self.usb), self.snapshot(self.efi), self.snapshot(self.host))
        self.run_prepare('--check')
        self.assertEqual(before, (self.snapshot(self.usb), self.snapshot(self.efi), self.snapshot(self.host)))
        self.child.assert_not_called()

    def test_corrupt_assets_and_helper_are_repaired_with_old_files_saved(self):
        self.payload(self.usb)
        (self.usb / 'Library/Packages/AutoPkg-Assets.pkg').write_bytes(b'bad package')
        (self.usb / 'repair.sh').write_bytes(b'old script')
        self.run_prepare()
        prepare.audit(self.usb, self.partition, self.config)
        backups = list((self.host / 'build/runs').rglob('usb-backups'))
        self.assertEqual((backups[0] / 'repair.sh').read_bytes(), b'old script')
        self.assertEqual((backups[0] / 'Library/Packages/AutoPkg-Assets.pkg').read_bytes(), b'bad package')
        self.assertNotIn('--assets-pkg', self.child.call_args.args[0])
        self.assertIn('--kdk-pkg', self.child.call_args.args[0])

    def test_permissions_are_repaired_without_rebuilding(self):
        self.payload(self.usb); (self.usb / 'MBP113-Repair/recovery-tool').chmod(0o644)
        self.run_prepare(); self.child.assert_not_called()
        self.assertEqual((self.usb / 'MBP113-Repair/recovery-tool').stat().st_mode & 0o777, 0o755)

    def test_wrong_model_fails_before_usb_write_or_download(self):
        self.original['#Revision']['Original-Model'] = 'iMac15,1'
        self.config.write_bytes(plistlib.dumps(self.original))
        before = self.snapshot(self.usb)
        with self.assertRaisesRegex(ValueError, 'built for'): self.run_prepare()
        self.assertEqual(self.snapshot(self.usb), before); self.child.assert_not_called()

    def test_missing_enabled_kext_fails_before_usb_write_or_download(self):
        (self.efi / 'EFI/OC/Kexts/Lilu.kext/Contents/MacOS/Lilu').unlink()
        before = self.snapshot(self.usb)
        with self.assertRaisesRegex(ValueError, 'Missing enabled kext'): self.run_prepare()
        self.assertEqual(self.snapshot(self.usb), before); self.child.assert_not_called()

    def test_wrong_efi_and_nested_backup_config_are_rejected(self):
        with patch.object(fix_efi, 'disk_info', return_value={'Internal': True, 'Content': 'EFI', 'ParentWholeDisk': 'disk0'}):
            with self.assertRaisesRegex(ValueError, 'same external USB'): self.run_prepare()
        nested = self.efi / 'backup/EFI/OC/config.plist'; nested.parent.mkdir(parents=True); shutil.copy2(self.config, nested)
        with self.assertRaisesRegex(ValueError, 'volume root'): fix_efi.validate_config(self.usb, nested)
        self.child.assert_not_called()

    def test_changed_config_after_build_aborts_before_deployment(self):
        def change(command, **kwargs):
            proc = self.fake_build(command, **kwargs); self.config.write_bytes(b'concurrent change'); return proc
        self.child.side_effect = change
        with self.assertRaises(Exception): self.run_prepare()
        self.assertFalse((self.usb / 'repair.sh').exists())
        self.assertEqual(self.config.read_bytes(), b'concurrent change')
        self.assertEqual(json.loads(next((self.usb / 'Repair-Logs').rglob('report.json')).read_text())['status'], 'incomplete')

    def test_changed_usb_identity_aborts_before_deployment(self):
        def change(command, **kwargs):
            proc = self.fake_build(command, **kwargs)
            self.partition = '22222222-2222-4333-8444-555555555555'; return proc
        self.child.side_effect = change
        with self.assertRaisesRegex(ValueError, 'identity changed'): self.run_prepare()
        self.assertFalse((self.usb / 'repair.sh').exists())
        self.assertEqual(plistlib.loads(self.config.read_bytes()), self.original)

    def test_symlink_destination_blocks_deployment_and_preserves_external_file(self):
        outside = self.root / 'outside'; outside.write_bytes(b'preserve')
        (self.usb / 'repair.sh').symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'symlinked'): self.run_prepare()
        self.assertEqual(outside.read_bytes(), b'preserve')
        self.assertEqual(plistlib.loads(self.config.read_bytes()), self.original)

    def test_cache_on_usb_rejected_before_writes(self):
        with self.assertRaisesRegex(ValueError, 'cache must be'): self.run_prepare('--cache', str(self.usb / 'cache'))
        self.assertFalse((self.usb / 'Repair-Logs').exists()); self.child.assert_not_called()

    def test_duplicate_manifest_and_wrong_partition_rejected(self):
        self.payload(self.usb)
        manifest = self.usb / 'MBP113-Repair/SHA256SUMS'; original = manifest.read_text()
        manifest.write_text(original + original.splitlines()[0] + '\n')
        with self.assertRaisesRegex(ValueError, 'duplicate'): prepare.verify_payloads(self.usb, self.partition)
        manifest.write_text(original)
        with self.assertRaisesRegex(ValueError, 'different USB'): prepare.verify_payloads(self.usb, 'WRONG')

    def test_failed_builder_leaves_usb_packages_and_efi_untouched(self):
        def fail(command, **kwargs):
            process = self.fake_build(command, **kwargs)
            process.wait = lambda: 1
            return process
        self.child.side_effect = fail
        with self.assertRaisesRegex(ValueError, 'preparation failed'): self.run_prepare()
        self.assertFalse((self.usb / 'repair.sh').exists())
        self.assertEqual(plistlib.loads(self.config.read_bytes()), self.original)
        report = json.loads(next((self.usb / 'Repair-Logs').rglob('report.json')).read_text())
        self.assertEqual(report['status'], 'incomplete')
        self.assertIn('preparation failed', report['error'])

    def test_broken_helper_mode_is_fixed_during_incomplete_kit_deployment(self):
        self.payload(self.usb)
        (self.usb / 'Library/Packages/KDK.pkg').unlink()
        (self.usb / 'MBP113-Repair/recovery-tool').chmod(0o644)
        self.run_prepare()
        prepare.audit(self.usb, self.partition, self.config)

    def test_concurrent_efi_write_is_not_overwritten(self):
        original = self.config.read_bytes(); self.config.write_bytes(b'new data')
        with self.assertRaisesRegex(ValueError, 'changed during preparation'):
            fix_efi.apply_config(self.config, True, expected_bytes=original)
        self.assertEqual(self.config.read_bytes(), b'new data')
        self.assertEqual(list(self.config.parent.glob('config.before-datahub*')), [])


class EfiDiscoveryTests(unittest.TestCase):
    def discover(self, *, readonly=False, candidates=1):
        devices = ['disk99s' + str(i + 1) for i in range(candidates)]
        listing = plistlib.dumps({'AllDisksAndPartitions': [{'Partitions': [{'DeviceIdentifier': d} for d in devices]}]})
        mounted = False
        def info(path):
            if Path(path) == Path('/fixture/usb'): return {'ParentWholeDisk': 'disk99'}
            result = {'Content': 'EFI', 'ParentWholeDisk': 'disk99', 'Internal': False}
            if mounted: result['MountPoint'] = '/fixture/efi'
            return result
        def mount(*args, **kwargs):
            nonlocal mounted
            mounted = True
        with patch.object(builder, 'disk_info', side_effect=info), patch.object(prepare.subprocess, 'check_output', return_value=listing), patch.object(prepare.subprocess, 'run', side_effect=mount) as command:
            result = prepare.find_config(Path('/fixture/usb'), read_only=readonly)
            return result, command.call_args.args[0]

    def test_discovers_same_usb_efi_and_mounts(self):
        result, command = self.discover()
        self.assertEqual(result, Path('/fixture/efi/EFI/OC/config.plist'))
        self.assertEqual(command, ['/usr/sbin/diskutil', 'mount', 'disk99s1'])

    def test_audit_mounts_read_only(self):
        self.assertEqual(self.discover(readonly=True)[1], ['/usr/sbin/diskutil', 'mount', 'readOnly', 'disk99s1'])

    def test_ambiguous_efi_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'exactly one EFI'): self.discover(candidates=2)


if __name__ == '__main__': unittest.main()
