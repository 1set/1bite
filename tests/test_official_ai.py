import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('official_ai', ROOT / 'scripts/official_ai.py')
ai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai)


class OfficialAITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='official-ai-test-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.env = patch.dict(os.environ, {'HOME': str(self.home), 'XDG_STATE_HOME': str(self.home / 'state')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.destination = self.home / 'Applications/ChatGPT.app'
        self.destination.parent.mkdir()
        applications = patch.object(ai, 'APPLICATIONS', self.home / 'SystemApplications')
        applications.start()
        self.addCleanup(applications.stop)

    def bundle(self, path, version='1.0.0'):
        (path / 'Contents/MacOS').mkdir(parents=True)
        (path / 'Contents/Info.plist').write_bytes(plistlib.dumps(dict(
            CFBundleIdentifier='com.openai.codex', CFBundleShortVersionString=version,
            CFBundleVersion='10', CFBundleExecutable='ChatGPT')))
        (path / 'Contents/MacOS/ChatGPT').write_text('test binary')
        (path / 'Contents/MacOS/ChatGPT').chmod(0o755)
        return path

    def test_releases_use_vendor_stable_architecture_and_current_version(self):
        catalog = ai.sources()
        def feed(version, build, arch='arm64'):
            return f'<item><s:hardwareRequirements>{arch}</s:hardwareRequirements><s:shortVersionString>{version}</s:shortVersionString><s:version>{build}</s:version><enclosure url="{catalog["chatgpt-distribution"]}ChatGPT.zip" /></item>'
        xml = '<rss xmlns:s="http://www.andymatuschak.org/xml-namespaces/sparkle"><channel>' + feed('1.9.0', 1) + feed('1.10.0', 2) + feed('99.0.0', 3, 'x64') + '</channel></rss>'
        result = ai.release('chatgpt', catalog, lambda _: xml)
        self.assertEqual((result['version'], result['build'], result['url']), ('1.10.0', '2', catalog['chatgpt-download']))
        urls = [catalog['kiro-distribution'] + f'releases/stable/darwin-arm64/signed/{v}/kiro-ide-{v}-stable-darwin-arm64.dmg' for v in ('1.9.0', '1.10.0')]
        self.assertEqual(ai.release('kiro', catalog, lambda _: ' '.join(urls))['version'], '1.10.0')
        for text in ('https://example.invalid/kiro.dmg', urls[0].replace('stable', 'preview'), urls[0].replace('arm64', 'x64')):
            with self.assertRaises(ValueError):
                ai.release('kiro', catalog, lambda _: text)
        self.assertEqual(ai.release('codex', catalog, lambda _: '{"tag_name":"rust-v0.200.0"}')['version'], '0.200.0')
        self.assertEqual(ai.release('claude', catalog, lambda _: '2.5.0\n')['version'], '2.5.0')

    def test_kiro_manifest_requires_stable_native_package_and_sha256(self):
        package = dict(os='macos', architecture='universal', fileType='dmg', channel='stable',
                       download='2.24.0/Kiro CLI.dmg', sha256='a' * 64)
        data = dict(version='2.24.0', packages=[package])
        result = ai.release('kiro-cli', fetch=lambda _: json.dumps(data))
        self.assertTrue(result['url'].endswith('/2.24.0/Kiro%20CLI.dmg'))
        for field, value in [('sha256', 'missing'), ('download', '../evil.dmg'), ('channel', 'preview'), ('architecture', 'x64')]:
            invalid = dict(data, packages=[dict(package, **{field: value})])
            with self.assertRaises(ValueError):
                ai.release('kiro-cli', fetch=lambda _: json.dumps(invalid))

    def test_receipt_is_not_proof_of_health_and_is_private(self):
        with patch.object(ai, 'release', return_value=dict(version='2.0.0', url='https://vendor.invalid/app.dmg')), \
                patch.object(ai, 'download', side_effect=RuntimeError('network interrupted')):
            ai.record('chatgpt', self.destination, '1.0.0')
            path = ai.receipt_path('chatgpt')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaisesRegex(RuntimeError, 'network interrupted'):
                ai.install_app('chatgpt', self.destination)
            self.assertFalse(self.destination.exists())

    def test_healthy_default_and_unmanaged_update_never_download(self):
        self.bundle(self.destination)
        with patch.object(ai, 'release', side_effect=AssertionError('unexpected network')):
            self.assertEqual(ai.install_app('chatgpt', self.destination, True), 'preserved')
            self.assertEqual(ai.install_app('chatgpt', self.destination, True, True), 'preserved')
            ai.record('chatgpt', self.destination, '1.0.0')
            self.assertEqual(ai.install_app('chatgpt', self.destination, True), 'skipped')

    def test_unmanaged_damage_and_symlink_are_preserved(self):
        self.bundle(self.destination)
        before = (self.destination / 'Contents/Info.plist').read_bytes()
        with self.assertRaisesRegex(ValueError, 'unmanaged'):
            ai.install_app('chatgpt', self.destination)
        self.assertEqual((self.destination / 'Contents/Info.plist').read_bytes(), before)
        other = self.destination.parent / 'other.app'
        other.symlink_to(self.destination)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            ai.install_app('chatgpt', other)

    def test_update_does_not_downgrade_or_download_current_build(self):
        self.bundle(self.destination, '2.0.0')
        ai.record('chatgpt', self.destination, '1.0.0')
        for version, build in [('1.0.0', '999'), ('2.0.0', '10')]:
            with patch.object(ai, 'release', return_value=dict(version=version, build=build)), \
                    patch.object(ai, 'download', side_effect=AssertionError('download')):
                self.assertEqual(ai.install_app('chatgpt', self.destination, True, True), 'update-checked')

    def test_failed_copy_or_final_verification_preserves_previous_app(self):
        self.bundle(self.destination)
        staged = self.bundle(self.home / 'new.app', '2.0.0')
        def copy(args, **kwargs):
            self.assertEqual(args[0], 'ditto')
            shutil.copytree(args[1], args[2])
        with patch.object(ai.subprocess, 'run', side_effect=copy), patch.object(ai, 'require_closed'), \
                patch.object(ai, 'verify_bundle', side_effect=[{}, ValueError('bad final signature')]):
            with self.assertRaisesRegex(ValueError, 'signature'):
                ai.place_bundle('chatgpt', staged, self.destination)
        self.assertEqual(ai.bundle_info(self.destination)['CFBundleShortVersionString'], '1.0.0')
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])
        with patch.object(ai.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'ditto')):
            with self.assertRaises(subprocess.CalledProcessError):
                ai.place_bundle('chatgpt', staged, self.destination)
        self.assertEqual(ai.bundle_info(self.destination)['CFBundleShortVersionString'], '1.0.0')

    def test_failed_rollback_retains_previous_bundle_for_recovery(self):
        self.bundle(self.destination)
        staged = self.bundle(self.home / 'new.app', '2.0.0')
        original_rename = Path.rename
        def rename(path, target):
            if path.name == 'previous.app':
                raise OSError('simulated restore failure')
            return original_rename(path, target)
        with patch.object(ai.subprocess, 'run', side_effect=lambda args, **kwargs: shutil.copytree(args[1], args[2])), \
                patch.object(ai, 'require_closed'), patch.object(Path, 'rename', rename), \
                patch.object(ai, 'verify_bundle', side_effect=[{}, ValueError('bad final signature')]), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(OSError, 'restore failure'):
                ai.place_bundle('chatgpt', staged, self.destination)
        backups = list(self.destination.parent.glob('.1bite-*/previous.app'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(ai.bundle_info(backups[0])['CFBundleShortVersionString'], '1.0.0')

    def test_rejected_dmg_detaches_without_touching_destination(self):
        mount = self.home / 'mount'
        calls = []
        with patch.object(ai.subprocess, 'run', side_effect=lambda args, **kwargs: calls.append(args)):
            with self.assertRaisesRegex(ValueError, 'bad signature'):
                with ai.mounted(self.home / 'image.dmg', mount):
                    raise ValueError('bad signature')
        self.assertEqual([cmd[1] for cmd in calls], ['attach', 'detach'])
        self.assertFalse(self.destination.exists())

    def test_running_app_is_not_replaced_or_killed(self):
        self.bundle(self.destination)
        with patch.object(ai.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '123\n', '')) as run:
            with self.assertRaisesRegex(ValueError, 'Quit'):
                ai.require_closed(self.destination)
        self.assertEqual(run.call_args.args[0], ['/usr/sbin/lsof', '-t', '+D', str(self.destination)])

    def test_download_checksum_failure_leaves_no_receipt(self):
        with patch.object(ai.subprocess, 'run'):
            image = self.home / 'image.dmg'
            image.write_bytes(b'interrupted download')
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                ai.download('kiro-cli', 'https://vendor.invalid/dmg', image, 'a' * 64)
        self.assertFalse(ai.receipt_path('kiro-cli').exists())

    def test_vendor_identity_and_signature_checked_before_any_placement(self):
        app = self.bundle(self.destination)
        with patch.object(ai.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'codesign')) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                ai.verify_bundle('chatgpt', app)
            self.assertEqual(run.call_count, 1)
        with self.assertRaisesRegex(ValueError, 'identity'):
            ai.verify_bundle('kiro', app)

    def test_missing_app_and_managed_damage_install_from_verified_temporary_bundle(self):
        staged = self.bundle(self.home / 'vendor/ChatGPT.app', '2.0.0')
        @contextlib.contextmanager
        def mount(image, target):
            self.assertTrue(image.is_relative_to(target.parent))
            self.assertFalse(image.is_relative_to(self.destination.parent))
            yield staged.parent
        def copy(args, **kwargs):
            self.assertEqual(args[0], 'ditto')
            shutil.copytree(args[1], args[2])
        for owned, expected in [(False, 'installed'), (True, 'repaired')]:
            if owned:
                shutil.rmtree(self.destination / 'Contents/MacOS')
            with patch.object(ai, 'release', return_value=dict(version='2.0.0', build='10', url='https://vendor.invalid/current.dmg')), \
                    patch.object(ai, 'download'), patch.object(ai, 'mounted', side_effect=mount), \
                    patch.object(ai, 'verify_bundle', side_effect=lambda name, app: ai.bundle_info(app)), \
                    patch.object(ai, 'require_closed'), patch.object(ai.subprocess, 'run', side_effect=copy), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(ai.install_app('chatgpt', self.destination), expected)
            self.assertTrue((self.destination / 'Contents/MacOS/ChatGPT').is_file())
            self.assertTrue(ai.managed('chatgpt', self.destination))

    @unittest.skipUnless(sys.platform == 'darwin' and Path('/System/Applications/Utilities/Terminal.app').is_dir(),
                         'Requires a signed macOS system application')
    def test_real_macos_signature_requirement_syntax(self):
        # Read-only verification catches requirement text being mistaken for a filename.
        with patch.dict(ai.APPS, {'terminal': ('Terminal.app', 'com.apple.Terminal', ('Terminal.app',))}):
            ai.verify_signature('terminal', Path('/System/Applications/Utilities/Terminal.app'))

    def test_cli_preserves_existing_installations_and_refuses_unknown_damage(self):
        with patch.object(ai.shutil, 'which', return_value='/external/codex'), \
                patch.object(ai, 'release', side_effect=AssertionError('network')):
            self.assertEqual(ai.install_cli('codex', True, True), 'preserved')
            with self.assertRaisesRegex(ValueError, 'unknown broken CLI'):
                ai.install_cli('codex')

    def test_cli_native_install_streams_errors_and_records_only_success(self):
        def run(args, **kwargs):
            self.assertEqual(args[0], '/bin/sh')
            self.assertEqual(args[-2:], ['--release', '1.0.0'])
            self.assertEqual(kwargs['env']['CODEX_NON_INTERACTIVE'], '1')
            self.assertEqual(kwargs['umask'], 0o022)
        with patch.object(ai.shutil, 'which', return_value=None), patch.object(ai, 'download'), \
                patch.object(ai, 'release', return_value=dict(version='1.0.0', url='https://vendor.invalid/install.sh')), \
                patch.object(ai.subprocess, 'run', side_effect=run), \
                patch.object(ai.subprocess, 'check_output', return_value='codex 1.0.0\n'), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ai.install_cli('codex'), 'installed')
        self.assertTrue(ai.managed('codex', self.home / '.local/bin/codex'))
        with patch.object(ai.shutil, 'which', return_value=None), patch.object(ai, 'download'), \
                patch.object(ai, 'release', return_value=dict(version='1.0.0', url='https://vendor.invalid/install.sh')), \
                patch.object(ai.subprocess, 'run', side_effect=subprocess.CalledProcessError(27, 'installer')):
            with self.assertRaises(subprocess.CalledProcessError):
                ai.install_cli('claude')
        self.assertFalse(ai.receipt_path('claude').exists())


if __name__ == '__main__':
    unittest.main()
