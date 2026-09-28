import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import desktop


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='desktop-test-')
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.env = patch.dict(os.environ, {'HOME': str(self.home), 'RUN_DIR': ''})
        self.env.start()
        self.addCleanup(self.env.stop)

    def download(self, name, url, destination, digest=None):
        destination.write_bytes(b'complete vendor DMG')

    def test_preparation_reuse_damage_and_explicit_refresh(self):
        with patch.object(desktop.vendor, 'download', side_effect=self.download) as download, \
                patch.object(desktop.subprocess, 'run') as command, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(desktop.prepare('google-chrome'), 'prepared')
            data = desktop.prepared('google-chrome')
            self.assertTrue(data['manual_install_required'])
            self.assertEqual(download.call_count, 1)
            self.assertEqual(command.call_args.args[0][:2], ['hdiutil', 'verify'])
            self.assertEqual(desktop.prepare('google-chrome'), 'prepared')
            self.assertEqual(download.call_count, 1)
            image = desktop.directory() / data['filename']
            image.write_bytes(b'truncated')
            self.assertIsNone(desktop.prepared('google-chrome'))
            desktop.prepare('google-chrome')
            self.assertEqual(download.call_count, 2)
            desktop.prepare('google-chrome', update=True)
            self.assertEqual(download.call_count, 3)
        self.assertFalse((self.home / 'Applications').exists())

    def test_failed_refresh_preserves_previous_complete_package(self):
        with patch.object(desktop.vendor, 'download', side_effect=self.download), \
                patch.object(desktop.subprocess, 'run'), contextlib.redirect_stderr(io.StringIO()):
            desktop.prepare('docker-desktop')
        previous = desktop.prepared('docker-desktop')
        with patch.object(desktop.vendor, 'download', side_effect=self.download), \
                patch.object(desktop.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'hdiutil')):
            with self.assertRaises(subprocess.CalledProcessError):
                desktop.prepare('docker-desktop', update=True)
        self.assertEqual(desktop.prepared('docker-desktop'), previous)
        self.assertFalse(list(desktop.directory().glob('.desktop-*')))

    def test_receipt_cannot_point_outside_download_directory(self):
        root = desktop.directory()
        root.mkdir(parents=True)
        (root / 'chatgpt.json').write_text(json.dumps(dict(schema_version=1, component='chatgpt',
                                                         filename='../personal.dmg', sha256='a' * 64)))
        self.assertIsNone(desktop.prepared('chatgpt'))
        (root / 'chatgpt.json').unlink()
        (root / 'chatgpt.json').symlink_to(self.home / 'personal')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            desktop.prepared('chatgpt')

    def test_vendor_rejection_does_not_leave_an_installer_receipt(self):
        with patch.object(desktop.vendor, 'download', side_effect=self.download), \
                patch.object(desktop.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'hdiutil')):
            with self.assertRaises(subprocess.CalledProcessError):
                desktop.prepare('google-chrome')
        self.assertIsNone(desktop.prepared('google-chrome'))
        self.assertFalse(list(desktop.directory().glob('*.dmg')))

    def test_claude_default_uses_official_latest_dmg_without_metadata_lookup(self):
        with patch.object(desktop.vendor, 'release', side_effect=AssertionError('metadata must not be required')), \
                patch.object(desktop.vendor, 'download', side_effect=self.download) as download, \
                patch.object(desktop.subprocess, 'run'), contextlib.redirect_stderr(io.StringIO()):
            desktop.prepare('claude-desktop')
            desktop.prepare('claude-desktop')
            self.assertEqual(download.call_count, 1)
            self.assertEqual(download.call_args.args[1], desktop.vendor.sources()['claude-desktop-download'])
            desktop.prepare('claude-desktop', update=True)
            self.assertEqual(download.call_count, 2)
        data = desktop.prepared('claude-desktop')
        self.assertEqual(data['version'], 'latest')
        self.assertEqual(data['filename'], 'claude-desktop-latest.dmg')
        self.assertTrue(data['manual_install_required'])
        self.assertFalse((self.home / 'Applications').exists())

    def test_claude_redirect_failure_falls_back_only_to_official_release_dmg(self):
        catalog = desktop.vendor.sources()
        url = catalog['claude-desktop-distribution'] + '2.9.0/Claude-' + 'a' * 40 + '.dmg'
        calls = []
        def download(name, source, target, digest=None):
            calls.append(source)
            if source == catalog['claude-desktop-download']:
                target.write_bytes(b'failed redirect')
                raise subprocess.CalledProcessError(22, 'curl')
            self.download(name, source, target, digest)
        with patch.object(desktop.vendor, 'release', return_value=dict(version='2.9.0', url=url)), \
                patch.object(desktop.vendor, 'download', side_effect=download), \
                patch.object(desktop.subprocess, 'run'), contextlib.redirect_stderr(io.StringIO()):
            desktop.prepare('claude-desktop')
        self.assertEqual(calls, [catalog['claude-desktop-download'], url])
        data = desktop.prepared('claude-desktop')
        self.assertEqual((data['source'], data['version']), (url, '2.9.0'))
        self.assertEqual((desktop.directory() / data['filename']).read_bytes(), b'complete vendor DMG')

    def test_claude_desktop_dmg_tracks_official_release_feed(self):
        catalog = desktop.vendor.sources()
        data = dict(currentRelease='2.9.0', releases=[dict(version='2.9.0', updateTo=dict(
            url=catalog['claude-desktop-distribution'] + '2.9.0/Claude-' + 'a' * 40 + '.zip'))])
        release = desktop.vendor.release('claude-desktop', catalog, lambda _: json.dumps(data))
        self.assertEqual(release['version'], '2.9.0')
        self.assertTrue(release['url'].endswith('.dmg'))
        data['releases'][0]['updateTo']['url'] = 'https://untrusted.invalid/Claude.zip'
        with self.assertRaises(ValueError):
            desktop.vendor.release('claude-desktop', catalog, lambda _: json.dumps(data))


if __name__ == '__main__':
    unittest.main()
