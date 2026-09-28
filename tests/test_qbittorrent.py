import argparse
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('qbt', ROOT / 'apps/qbittorrent/qbt.py')
qbt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qbt)


class QbittorrentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='qbt unit ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.state = self.root / 'state'
        self.state.mkdir()
        self.password = 'only-a-unit-test-password'
        self.args = argparse.Namespace(downloads=self.root / 'downloads', port=1024,
                                       bt_port=6881, bind='0.0.0.0', password_stdin=True)

    def initialize(self):
        with patch.object(qbt, 'check_engine'), patch.object(qbt, 'run', return_value='desktop-linux\n'), \
                patch.object(qbt, 'docker', return_value='aarch64\n'), \
                patch.object(qbt, 'compose', return_value=''), \
                patch('sys.stdin', io.StringIO(self.password + '\n')), \
                contextlib.redirect_stdout(io.StringIO()):
            return qbt.initialize(self.state, self.args)

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
                for p in self.root.rglob('*') if p.is_file()}

    def test_first_init_and_all_persisted_settings(self):
        settings = self.initialize()
        self.assertEqual(settings, dict(image=qbt.PIN, platform='linux/arm64', uid=os.getuid(),
                                        gid=os.getgid(), timezone='Asia/Shanghai', web_port=1024,
                                        bt_port=6881, bind='0.0.0.0', downloads=str(self.args.downloads),
                                        context='desktop-linux', project='qbt-' + hashlib.sha256(
                                            str(self.state).encode()).hexdigest()[:12]))
        self.assertEqual(qbt.load_settings(self.state), settings)
        conf = self.state / 'config/qBittorrent/qBittorrent.conf'
        self.assertNotIn(self.password, conf.read_text())
        salt, hashed = map(base64.b64decode, re.search(r'@ByteArray\(([^)]+)\)', conf.read_text()).group(1).split(':'))
        self.assertEqual(len(salt), 16)
        self.assertEqual(hashlib.pbkdf2_hmac('sha512', self.password.encode(), salt, 100000, 64), hashed)
        self.assertEqual(conf.stat().st_mode & 0o777, 0o600)
        self.assertTrue((self.args.downloads / 'complete').is_dir())
        self.assertTrue((self.args.downloads / 'incomplete').is_dir())

    def test_repeated_init_preserves_personal_password_settings_and_downloads(self):
        self.initialize()
        conf = self.state / 'config/qBittorrent/qBittorrent.conf'
        conf.write_text(conf.read_text().replace('WebUI\\Username=admin', 'WebUI\\Username=personal') + '\n# personal\n')
        (self.args.downloads / 'complete/saved.bin').write_bytes(b'keep downloaded bytes')
        before = self.snapshot()
        self.password = 'different-never-applied-password'
        self.initialize()
        self.assertEqual(before, self.snapshot())
        for field, value in [('downloads', self.root / 'elsewhere'), ('port', 8024),
                             ('bt_port', 7999), ('bind', '127.0.0.1')]:
            old = getattr(self.args, field)
            setattr(self.args, field, value)
            with self.assertRaises(ValueError):
                self.initialize()
            setattr(self.args, field, old)
            self.assertEqual(before, self.snapshot())

    def test_invalid_initial_ports_and_paths_do_not_create_configuration(self):
        for field, value in [('port', 0), ('port', 65536), ('bt_port', 0),
                             ('bt_port', 65536), ('port', 6881), ('bind', 'not-an-ip'),
                             ('downloads', self.state), ('downloads', self.state / 'nested')]:
            old = getattr(self.args, field)
            setattr(self.args, field, value)
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.initialize()
            setattr(self.args, field, old)
            self.assertFalse((self.state / 'settings.json').exists())
        link = self.root / 'link'
        link.symlink_to(self.state, target_is_directory=True)
        with self.assertRaises(ValueError):
            qbt.checked_path(link / 'config')
        with self.assertRaises(ValueError):
            qbt.checked_path('/Volumes/qbt-unmounted-unit-test/downloads')

    def test_missing_config_on_existing_container_does_not_reset_password(self):
        self.initialize()
        conf = self.state / 'config/qBittorrent/qBittorrent.conf'
        conf.unlink()
        with patch.object(qbt, 'compose', return_value='existing-container'), self.assertRaises(ValueError):
            qbt.initialize(self.state, self.args)
        self.assertFalse(conf.exists())

    def test_remote_context_and_unknown_settings_are_rejected(self):
        self.initialize()
        with patch.object(qbt, 'docker', return_value=json.dumps([
                {'Endpoints': {'docker': {'Host': 'ssh://remote.invalid'}}}])):
            with self.assertRaises(ValueError):
                qbt.check_engine(qbt.load_settings(self.state))
        settings = qbt.load_settings(self.state)
        for field in settings:
            invalid = dict(settings)
            del invalid[field]
            qbt.save_settings(self.state, invalid)
            with self.subTest(field=field), self.assertRaises(ValueError):
                qbt.load_settings(self.state)
        settings['unknown'] = True
        qbt.save_settings(self.state, settings)
        with self.assertRaises(ValueError):
            qbt.load_settings(self.state)

    def test_new_digest_update_stops_before_backup_and_preserves_downloads(self):
        self.initialize()
        before = qbt.load_settings(self.state)
        conf = self.state / 'config/qBittorrent/qBittorrent.conf'
        download = self.args.downloads / 'complete/keep.bin'
        download.write_bytes(b'completed torrent')
        digest = qbt.IMAGE + '@sha256:' + '1' * 64
        actions = []

        def docker(settings, *args, **kwargs):
            actions.append(args[0])
            return json.dumps([digest]) if args[0] == 'image' else None

        def compose(state, settings, *args, **kwargs):
            actions.append(args[0])
            if args[0] == 'stop':
                conf.write_text(conf.read_text() + '# flushed on stop\n')

        with patch('sys.argv', ['qbt.py', 'update', '--state-dir', str(self.state)]), \
                patch.object(qbt, 'check_engine'), patch.object(qbt, 'docker', side_effect=docker), \
                patch.object(qbt, 'compose', side_effect=compose), patch.object(qbt, 'ready'), \
                patch.object(qbt.os, 'umask'):
            qbt.main()
        self.assertEqual(actions, ['pull', 'image', 'stop', 'up'])
        backup, = (self.state / 'backups').iterdir()
        self.assertEqual(json.loads((backup / 'settings.json').read_text()), before)
        self.assertEqual((backup / 'config/qBittorrent/qBittorrent.conf').read_bytes(), conf.read_bytes())
        self.assertEqual(qbt.load_settings(self.state)['image'], digest)
        self.assertEqual(download.read_bytes(), b'completed torrent')

    def test_update_pull_failure_leaves_running_container_and_data_untouched(self):
        self.initialize()
        before = self.snapshot()
        with patch('sys.argv', ['qbt.py', 'update', '--state-dir', str(self.state)]), \
                patch.object(qbt, 'check_engine'), patch.object(qbt, 'docker',
                side_effect=subprocess.CalledProcessError(1, ['docker', 'pull'])), \
                patch.object(qbt, 'compose') as compose, patch.object(qbt.os, 'umask'):
            with self.assertRaises(subprocess.CalledProcessError):
                qbt.main()
            compose.assert_not_called()
        after = self.snapshot()
        after.pop('state/operation.lock', None)
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
