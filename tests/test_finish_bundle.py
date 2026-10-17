"""USB finishing bundle and Apple tools bootstrap. No real installs or EFI writes."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import finish_bundle as bundle


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.usb = self.root / 'usb'
        self.usb.mkdir()

    def install(self, name='backups'):
        return bundle.install(self.usb, self.root / name)

    def test_complete_bundle_is_small_and_imports_without_git_or_site_packages(self):
        result = self.install()
        self.assertLess(result['bytes'], 200000)
        folder = self.usb / bundle.FOLDER
        bundle.verify(self.usb)
        manifest = json.loads((folder / 'manifest.json').read_text())
        for name, digest in manifest['sha256'].items():
            self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), digest)
        # Wrong-host guard may run, but cannot pass on the preparation iMac.
        # Instead just import all modules with the folder as the only project source.
        result = subprocess.run([sys.executable, '-E', '-s', '-B', '-c',
                                 'import finish_install; print("imports OK")'], cwd=folder,
                                text=True, capture_output=True, check=True)
        self.assertIn('imports OK', result.stdout)

    def test_repeat_reuses_files_and_retains_logs(self):
        self.install()
        log = self.usb / bundle.FOLDER / 'build/bootstrap/existing.log'
        log.parent.mkdir(parents=True)
        log.write_text('retain')
        times = {p.name: p.stat().st_mtime_ns for p in (self.usb / bundle.FOLDER).iterdir() if p.is_file()}
        self.assertEqual(self.install('second')['changed_files'], [])
        self.assertEqual(log.read_text(), 'retain')
        self.assertEqual(times, {p.name: p.stat().st_mtime_ns for p in (self.usb / bundle.FOLDER).iterdir() if p.is_file()})

    def test_changed_file_is_backed_up_and_permission_repaired(self):
        self.install()
        script = self.usb / bundle.FOLDER / 'finish_install.py'
        script.write_bytes(b'old version')
        launcher = script.parent / bundle.LAUNCHER
        launcher.chmod(0o600)
        with self.assertRaises(ValueError): bundle.verify(self.usb)
        self.install('repair-backups')
        self.assertEqual((self.root / 'repair-backups/finish_install.py').read_bytes(), b'old version')
        self.assertEqual(launcher.stat().st_mode & 0o777, 0o755)
        bundle.verify(self.usb)

    def test_symlink_destination_prevents_all_writes(self):
        folder = self.usb / bundle.FOLDER
        folder.mkdir()
        outside = self.root / 'outside'
        outside.write_text('preserve')
        (folder / 'finish_install.py').symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.install()
        self.assertEqual(list(folder.iterdir()), [folder / 'finish_install.py'])
        self.assertEqual(outside.read_text(), 'preserve')

    def test_backup_on_usb_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'outside the USB'):
            bundle.install(self.usb, self.usb / 'backup')
        self.assertFalse((self.usb / bundle.FOLDER).exists())


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.script = bundle.BASE / 'kit/finish-install.command'

    def shell(self, body, stdin='', script=None):
        return subprocess.run(['/bin/bash', '-c', 'source "$1"\n' + body, 'fixture', str(script or self.script)],
                              input=stdin, text=True, capture_output=True, timeout=10)

    def test_exact_label_and_numeric_version_selection_exclude_os_and_beta(self):
        listing = '''* Label: macOS Tahoe 26.7.2-25G999
* Label: Command Line Tools for Xcode-26.9
* Label: Command Line Tools for Xcode 26.10-26.10
* Label: Command Line Tools for Xcode 27.0 beta-27.0
* Label: Safari 27.0
'''
        result = self.shell('select_clt_label', listing)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), 'Command Line Tools for Xcode 26.10-26.10')

    def test_missing_clt_label_returns_empty_not_a_macos_update(self):
        result = self.shell('select_clt_label', '* Label: macOS Tahoe 26.7.2-25G999\n')
        self.assertEqual(result.stdout, '')

    def installer_fixture(self, listing, fail_list=False, fail_install=False):
        marker = self.root / 'marker'
        tool_dir = self.root / 'CommandLineTools'
        commands = self.root / 'commands'
        updater = self.root / 'softwareupdate'
        updater.write_text('#!/bin/bash\n'
                           'printf "%s\\n" "$*" >> "' + str(commands) + '"\n'
                           'if [[ "$1" == --list ]]; then\n'
                           'cat <<\'LIST\'\n' + listing + '\nLIST\n'
                           'exit ' + ('1' if fail_list else '0') + '\nfi\n'
                           + ('exit 1\n' if fail_install else 'mkdir -p "' + str(tool_dir) + '"\n'))
        updater.chmod(0o755)
        selector = self.root / 'xcode-select'
        selector.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "' + str(commands) + '"\n')
        selector.chmod(0o755)
        source = self.script.read_text().replace('/usr/sbin/softwareupdate', str(updater))
        source = source.replace('/usr/bin/xcode-select', str(selector))
        source = source.replace('/Library/Developer/CommandLineTools', str(tool_dir))
        source = source.replace('/tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress', str(marker))
        script = self.root / 'launcher.command'
        script.write_text(source)
        return script, marker, commands

    def test_install_uses_exact_discovered_label_and_cleans_own_marker(self):
        script, marker, commands = self.installer_fixture('* Label: Command Line Tools for Xcode 26.5-26.5')
        result = self.shell('install_finish_tools', script=script)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = commands.read_text().splitlines()
        self.assertEqual(lines[1], '--install Command Line Tools for Xcode 26.5-26.5 --verbose')
        self.assertTrue(lines[2].startswith('--switch '))
        self.assertFalse(marker.exists())
        self.assertNotIn('--all', commands.read_text())

    def test_no_clt_package_stops_before_any_install(self):
        script, marker, commands = self.installer_fixture('* Label: macOS Tahoe 26.7.2-25G999')
        result = self.shell('install_finish_tools', script=script)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(commands.read_text().splitlines(), ['--list'])
        self.assertFalse(marker.exists())

    def test_download_failure_stops_and_preserves_existing_marker(self):
        script, marker, commands = self.installer_fixture('* Label: Command Line Tools for Xcode-26.5', fail_install=True)
        marker.write_text('preexisting marker')
        result = self.shell('install_finish_tools', script=script)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('--switch', commands.read_text())
        self.assertEqual(marker.read_text(), 'preexisting marker')

    def test_update_discovery_failure_does_not_install(self):
        script, marker, commands = self.installer_fixture('network error', fail_list=True)
        result = self.shell('install_finish_tools', script=script)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(commands.read_text().splitlines(), ['--list'])
        self.assertFalse(marker.exists())

    def test_launch_verification_rejects_corrupted_bundle(self):
        usb = self.root / 'usb'
        usb.mkdir()
        bundle.install(usb, self.root / 'backups')
        folder = usb / bundle.FOLDER
        (folder / 'fix_efi.py').write_text('corrupt')
        # Read the launcher functions; invoke only the pre-import verifier.
        result = subprocess.run(
            ['/bin/bash', '-c', 'source "$1"; finish_python="$2"; finish_bundle_dir="$3"; verify_finish_bundle',
             'fixture', str(self.script), sys.executable, str(folder)], text=True, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('did not verify', result.stderr)

    def test_existing_python_skips_tools_install_and_logs_launch(self):
        folder = self.root / 'bundle'
        folder.mkdir()
        python = self.root / 'python-fixture'
        invoked = self.root / 'python-invocations'
        python.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "' + str(invoked) + '"\n')
        python.chmod(0o755)
        sysctl = self.root / 'sysctl'
        sysctl.write_text('#!/bin/bash\necho MacBookPro11,3\n')
        sysctl.chmod(0o755)
        swvers = self.root / 'sw_vers'
        swvers.write_text('#!/bin/bash\necho 25G241\n')
        swvers.chmod(0o755)
        script = self.root / 'fixture-launcher'
        # Keep all writes and commands inside this disposable fixture. Never sudo.
        source = self.script.read_text().replace('/usr/sbin/sysctl', str(sysctl)).replace('/usr/bin/sw_vers', str(swvers))
        source = source.replace('if [[ $EUID != 0 ]]; then', 'if false; then')
        script.write_text(source)
        result = subprocess.run(['/bin/bash', '-c',
            'source "$1"; fixture_python="$2"; find_finish_python() { printf "%s\\n" "$fixture_python"; }; '
            'install_finish_tools() { echo unexpected-install; return 70; }; '
            'finish_main --check',
            'fixture', str(script), str(python)], cwd=folder, text=True, capture_output=True, timeout=10)
        self.assertNotIn('unexpected-install', result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('-E -s -B', invoked.read_text())
        self.assertEqual(len(list((folder / 'build/bootstrap').glob('*.log'))), 1)


if __name__ == '__main__':
    unittest.main()
