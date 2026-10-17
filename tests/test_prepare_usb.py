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
import finish_bundle


class UsbFixtures:
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
        self.stack.enter_context(patch.object(prepare, 'check_build_tools'))
        def native_run(args, **kwargs):
            with patch.object(subprocess, 'Popen', REAL_POPEN):
                return subprocess.run([str(a) for a in args], check=True, **kwargs)
        self.stack.enter_context(patch.object(builder, 'run', side_effect=native_run))
        self.child = self.stack.enter_context(patch.object(prepare.subprocess, 'Popen', side_effect=self.fake_build))
        self.output = io.StringIO()
        self.stack.enter_context(contextlib.redirect_stdout(self.output))

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
        prepare.permissions(output, repair=True, recovery_kit=True)

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
        prepare.main(['--usb', str(self.usb), '--cache', str(self.host / 'cache'), '--with-recovery-kit', *extra])

    def snapshot(self, root):
        return {str(p.relative_to(root)): (p.stat().st_mode & 0o777, p.read_bytes() if p.is_file() else None)
                for p in root.rglob('*')}



class RecoveryKitPreparationTests(UsbFixtures, unittest.TestCase):
    def test_fresh_usb_download_build_deploy_efi_permissions_and_logs(self):
        old_boot = (self.efi / 'EFI/BOOT/BOOTx64.efi').read_bytes()
        self.run_prepare()
        self.child.assert_called_once()
        command = self.child.call_args.args[0]
        self.assertIn('--download', command)
        prepare.audit(self.usb, self.partition, self.config, recovery_kit=True)
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
        finish_bundle.install(self.usb, self.host / 'fixture-finish-backups')
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
        prepare.audit(self.usb, self.partition, self.config, recovery_kit=True)
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
        with self.assertRaisesRegex(ValueError, 'symlink'): self.run_prepare()
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
        prepare.audit(self.usb, self.partition, self.config, recovery_kit=True)

    def test_concurrent_efi_write_is_not_overwritten(self):
        original = self.config.read_bytes(); self.config.write_bytes(b'new data')
        with self.assertRaisesRegex(ValueError, 'changed during preparation'):
            fix_efi.apply_config(self.config, True, expected_bytes=original)
        self.assertEqual(self.config.read_bytes(), b'new data')
        self.assertEqual(list(self.config.parent.glob('config.before-datahub*')), [])


