"""Internal EFI handover fixtures. Never mount or write a physical disk."""
import contextlib
import io
from pathlib import Path
import json
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build_kit as builder
import fix_efi
import finish_install as finish


class InternalEfiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.mount = self.base / 'internal-efi'
        self.config = self.mount / 'EFI/OC/config.plist'
        self.config.parent.mkdir(parents=True)
        self.original = {
            '#Revision': {'Original-Model': builder.MODEL},
            'PlatformInfo': {'DataHub': {'SystemProductName': '', 'BoardProduct': ''}, 'UpdateDataHub': False},
            'NVRAM': {'Add': {fix_efi.APPLE_GUID: {'boot-args': '-v -x keepsyms=1'},
                              fix_efi.OCLP_GUID: {'OCLP-Model': builder.MODEL}}},
        }
        self.config.write_bytes(plistlib.dumps(self.original))
        for name in ('EFI/OC/OpenCore.efi', 'System/Library/CoreServices/boot.efi'):
            target = self.mount / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'fixture')
        self.root = {'Internal': True, 'FilesystemType': 'apfs',
                     'APFSPhysicalStores': [{'APFSPhysicalStore': 'disk42s2'}]}
        self.efi = {'DeviceIdentifier': 'disk42s1', 'Content': 'EFI', 'Internal': True,
                    'ParentWholeDisk': 'disk42', 'DiskUUID': 'fixture-internal-efi',
                    'MountPoint': str(self.mount), 'WritableVolume': True}
        self.model, self.build = builder.MODEL, builder.BUILD
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(builder, 'BASE', self.base))
        self.stack.enter_context(patch.object(builder, 'disk_info', side_effect=self.disk_info))
        self.stack.enter_context(patch.object(finish.subprocess, 'check_output', side_effect=self.output))
        self.run = self.stack.enter_context(patch.object(finish.subprocess, 'run'))
        self.stack.enter_context(patch.object(finish.os.path, 'ismount', side_effect=lambda p: Path(p) == self.mount))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def disk_info(self, path):
        if str(path) == '/':
            return dict(self.root)
        if str(path) == 'disk42s2':
            return {'Internal': True, 'ParentWholeDisk': 'disk42'}
        if str(path) == 'disk42s1' or Path(path) == self.mount:
            return dict(self.efi)
        raise AssertionError('Unexpected disk lookup: ' + str(path))

    def output(self, command, **kwargs):
        if command == ['/usr/sbin/sysctl', '-n', 'hw.model']:
            return self.model + '\n'
        if command == ['/usr/bin/sw_vers', '-buildVersion']:
            return self.build + '\n'
        if command == ['/usr/sbin/diskutil', 'list', '-plist', 'disk42']:
            return plistlib.dumps({'AllDisksAndPartitions': [{'DeviceIdentifier': 'disk42',
                                     'Partitions': [{'DeviceIdentifier': 'disk42s1'}]}]})
        raise AssertionError('Unexpected command: ' + str(command))

    def test_internal_changes_are_backed_up_and_reported_not_boot_verified(self):
        old = self.config.read_bytes()
        finish.main([])
        self.assertEqual(plistlib.loads(self.config.read_bytes()), fix_efi.update_config(self.original, True))
        self.assertEqual(next(self.base.glob('build/internal-efi/*/config.before.plist')).read_bytes(), old)
        self.assertEqual(next(self.config.parent.glob('config.before-datahub-*.plist')).read_bytes(), old)
        report = json.loads(next(self.base.glob('build/internal-efi/*/report.json')).read_text())
        self.assertEqual(report['status'], 'configuration-verified-awaiting-boot-test')
        self.assertFalse(report['usb_free_boot_verified'])
        self.assertEqual(report['efi_device'], 'disk42s1')
        self.run.assert_not_called()

    def test_repeat_keeps_config_unchanged(self):
        finish.main([])
        before = self.config.read_bytes()
        finish.main([])
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(len(list(self.config.parent.glob('config.before-datahub-*.plist'))), 1)

    def test_wrong_host_and_build_stop_before_mount_or_backup(self):
        for model, build in [('iMac15,1', builder.BUILD), (builder.MODEL, '25G999')]:
            self.model, self.build = model, build
            with self.assertRaisesRegex(ValueError, 'Run this on'):
                finish.main([])
        self.run.assert_not_called()
        self.assertFalse((self.base / 'build').exists())
        self.assertEqual(plistlib.loads(self.config.read_bytes()), self.original)

    def test_external_system_is_rejected(self):
        self.root['Internal'] = False
        with self.assertRaisesRegex(ValueError, 'internal APFS'):
            finish.main([])
        self.run.assert_not_called()

    def test_ambiguous_physical_storage_is_rejected(self):
        self.root['APFSPhysicalStores'].append({'APFSPhysicalStore': 'disk43s2'})
        with self.assertRaisesRegex(ValueError, 'one internal'):
            finish.main([])

    def test_external_or_unidentified_efi_is_rejected(self):
        for changes in ({'Internal': False}, {'ParentWholeDisk': 'disk99'}, {'DiskUUID': ''}):
            old = dict(self.efi)
            self.efi.update(changes)
            with self.assertRaisesRegex(ValueError, 'exactly one EFI'):
                finish.main([])
            self.efi = old

    def test_missing_opencore_has_actionable_guidance_and_no_write(self):
        self.config.unlink()
        with self.assertRaisesRegex(ValueError, 'INTERNAL disk EFI first'):
            finish.main([])
        self.assertFalse((self.base / 'build').exists())

    def test_wrong_config_target_is_rejected(self):
        self.original['#Revision']['Original-Model'] = 'iMac15,1'
        self.config.write_bytes(plistlib.dumps(self.original))
        with self.assertRaisesRegex(ValueError, 'built for'):
            finish.main([])
        self.assertFalse((self.base / 'build').exists())

    def test_symlink_config_is_rejected(self):
        elsewhere = self.base / 'elsewhere.plist'
        self.config.rename(elsewhere)
        self.config.symlink_to(elsewhere)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            finish.main([])
        self.assertEqual(plistlib.loads(elsewhere.read_bytes()), self.original)

    def test_missing_bootstrap_is_rejected(self):
        (self.mount / 'System/Library/CoreServices/boot.efi').unlink()
        with self.assertRaisesRegex(ValueError, 'bootstrap'):
            finish.main([])
        self.assertFalse((self.base / 'build').exists())

    def test_check_is_read_only_and_requires_fixed_config(self):
        with self.assertRaisesRegex(ValueError, 'needs the model'):
            finish.main(['--check'])
        self.config.write_bytes(plistlib.dumps(fix_efi.update_config(self.original, True)))
        before = self.config.read_bytes()
        finish.main(['--check'])
        self.assertEqual(self.config.read_bytes(), before)
        self.assertFalse((self.base / 'build').exists())
        self.run.assert_not_called()

    def test_unmounted_check_requests_read_only_mount(self):
        self.config.write_bytes(plistlib.dumps(fix_efi.update_config(self.original, True)))
        initial = dict(self.efi)
        initial.pop('MountPoint')
        with patch.object(finish, 'internal_efi', return_value=initial):
            finish.main(['--check'])
        self.run.assert_called_once_with(['/usr/sbin/diskutil', 'mount', 'readOnly', 'disk42s1'], check=True)

    def test_readonly_write_run_never_force_unmounts(self):
        self.efi['WritableVolume'] = False
        with self.assertRaisesRegex(ValueError, 'read-only'):
            finish.main([])
        self.run.assert_not_called()
        self.assertEqual(plistlib.loads(self.config.read_bytes()), self.original)

    def test_disk_identity_change_prevents_write_and_records_failure(self):
        changed = dict(self.efi, DiskUUID='changed-identity')
        with patch.object(finish, 'internal_efi', side_effect=[dict(self.efi), changed]):
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                finish.main([])
        self.assertEqual(plistlib.loads(self.config.read_bytes()), self.original)
        report = json.loads(next(self.base.glob('build/internal-efi/*/report.json')).read_text())
        self.assertEqual(report['status'], 'incomplete')
        self.assertIn('identity changed', report['error'])


if __name__ == '__main__':
    unittest.main()
