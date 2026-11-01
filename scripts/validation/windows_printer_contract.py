"""Printer package integrity, architecture boundary and missing-file regressions."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import hashlib

from scripts.build import windows_printer as p


class PrinterTests(unittest.TestCase):
    def fixture(self, cache):
        hashes = {}
        for archive in p.ARCHIVES:
            with zipfile.ZipFile(cache / archive, 'w') as z:
                if archive.startswith('rustdesk_'):
                    for name in p.DRIVER_FILES:
                        z.writestr('rustdesk_printer_driver_v4-1.4/' + name, b'driver fixture')
                else:
                    z.writestr('printer_driver_adapter.dll', b'adapter fixture')
            hashes[archive] = hashlib.sha256((cache / archive).read_bytes()).hexdigest()
        return hashes

    def test_complete_payload_and_each_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); cache = root / 'cache'; cache.mkdir()
            with patch.dict(p.ARCHIVES, self.fixture(cache), clear=True):
                result = p.stage(root / 'release', 'x86_64', cache)
            self.assertEqual(result['status'], 'bundled')
            p.validate(root / 'release')
            files = list((root / 'release').rglob('*'))
            for file in files:
                if not file.is_file(): continue
                data = file.read_bytes(); file.unlink()
                with self.assertRaises(ValueError): p.validate(root / 'release')
                file.write_bytes(data)

    def test_corrupt_archive_fails_before_staging(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); hashes = self.fixture(root)
            with (root / next(iter(hashes))).open('ab') as output: output.write(b'tampered')
            with patch.dict(p.ARCHIVES, hashes, clear=True):
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                    p.stage(root / 'release', 'x86_64', root)
            self.assertFalse((root / 'release').exists())

    def test_missing_member_fails_before_staging(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); hashes = self.fixture(root)
            archive = root / 'printer_driver_adapter.zip'
            with zipfile.ZipFile(archive, 'w') as z: z.writestr('../wrong.dll', b'wrong')
            hashes[archive.name] = hashlib.sha256(archive.read_bytes()).hexdigest()
            with patch.dict(p.ARCHIVES, hashes, clear=True):
                with self.assertRaisesRegex(ValueError, 'archive member'):
                    p.stage(root / 'release', 'x86_64', root)
            self.assertFalse((root / 'release').exists())

    def test_arm64_does_not_ship_x64_driver(self):
        with tempfile.TemporaryDirectory() as td, patch('scripts.build.windows_printer.urlopen') as download:
            self.assertEqual(p.stage(Path(td), 'aarch64')['status'], 'unsupported')
            download.assert_not_called()
            self.assertEqual(list(Path(td).iterdir()), [])


if __name__ == '__main__': unittest.main()
