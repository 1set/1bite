import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_doubao', ROOT / 'scripts/prepare-doubao.py')
doubao = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doubao)


class DoubaoTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='doubao test ')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / 'packages'
        self.build = '1000103'
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            root = f'DoubaoImeInstaller_v{self.build}.app'
            archive.writestr(root + '/Contents/Info.plist', 'fixture only')
            archive.writestr(root + '/Contents/Resources/DoubaoIme.zip', b'nested fixture')
            link = zipfile.ZipInfo(root + '/Contents/Frameworks/Fixture.framework/Versions/Current')
            link.external_attr = (stat.S_IFLNK | 0o755) << 16
            archive.writestr(link, 'A')
            archive.writestr('__MACOSX/' + root + '/Contents/._Info.plist', b'resource fork')
        self.payload = stream.getvalue()
        self.item = {
            'token': 'doubaoime',
            'version': f'1.0.1,{self.build}',
            'url': ('https://lf-wave.doubaocdn.com/obj/doubao-ime/app/macos/'
                    f'DoubaoImeInstaller_v{self.build}_release.zip'),
            'sha256': hashlib.sha256(self.payload).hexdigest(),
        }

    def test_source_contract_rejects_changed_origin_version_and_checksum(self):
        response = json.dumps(self.item)
        with patch.object(doubao.subprocess, 'check_output', return_value=response) as query:
            self.assertEqual(doubao.metadata(), (self.item, '1.0.1', self.build))
            command = query.call_args.args[0]
            self.assertEqual(command[0], 'curl')
            self.assertIn('https://formulae.brew.sh/api/cask/doubaoime.json', command)
            self.assertIn('--proto', command)
        invalid = [
            ('token', 'another-app'),
            ('sha256', 'no_check'),
            ('version', '1.0.1'),
            ('version', '1.0.1,999'),
            ('url', 'http://lf-wave.doubaocdn.com/obj/doubao-ime/app/macos/file.zip'),
            ('url', 'https://lf-wave.doubaocdn.com.attacker.invalid/obj/doubao-ime/app/macos/file.zip'),
            ('url', 'https://lf-wave.doubaocdn.com/obj/doubao-ime/app/macos/../file.zip'),
        ]
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                item = dict(self.item, **{field: value})
                with patch.object(doubao.subprocess, 'check_output',
                                  return_value=json.dumps(item)):
                    with self.assertRaises(ValueError):
                        doubao.metadata()

    def test_prepare_reuses_verified_bytes_and_repairs_damage(self):
        def download(url, target):
            self.assertEqual(url, self.item['url'])
            target.write_bytes(self.payload)

        metadata = (self.item, '1.0.1', self.build)
        with patch.object(doubao, 'metadata', return_value=metadata), \
                patch.object(doubao, 'download', side_effect=download) as fetch:
            target, report = doubao.prepare(self.directory)
            self.assertEqual(set(report), {'schema_version', 'status', 'action', 'manual_install_required',
                                          'version', 'build', 'source', 'sha256', 'filename'})
            self.assertEqual(report['action'], 'downloaded')
            self.assertTrue(report['manual_install_required'])
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            before = target.stat().st_mtime_ns
            _, repeat = doubao.prepare(self.directory)
            self.assertEqual(repeat['action'], 'reused')
            self.assertEqual(target.stat().st_mtime_ns, before)
            self.assertEqual(fetch.call_count, 1)
            target.write_bytes(b'interrupted or damaged')
            _, repaired = doubao.prepare(self.directory)
            self.assertEqual(repaired['action'], 'downloaded')
            self.assertEqual(target.read_bytes(), self.payload)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(list(self.directory.iterdir()), [target])

    def test_download_failure_preserves_existing_package(self):
        metadata = (self.item, '1.0.1', self.build)
        with patch.object(doubao, 'metadata', return_value=metadata), \
                patch.object(doubao, 'download', side_effect=lambda url, path: path.write_bytes(self.payload)):
            target, _ = doubao.prepare(self.directory)
        target.write_bytes(b'previous package')
        with patch.object(doubao, 'metadata', return_value=metadata), \
                patch.object(doubao, 'download', side_effect=subprocess.CalledProcessError(22, 'curl')):
            with self.assertRaises(subprocess.CalledProcessError):
                doubao.prepare(self.directory)
        self.assertEqual(target.read_bytes(), b'previous package')
        self.assertEqual(list(self.directory.iterdir()), [target])

    def test_bad_checksum_layout_and_unsafe_members_never_publish(self):
        cases = []
        cases.append((dict(self.item), b'not a zip'))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('Another.app/Contents/Resources/DoubaoIme.zip', b'wrong')
        cases.append((dict(self.item, sha256=hashlib.sha256(stream.getvalue()).hexdigest()),
                      stream.getvalue()))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            root = f'DoubaoImeInstaller_v{self.build}.app'
            archive.writestr(root + '/Contents/Resources/DoubaoIme.zip', b'nested')
            archive.writestr(root + '/../escape', b'unsafe')
        cases.append((dict(self.item, sha256=hashlib.sha256(stream.getvalue()).hexdigest()),
                      stream.getvalue()))
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            root = f'DoubaoImeInstaller_v{self.build}.app'
            archive.writestr(root + '/Contents/Resources/DoubaoIme.zip', b'nested')
            link = zipfile.ZipInfo(root + '/Contents/Frameworks/escape')
            link.external_attr = (stat.S_IFLNK | 0o755) << 16
            archive.writestr(link, '../../../../outside')
        cases.append((dict(self.item, sha256=hashlib.sha256(stream.getvalue()).hexdigest()),
                      stream.getvalue()))
        for item, payload in cases:
            metadata = (item, '1.0.1', self.build)
            with self.subTest(payload=payload[:20]), patch.object(doubao, 'metadata', return_value=metadata), \
                    patch.object(doubao, 'download', side_effect=lambda url, path, data=payload: path.write_bytes(data)):
                with self.assertRaises((ValueError, zipfile.BadZipFile)):
                    doubao.prepare(self.directory)
                self.assertEqual(list(self.directory.iterdir()), [])

    def test_symlinks_are_never_followed_or_replaced(self):
        other = self.directory.parent / 'personal'
        other.mkdir()
        self.directory.symlink_to(other, target_is_directory=True)
        metadata = (self.item, '1.0.1', self.build)
        with patch.object(doubao, 'metadata', return_value=metadata), patch.object(doubao, 'download') as fetch:
            with self.assertRaises(ValueError):
                doubao.prepare(self.directory)
            self.directory.unlink()
            self.directory.mkdir()
            target = self.directory / f"DoubaoInput-1.0.1-{self.build}-{self.item['sha256'][:12]}.zip"
            target.symlink_to(other / 'missing.zip')
            with self.assertRaises(ValueError):
                doubao.prepare(self.directory)
            self.assertTrue(target.is_symlink())
            target.unlink()
            target.mkdir()
            with self.assertRaises(ValueError):
                doubao.prepare(self.directory)
            self.assertTrue(target.is_dir())
            fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