class InstallerOnlyTests(UsbFixtures, unittest.TestCase):
    def run_prepare(self, *extra):
        prepare.main(['--usb', str(self.usb), '--cache', str(self.host / 'cache'), *extra])

    def packages(self, output):
        for name, data in [('AutoPkg-Assets.pkg', self.asset), ('KDK.pkg', self.kdk)]:
            path = output / 'Library/Packages' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def fake_build(self, command, **kwargs):
        self.packages(Path(command[command.index('--output') + 1]))
        class Process:
            stdout = ['fixture packages copied\n']
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def wait(self): return 0
        return Process()

    def test_writable_efi_is_not_remounted(self):
        with patch.object(prepare.subprocess, 'run') as command:
            self.assertEqual(prepare.ensure_writable_efi(self.usb, self.config), self.config)
        command.assert_not_called()

    def test_readonly_efi_is_remounted_without_force_and_preserves_config(self):
        mounted_writable = False
        def info(path):
            result = self.disk_info(path)
            if Path(path) != self.usb:
                result.update(DeviceIdentifier='disk99s1', WritableVolume=mounted_writable,
                              WritableMedia=True, DiskUUID='33333333-2222-4333-8444-555555555555')
            return result
        def mount(command, **kwargs):
            nonlocal mounted_writable
            if command[1] == 'mount': mounted_writable = True
        before = self.config.read_bytes()
        with patch.object(builder, 'disk_info', side_effect=info), patch.object(prepare.subprocess, 'run', side_effect=mount) as command:
            self.assertEqual(prepare.ensure_writable_efi(self.usb, self.config), self.config)
        self.assertEqual([c.args[0] for c in command.call_args_list],
                         [['/usr/sbin/diskutil', 'unmount', 'disk99s1'], ['/usr/sbin/diskutil', 'mount', 'disk99s1']])
        self.assertEqual(self.config.read_bytes(), before)

    def test_busy_efi_remount_stops_without_force_or_replacement(self):
        def info(path):
            result = self.disk_info(path)
            result.update(DeviceIdentifier='disk99s1', WritableVolume=False, WritableMedia=True)
            return result
        failure = subprocess.CalledProcessError(1, ['/usr/sbin/diskutil', 'unmount', 'disk99s1'], stderr='busy')
        with patch.object(builder, 'disk_info', side_effect=info), patch.object(prepare.subprocess, 'run', side_effect=failure) as command:
            with self.assertRaises(subprocess.CalledProcessError): prepare.ensure_writable_efi(self.usb, self.config)
        command.assert_called_once()
        self.assertNotIn('force', command.call_args.args[0])
        self.assertIn('sudo', ' '.join(prepare.next_actions(failure)))

    def test_changed_efi_identity_stops_after_remount(self):
        writable = False
        def info(path):
            result = self.disk_info(path)
            result.update(DeviceIdentifier='disk99s1', WritableVolume=writable, WritableMedia=True,
                          DiskUUID='new-id' if writable else 'original-id')
            return result
        def mount(command, **kwargs):
            nonlocal writable
            if command[1] == 'mount': writable = True
        with patch.object(builder, 'disk_info', side_effect=info), patch.object(prepare.subprocess, 'run', side_effect=mount):
            with self.assertRaisesRegex(ValueError, 'identity changed'): prepare.ensure_writable_efi(self.usb, self.config)
        self.assertEqual(plistlib.loads(self.config.read_bytes()), self.original)

    def test_write_probe_failure_records_next_step_before_downloads(self):
        with patch.object(prepare, 'check_write_access', side_effect=PermissionError(13, 'permission denied')):
            with self.assertRaises(PermissionError): self.run_prepare()
        self.child.assert_not_called()
        report = json.loads(next((self.usb / 'Repair-Logs').rglob('report.json')).read_text())
        self.assertEqual((report['status'], report['phase']), ('incomplete', 'preflight'))
        self.assertIn('sudo', ' '.join(report['next_steps']))
        self.assertEqual(plistlib.loads(self.config.read_bytes()), self.original)

    def test_write_probes_are_cleaned_up(self):
        before = (self.snapshot(self.usb), self.snapshot(self.efi))
        prepare.check_write_access(self.usb, self.config)
        self.assertEqual(before, (self.snapshot(self.usb), self.snapshot(self.efi)))

    def test_boot_error_next_step_does_not_require_recreating_installer(self):
        advice = prepare.next_actions(ValueError('No supported OCLP bootstrap'))
        self.assertIn('Build and Install OpenCore', advice[0])
        self.assertIn('Do not recreate', advice[1])


    def apple_bootstrap(self):
        path = self.efi / 'System/Library/CoreServices/boot.efi'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'Apple bootstrap fixture')
        return path

    def test_apple_layout_prepares_without_creating_uefi_fallback(self):
        apple = self.apple_bootstrap()
        (self.efi / 'EFI/BOOT/BOOTx64.efi').unlink()
        self.run_prepare()
        prepare.audit(self.usb, self.partition, self.config)
        self.assertEqual(apple.read_bytes(), b'Apple bootstrap fixture')
        self.assertFalse((self.efi / 'EFI/BOOT/BOOTx64.efi').exists())
        report = json.loads(next((self.usb / 'Repair-Logs').rglob('report.json')).read_text())
        self.assertEqual(report['boot_layout'], 'Apple')

    def test_both_bootstrap_layouts_are_accepted(self):
        self.apple_bootstrap()
        self.assertEqual(prepare.check_boot_files(self.config), 'Apple + UEFI')

    def test_no_bootstrap_stops_before_downloads_or_usb_writes(self):
        (self.efi / 'EFI/BOOT/BOOTx64.efi').unlink()
        before = self.snapshot(self.usb)
        with self.assertRaisesRegex(ValueError, 'No supported OCLP bootstrap'):
            self.run_prepare()
        self.child.assert_not_called()
        self.assertEqual(self.snapshot(self.usb), before)
        self.assertEqual(plistlib.loads(self.config.read_bytes()), self.original)

    def test_empty_apple_bootstrap_is_not_accepted(self):
        self.apple_bootstrap().write_bytes(b'')
        (self.efi / 'EFI/BOOT/BOOTx64.efi').unlink()
        with self.assertRaisesRegex(ValueError, 'No supported OCLP bootstrap'):
            self.run_prepare()
        self.child.assert_not_called()

    def test_symlinked_apple_bootstrap_is_rejected(self):
        path = self.apple_bootstrap(); path.unlink()
        outside = self.root / 'outside-loader'; outside.write_bytes(b'preserve')
        path.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.run_prepare()
        self.child.assert_not_called()
        self.assertEqual(outside.read_bytes(), b'preserve')

    def test_apple_bootstrap_still_requires_opencore_binary(self):
        self.apple_bootstrap()
        (self.efi / 'EFI/OC/OpenCore.efi').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing OpenCore boot file: OC/OpenCore.efi'):
            self.run_prepare()
        self.child.assert_not_called()


    def test_default_prepares_packages_and_efi_without_any_recovery_files(self):
        self.run_prepare()
        self.child.assert_called_once()
        self.assertIn('--installer-only', self.child.call_args.args[0])
        for relative in ['repair.sh', 'MBP113-Repair', 'KDK-25G241.tar.gz']:
            self.assertFalse((self.usb / relative).exists())
        prepare.audit(self.usb, self.partition, self.config)
        report = json.loads(next((self.usb / 'Repair-Logs').rglob('report.json')).read_text())
        self.assertEqual((report['mode'], report['status']), ('installer-only', 'verified'))
        self.assertEqual(plistlib.loads(self.config.read_bytes())['PlatformInfo']['DataHub']['BoardProduct'], fix_efi.BOARD)

    def test_missing_packages_use_plain_status_and_preserve_details_in_report(self):
        self.run_prepare()
        self.assertIn('Installer packages are missing.', self.output.getvalue())
        self.assertNotIn('[Errno 2]', self.output.getvalue())
        report = json.loads(next((self.usb / 'Repair-Logs').rglob('report.json')).read_text())
        self.assertIn('[Errno 2]', report['payload_preparation_reason'])

    def test_default_reuses_valid_packages_and_efi_on_repeat_run(self):
        self.packages(self.usb)
        self.run_prepare(); self.run_prepare()
        self.child.assert_not_called()
        self.assertEqual(len(list(self.config.parent.glob('config.before-datahub*'))), 1)

    def test_old_usb_gets_finishing_bundle_without_package_downloads(self):
        self.packages(self.usb)
        self.run_prepare()
        self.child.assert_not_called()
        finish_bundle.verify(self.usb)
        report = json.loads(next((self.usb / 'Repair-Logs').rglob('report.json')).read_text())
        self.assertEqual(report['finishing_tools']['folder'], 'MBP113-Finish')
        self.assertIn('finish_install.py', report['finishing_tools']['files'])

    def test_audit_rejects_missing_finishing_bundle_without_writes(self):
        self.packages(self.usb)
        prepare.permissions(self.usb, repair=True)
        self.config.write_bytes(plistlib.dumps(fix_efi.update_config(self.original, True)))
        before = (self.snapshot(self.usb), self.snapshot(self.efi))
        with self.assertRaises((OSError, ValueError)):
            self.run_prepare('--check')
        self.assertEqual(before, (self.snapshot(self.usb), self.snapshot(self.efi)))

    def test_default_ignores_and_preserves_old_optional_kit(self):
        kit = self.usb / 'MBP113-Repair'; kit.mkdir()
        (kit / 'common.sh').write_bytes(b'old kit, deliberately not audited')
        script = self.usb / 'repair.sh'; script.write_bytes(b'old script'); script.chmod(0o600)
        before = (self.snapshot(kit), script.read_bytes(), script.stat().st_mode)
        self.run_prepare()
        self.assertEqual(before, (self.snapshot(kit), script.read_bytes(), script.stat().st_mode))
        prepare.audit(self.usb, self.partition, self.config)
        with self.assertRaises((OSError, ValueError)):
            prepare.audit(self.usb, self.partition, self.config, recovery_kit=True)

    def test_default_audit_needs_no_kit_and_writes_nothing(self):
        self.packages(self.usb)
        finish_bundle.install(self.usb, self.host / 'fixture-finish-backups')
        prepare.permissions(self.usb, repair=True)
        self.config.write_bytes(plistlib.dumps(fix_efi.update_config(self.original, True)))
        before = (self.snapshot(self.usb), self.snapshot(self.efi), self.snapshot(self.host))
        self.run_prepare('--check')
        self.assertEqual(before, (self.snapshot(self.usb), self.snapshot(self.efi), self.snapshot(self.host)))
        self.child.assert_not_called()

    def test_default_repairs_and_backs_up_corrupt_package(self):
        self.packages(self.usb)
        (self.usb / 'Library/Packages/KDK.pkg').write_bytes(b'bad package')
        self.run_prepare()
        backup = next((self.host / 'build/runs').rglob('usb-backups/Library/Packages/KDK.pkg'))
        self.assertEqual(backup.read_bytes(), b'bad package')
        prepare.audit(self.usb, self.partition, self.config)
        self.assertFalse((self.usb / 'MBP113-Repair').exists())

    def test_default_audit_rejects_missing_package(self):
        self.packages(self.usb)
        self.config.write_bytes(plistlib.dumps(fix_efi.update_config(self.original, True)))
        (self.usb / 'Library/Packages/AutoPkg-Assets.pkg').unlink()
        with self.assertRaises(OSError): self.run_prepare('--check')
        self.child.assert_not_called()

    def test_installer_builder_local_packages_never_expand_or_compile(self):
        sources = self.host / 'sources'; self.packages(sources)
        output = self.host / 'installer-output'
        with patch.object(builder, 'assemble', side_effect=AssertionError('must not expand/compile')) as assembly:
            builder.main(['--usb', str(self.usb), '--installer-only',
                          '--assets-pkg', str(sources / 'Library/Packages/AutoPkg-Assets.pkg'),
                          '--kdk-pkg', str(sources / 'Library/Packages/KDK.pkg'), '--output', str(output)])
            assembly.assert_not_called()
        self.assertEqual({str(p.relative_to(output)) for p in output.rglob('*') if p.is_file()},
                         {'Library/Packages/AutoPkg-Assets.pkg', 'Library/Packages/KDK.pkg'})
        self.child.assert_not_called()

    def test_installer_builder_downloads_and_detaches_readonly_kdk_without_expansion(self):
        sources = self.host / 'downloaded'; self.packages(sources)
        mount = self.host / 'mounted-kdk'; mount.mkdir()
        (mount / 'KernelDebugKit.pkg').write_bytes(self.kdk)
        dmg = sources / 'KDK.dmg'; dmg.write_bytes(b'dmg fixture')
        def downloaded(name, cache):
            return sources / 'Library/Packages/AutoPkg-Assets.pkg' if name == 'AutoPkg-Assets.pkg' else dmg
        with patch.object(builder, 'download', side_effect=downloaded) as download, \
             patch.object(builder.subprocess, 'check_output', return_value=plistlib.dumps({'system-entities': [{'mount-point': str(mount)}]})) as attach, \
             patch.object(builder.subprocess, 'run') as detach, \
             patch.object(builder, 'assemble', side_effect=AssertionError('must not expand/compile')):
            builder.main(['--usb', str(self.usb), '--installer-only', '--download', '--output', str(self.host / 'download-output')])
        self.assertEqual([call.args[0] for call in download.call_args_list], ['AutoPkg-Assets.pkg', 'KDK-25G241.dmg'])
        self.assertIn('-readonly', attach.call_args.args[0])
        self.assertEqual(detach.call_args.args[0], ['/usr/bin/hdiutil', 'detach', str(mount)])

    def test_installer_deployment_rejects_extra_output_files(self):
        output = self.host / 'output'; self.packages(output)
        (output / 'unexpected').write_bytes(b'not managed')
        with self.assertRaisesRegex(ValueError, 'exactly the two pinned'):
            builder.deploy(output, self.usb, backup_dir=self.host / 'backups', recovery_kit=False)
        self.assertFalse((self.usb / 'Library').exists())


class PrerequisiteTests(unittest.TestCase):
    def test_default_does_not_need_compiler(self):
        with patch.object(prepare.subprocess, 'run') as command:
            prepare.check_build_tools(False)
        command.assert_not_called()

    def test_optional_compiler_missing_gives_specific_next_step(self):
        import types
        with patch.object(prepare.subprocess, 'run', return_value=types.SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(ValueError, 'xcode-select --install'):
                prepare.check_build_tools(True)


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
