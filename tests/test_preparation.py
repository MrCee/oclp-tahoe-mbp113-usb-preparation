"""Creator-side guards and native Recovery utility; no real disk writes."""
import copy
import hashlib
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build_kit as builder
import fix_efi


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        version = self.root / 'System/Library/CoreServices/SystemVersion.plist'
        version.parent.mkdir(parents=True)
        version.write_bytes(plistlib.dumps({'ProductVersion': builder.VERSION, 'ProductBuildVersion': builder.BUILD}))
        self.info = {'Internal': False, 'FilesystemType': 'hfs', 'MountPoint': str(self.root),
                     'DiskUUID': '11111111-2222-4333-8444-555555555555'}

    def test_usb_accepts_partition_identity_without_filesystem_uuid(self):
        with patch.object(builder, 'disk_info', return_value=self.info):
            self.assertEqual(builder.validate_usb(self.root), (self.root, self.info['DiskUUID']))

    def test_usb_rejects_internal_wrong_filesystem_and_subdirectory(self):
        for changes in ({'Internal': True}, {'FilesystemType': 'apfs'}, {'MountPoint': str(self.root.parent)}):
            with self.subTest(changes=changes), patch.object(builder, 'disk_info', return_value=dict(self.info, **changes)):
                with self.assertRaises(ValueError): builder.validate_usb(self.root)

    def test_wrong_installer_build_rejected(self):
        (self.root / 'System/Library/CoreServices/SystemVersion.plist').write_bytes(plistlib.dumps({'ProductVersion': builder.VERSION, 'ProductBuildVersion': 'WRONG'}))
        with patch.object(builder, 'disk_info', return_value=self.info):
            with self.assertRaises(ValueError): builder.validate_usb(self.root)

    def test_modified_cached_download_rejected_without_network(self):
        (self.root / 'AutoPkg-Assets.pkg').write_bytes(b'changed package')
        with patch.object(builder.urllib.request, 'urlopen') as network:
            with self.assertRaises(ValueError): builder.download('AutoPkg-Assets.pkg', self.root)
            network.assert_not_called()

    def test_deploy_rejects_symlink_before_writes(self):
        output = self.root / 'output'; output.mkdir()
        usb = self.root / 'usb'; usb.mkdir()
        (usb / 'Library').symlink_to(output, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlinked'): builder.deploy(output, usb)
        self.assertEqual(list(output.iterdir()), [])


class EfiTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            '#Revision': {'Original-Model': builder.MODEL},
            'PlatformInfo': {'DataHub': {'SystemProductName': '', 'BoardProduct': '', 'Other': 'preserve'}, 'UpdateDataHub': False},
            'NVRAM': {'Add': {fix_efi.APPLE_GUID: {'boot-args': '-v -x keepsyms=1'}, fix_efi.OCLP_GUID: {'OCLP-Model': builder.MODEL}}},
            'Misc': {'Security': {'SecureBootModel': 'Disabled'}},
        }

    def test_only_three_reported_fields_change_by_default(self):
        original = copy.deepcopy(self.config)
        expected = copy.deepcopy(original)
        expected['PlatformInfo']['DataHub'].update(SystemProductName=builder.MODEL, BoardProduct=fix_efi.BOARD)
        expected['PlatformInfo']['UpdateDataHub'] = True
        self.assertEqual(fix_efi.update_config(self.config), expected)
        self.assertEqual(self.config, original)

    def test_normal_boot_removes_only_safe_mode_token(self):
        changed = fix_efi.update_config(self.config, True)
        self.assertEqual(changed['NVRAM']['Add'][fix_efi.APPLE_GUID]['boot-args'], '-v keepsyms=1')
        self.assertEqual(fix_efi.update_config(changed, True), changed)

    def test_other_or_conflicting_model_rejected(self):
        for branch in ('revision', 'nvram'):
            config = copy.deepcopy(self.config)
            if branch == 'revision': config['#Revision']['Original-Model'] = 'iMac15,1'
            else: config['NVRAM']['Add'][fix_efi.OCLP_GUID]['OCLP-Model'] = 'MacBookPro11,2'
            with self.subTest(branch=branch), self.assertRaises(ValueError): fix_efi.update_config(config)


class NativeHelperTests(unittest.TestCase):
    helper = builder.BASE / 'kit/recovery-tool'

    def run_helper(self, *args, **kwargs):
        return subprocess.run([str(self.helper), *map(str, args)], text=True, capture_output=True, **kwargs)

    def test_xml_binary_nested_arrays_booleans_unicode_and_stdin(self):
        data = {'items': [{'value': 'Tahoe café', 'enabled': True, 'count': 7}]}
        for fmt in (plistlib.FMT_XML, plistlib.FMT_BINARY):
            with tempfile.TemporaryDirectory() as td:
                p = Path(td) / 'input.plist'; p.write_bytes(plistlib.dumps(data, fmt=fmt))
                for key, expected in [('items.0.value', 'Tahoe café'), ('items.0.enabled', 'true'), ('items.0.count', '7')]:
                    result = self.run_helper('value', p, key)
                    self.assertEqual((result.returncode, result.stdout.strip()), (0, expected))
                self.assertNotEqual(self.run_helper('value', p, 'items.9.value').returncode, 0)
        result = self.run_helper('value', '-', 'items.0.count', input=plistlib.dumps(data).decode())
        self.assertEqual((result.returncode, result.stdout.strip()), (0, '7'))

    def test_hash_manifest_corruption_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); data = root / 'payload'; data.write_bytes(b'fixture')
            digest = hashlib.sha256(b'fixture').hexdigest()
            manifest = root / 'SHA256SUMS'; manifest.write_text(digest + '  payload\n')
            self.assertEqual(self.run_helper('sha-check', manifest, cwd=td).returncode, 0)
            data.write_bytes(b'corrupt')
            self.assertNotEqual(self.run_helper('sha-check', manifest, cwd=td).returncode, 0)
            for path in ('../outside', '/absolute', 'nested/../outside'):
                manifest.write_text(digest + '  ' + path + '\n')
                self.assertNotEqual(self.run_helper('sha-check', manifest, cwd=td).returncode, 0)


if __name__ == '__main__':
    unittest.main()
