"""Download progress and interrupted/corrupt transfer guards; no network."""
import contextlib
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build_kit as builder


class DownloadTests(unittest.TestCase):
    def exercise(self, payload=b'package fixture', length=None, expected=None, interrupt=False):
        class Response(io.BytesIO):
            headers = {'Content-Length': str(length)} if length is not None else {}
            def read(self, count=-1):
                if interrupt:
                    raise OSError('network connection interrupted')
                return super().read(count)
        self.capture = io.StringIO()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = Path(self.directory.name)
        digest = expected or hashlib.sha256(payload).hexdigest()
        with patch.dict(builder.DOWNLOADS, {'fixture.pkg': ('https://example.invalid/fixture.pkg', digest)}), \
             patch.object(builder.urllib.request, 'urlopen', return_value=Response(payload)), \
             contextlib.redirect_stdout(self.capture):
            return builder.download('fixture.pkg', self.cache)

    def test_known_size_reports_completion_and_verification(self):
        path = self.exercise(length=len(b'package fixture'))
        self.assertEqual(path.read_bytes(), b'package fixture')
        self.assertIn('(0%)', self.capture.getvalue())
        self.assertIn('(100%)', self.capture.getvalue())
        self.assertIn('[' + '#' * 24 + ']', self.capture.getvalue())
        self.assertIn('MiB/s | ETA', self.capture.getvalue())
        self.assertIn('Verified official download:', self.capture.getvalue())
        self.assertEqual(list(self.cache.glob('*.part')), [])

    def test_partial_bar_displays_percentage_rate_and_eta(self):
        message = builder.download_status('KDK.dmg', 25 * 1024 ** 2, 100 * 1024 ** 2, 5)
        self.assertIn('[######------------------]', message)
        self.assertIn('(25%)', message)
        self.assertIn('5.0 MiB/s | ETA 0:15', message)

    def test_large_hash_verification_reports_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'large.pkg'
            with path.open('wb') as out: out.truncate(32 * 1024 ** 2)
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture): result = builder.digest(path)
            self.assertEqual(result, hashlib.sha256(bytes(32 * 1024 ** 2)).hexdigest())
            self.assertIn('Checking large.pkg', capture.getvalue())
            self.assertIn('(100%)', capture.getvalue())

    def test_large_copy_reports_progress_and_preserves_bytes_and_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory) / 'package.pkg', Path(directory) / 'copied.pkg'
            with source.open('wb') as out: out.truncate(32 * 1024 ** 2)
            source.chmod(0o640)
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                builder.copy_with_progress(source, destination)
                self.assertEqual(builder.digest(source), builder.digest(destination))
            self.assertEqual(destination.stat().st_mode & 0o777, 0o640)
            self.assertIn('Copying package.pkg', capture.getvalue())
            self.assertIn('(100%)', capture.getvalue())

    def test_unknown_size_reports_bytes_and_verifies(self):
        path = self.exercise()
        self.assertTrue(path.is_file())
        self.assertIn('MiB received', self.capture.getvalue())
        self.assertIn('Verified official download:', self.capture.getvalue())

    def test_truncated_response_never_becomes_cached_package(self):
        with self.assertRaisesRegex(ValueError, 'Incomplete download'):
            self.exercise(length=100)
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_corrupt_response_never_becomes_cached_package(self):
        with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'):
            self.exercise(expected='0' * 64)
        self.assertEqual(list(self.cache.iterdir()), [])
        self.assertNotIn('Verified official download:', self.capture.getvalue())

    def test_interruption_cleans_partial_file(self):
        with self.assertRaisesRegex(OSError, 'interrupted'):
            self.exercise(interrupt=True)
        self.assertEqual(list(self.cache.iterdir()), [])


if __name__ == '__main__': unittest.main()
