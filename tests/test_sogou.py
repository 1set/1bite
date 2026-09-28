import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_sogou', ROOT / 'scripts/prepare-sogou.py')
sogou = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sogou)


class SogouTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='sogou test ')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / 'packages'
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('SogouInstaller.app/Contents/Info.plist', 'fixture only')
        self.payload = stream.getvalue()
        self.item = {'token': 'sogouinput', 'version': '624d',
                     'url': 'https://ime.gtimg.com/pc/sogou_mac_624d.zip',
                     'sha256': hashlib.sha256(self.payload).hexdigest()}

    def test_source_contract_rejects_changed_origin_and_missing_checksum(self):
        with patch.object(sogou.subprocess, 'check_output', return_value=json.dumps({'casks': [self.item]})) as query:
            self.assertEqual(sogou.metadata(), self.item)
            self.assertEqual(query.call_args.args[0], ['brew', 'info', '--json=v2', '--cask', 'homebrew/cask/sogouinput'])
        for field, bad in [('token', 'another-app'), ('sha256', 'no_check'), ('version', '../outside'),
                           ('url', 'http://ime.gtimg.com/pc/sogou.zip'),
                           ('url', 'https://ime.gtimg.com.attacker.invalid/pc/sogou.zip'),
                           ('url', 'https://ime.gtimg.com/pc/../other.zip')]:
            with self.subTest(field=field, value=bad):
                item = dict(self.item, **{field: bad})
                with patch.object(sogou.subprocess, 'check_output', return_value=json.dumps({'casks': [item]})):
                    with self.assertRaises(ValueError):
                        sogou.metadata()

    def test_prepare_reuse_and_repair_are_based_on_package_bytes(self):
        def download(url, target):
            self.assertEqual(url, self.item['url'])
            target.write_bytes(self.payload)
        with patch.object(sogou, 'metadata', return_value=self.item), \
                patch.object(sogou, 'download', side_effect=download) as fetch:
            target, report = sogou.prepare(self.directory)
            self.assertEqual(set(report), {'schema_version', 'status', 'action', 'manual_install_required',
                                          'version', 'source', 'sha256', 'filename'})
            self.assertEqual(report['status'], 'prepared')
            self.assertTrue(report['manual_install_required'])
            self.assertEqual(report['action'], 'downloaded')
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            before = target.stat().st_mtime_ns
            _, repeat = sogou.prepare(self.directory)
            self.assertEqual(repeat['action'], 'reused')
            self.assertEqual(target.stat().st_mtime_ns, before)
            self.assertEqual(fetch.call_count, 1)
            target.write_bytes(b'interrupted or damaged')
            _, repaired = sogou.prepare(self.directory)
            self.assertEqual(repaired['action'], 'downloaded')
            self.assertEqual(target.read_bytes(), self.payload)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(list(self.directory.iterdir()), [target])

    def test_download_failure_preserves_existing_package_and_allows_retry(self):
        with patch.object(sogou, 'metadata', return_value=self.item), \
                patch.object(sogou, 'download', side_effect=lambda url, path: path.write_bytes(self.payload)):
            target, _ = sogou.prepare(self.directory)
        target.write_bytes(b'previous package')
        with patch.object(sogou, 'metadata', return_value=self.item), \
                patch.object(sogou, 'download', side_effect=subprocess.CalledProcessError(22, 'curl')):
            with self.assertRaises(subprocess.CalledProcessError):
                sogou.prepare(self.directory)
        self.assertEqual(target.read_bytes(), b'previous package')
        self.assertEqual(list(self.directory.iterdir()), [target])

    def test_bad_checksum_and_invalid_zip_never_publish(self):
        for valid_hash in (False, True):
            item = dict(self.item)
            if valid_hash:
                item['sha256'] = hashlib.sha256(b'not a zip').hexdigest()
            with self.subTest(valid_hash=valid_hash), patch.object(sogou, 'metadata', return_value=item), \
                    patch.object(sogou, 'download', side_effect=lambda url, path: path.write_bytes(b'not a zip')):
                with self.assertRaises((ValueError, zipfile.BadZipFile)):
                    sogou.prepare(self.directory)
                self.assertEqual(list(self.directory.iterdir()), [])

    def test_symlinks_are_not_followed_or_replaced(self):
        other = self.directory.parent / 'personal'
        other.mkdir()
        self.directory.symlink_to(other, target_is_directory=True)
        with patch.object(sogou, 'metadata', return_value=self.item), patch.object(sogou, 'download') as fetch:
            with self.assertRaises(ValueError):
                sogou.prepare(self.directory)
            self.directory.unlink()
            self.directory.mkdir()
            target = self.directory / f"SogouInput-624d-{self.item['sha256'][:12]}.zip"
            target.symlink_to(other / 'missing.zip')
            with self.assertRaises(ValueError):
                sogou.prepare(self.directory)
            self.assertTrue(target.is_symlink())
            fetch.assert_not_called()
