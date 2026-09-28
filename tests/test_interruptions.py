"""Real SIGKILL fault injection in temporary homes; never run vendor downloads."""
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import official_ai as ai
import desktop
import configure


class InterruptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='setup-interruption-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.logs = self.home / 'logs'
        self.environment = patch.dict(os.environ, HOME=str(self.home),
                                      XDG_STATE_HOME=str(self.home / 'state'), ZSH=str(self.home / '.oh-my-zsh'), RUN_DIR='')
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def killed(self, operation):
        pid = os.fork()
        if pid == 0:
            try:
                operation()
            except BaseException:
                import traceback
                traceback.print_exc()
            os._exit(99)
        _, status = os.waitpid(pid, 0)
        self.assertTrue(os.WIFSIGNALED(status), status)
        self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)

    def die(self):
        os.kill(os.getpid(), signal.SIGKILL)

    def command(self, body):
        return ['/bin/bash', '-c', 'source "$1"; ' + body + '; run_session "$2"',
                'test', str(ROOT / '1bite'), str(self.logs)]

    def rerun(self):
        return subprocess.run(self.command('execute_mode() { :; }'),
                              capture_output=True, text=True, timeout=10)

    def wait_file(self, path):
        deadline = time.monotonic() + 5
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(path.exists(), path)
        return path.read_text().strip()

    def test_kill_before_kernel_lock_acquisition_does_not_poison_next_run(self):
        self.logs.mkdir()
        # Opening the persistent inode is harmless, even without acquiring it.
        self.killed(lambda: (open(self.logs / 'session.lock', 'a'), self.die()))
        result = self.rerun()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.rerun().returncode, 0)

    def test_killed_worker_and_supervisor_do_not_unlock_live_installer_child(self):
        ready, release = self.home / 'ready', self.home / 'release'
        installer = self.home / 'installer.sh'
        installer.write_text('printf "%s\\n" "$PPID" > "$1"\n'
                             'while [ ! -e "$2" ]; do sleep 0.05; done\n')
        body = ('execute_mode() { /bin/bash ' + shlex.quote(str(installer)) + ' '
                + shlex.quote(str(ready)) + ' ' + shlex.quote(str(release)) + '; :; }')
        process = subprocess.Popen(self.command(body), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        try:
            worker = int(self.wait_file(ready))
            os.kill(worker, signal.SIGKILL)
            process.kill()
            self.assertEqual(self.rerun().returncode, 75)
        finally:
            release.touch()
            process.communicate(timeout=10)
        self.assertEqual(self.rerun().returncode, 0)

    def test_killed_entire_session_releases_kernel_lock(self):
        ready = self.home / 'ready'
        body = 'execute_mode() { touch ' + shlex.quote(str(ready)) + '; sleep 30; }'
        process = subprocess.Popen(self.command(body), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        try:
            self.wait_file(ready)
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=5)
            self.assertEqual(self.rerun().returncode, 0)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=5)

    def test_cli_partial_first_install_and_missing_receipt_are_repaired(self):
        for name in ('codex', 'claude'):
            with self.subTest(cli=name):
                destination = self.home / '.local/bin' / name
                def download(component, url, installer):
                    installer.write_text('mkdir -p "$HOME/.local/bin"\n'
                                         f'printf "#!/bin/sh\\nexit 23\\n" > "$HOME/.local/bin/{name}"\n'
                                         f'chmod +x "$HOME/.local/bin/{name}"\nkill -KILL "$PPID"\n')
                with patch.object(ai, 'release', return_value=dict(version='1.0.0', url='unused')), \
                        patch.object(ai, 'download', side_effect=download), \
                        patch.object(ai.shutil, 'which', return_value=None):
                    self.killed(lambda: ai.install_cli(name))
                self.assertTrue(destination.exists())
                self.assertFalse(ai.receipt_path(name).exists())
                self.assertTrue(ai.pending_path(name).exists())
                def complete(component, url, installer):
                    installer.write_text(f'printf "#!/bin/sh\\necho {name} 1.0.0\\n" > "$HOME/.local/bin/{name}"\n')
                with patch.object(ai, 'release', return_value=dict(version='1.0.0', url='unused')), \
                        patch.object(ai, 'download', side_effect=complete), \
                        patch.object(ai.shutil, 'which', return_value=str(destination)):
                    self.assertEqual(ai.install_cli(name), 'repaired')
                    self.assertEqual(ai.install_cli(name, healthy=True), 'skipped')
                self.assertFalse(ai.pending_path(name).exists())
                self.assertTrue(ai.managed(name, destination))

    @unittest.skipUnless(sys.platform == 'darwin', 'Shell dispatch invokes the macOS-only installation entry point')
    def test_healthy_cli_with_pending_receipt_is_finalized_by_shell_dispatch(self):
        destination = self.home / '.local/bin/codex'
        destination.parent.mkdir(parents=True)
        destination.write_text('#!/bin/sh\necho codex 1.0.0\n')
        destination.chmod(0o755)
        ai.begin_install('codex', destination, '1.0.0')
        # Exercise the healthy-tool fast path, including the real Python helper.
        env = {**os.environ, 'PATH': str(destination.parent) + os.pathsep + os.environ['PATH']}
        result = subprocess.run(['/bin/bash', '-c', 'source "$1"; check_agent codex',
                                 'test', str(ROOT / '1bite')], env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(ai.pending_path('codex').exists())
        self.assertTrue(ai.receipt_path('codex').exists())

    def test_killed_ohmyzsh_clone_does_not_leave_broken_final_directory(self):
        installer = self.home / 'omz-installer.sh'
        installer.write_text('mkdir -p "$ZSH"\necho partial > "$ZSH/oh-my-zsh.sh"\nkill -KILL "$PPID"\n')
        body = ('download_installer() { cp ' + shlex.quote(str(installer)) + ' "$2"; }; '
                'execute_mode() { ensure_ohmyzsh; }')
        result = subprocess.run(self.command(body), capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 137, result.stderr)
        self.assertFalse((self.home / '.oh-my-zsh').exists())
        installer.write_text('mkdir -p "$ZSH/lib" "$ZSH/themes" "$ZSH/plugins/git"\n'
                             'for file in oh-my-zsh.sh lib/git.zsh lib/cli.zsh '
                             'themes/robbyrussell.zsh-theme plugins/git/git.plugin.zsh; do\n'
                             'echo complete > "$ZSH/$file"\ndone\n')
        result = subprocess.run(self.command(body), capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(self.command(body), capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_python_native_child_keeps_lock_after_python_and_shell_are_killed(self):
        ready, release = self.home / 'ready', self.home / 'release'
        driver = self.home / 'driver.py'
        driver.write_text('import subprocess, sys\n'
                          f'sys.path.insert(0, {str(ROOT / "scripts")!r})\n'
                          'import official_ai\n'
                          f'child = subprocess.Popen(["/bin/bash", "-c", \'echo "$$" > "$1"; '
                          'while [ ! -e "$2" ]; do sleep 0.05; done\', "test", '
                          f'{str(ready)!r}, {str(release)!r}], pass_fds=official_ai.inherited_lock(), '
                          'start_new_session=True, stdin=subprocess.DEVNULL, '
                          'stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\nchild.wait()\n')
        body = 'execute_mode() { ' + shlex.quote(sys.executable) + ' ' + shlex.quote(str(driver)) + '; :; }'
        process = subprocess.Popen(self.command(body), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        child = None
        try:
            child = int(self.wait_file(ready))
            # Remove every supervisor and log writer, leaving only the native
            # child in its own group with descriptor 9 and no shared stdout.
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=5)
            self.assertEqual(self.rerun().returncode, 75)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate(timeout=5)
            if child is not None:
                os.killpg(child, signal.SIGKILL)
        deadline = time.monotonic() + 5
        while True:
            result = self.rerun()
            if result.returncode != 75 or time.monotonic() >= deadline:
                break
            time.sleep(0.01)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_app_crash_between_renames_or_before_receipt_recovers(self):
        # These are isolated fake bundles. Signature validation itself is covered
        # by the real signed-app test and disposable-runner installation tests.
        for phase in ('copy', 'backup', 'placed', 'recorded'):
            with self.subTest(phase=phase):
                directory = self.home / phase
                directory.mkdir()
                destination, source = directory / 'ChatGPT.app', directory / 'source.app'
                destination.mkdir()
                (destination / 'version').write_text('1.0.0')
                source.mkdir()
                (source / 'version').write_text('2.0.0')
                ai.record('chatgpt', destination, '1.0.0')
                def info(app):
                    return {'CFBundleShortVersionString': (app / 'version').read_text()}
                original_rename, original_record = Path.rename, ai.record
                def copy(args, **kwargs):
                    shutil.copytree(args[1], args[2])
                    if phase == 'copy':
                        self.die()
                def rename(path, target):
                    result = original_rename(path, target)
                    if ((phase == 'backup' and target.name == 'previous.app')
                            or (phase == 'placed' and target == destination)):
                        self.die()
                    return result
                def record(*args):
                    original_record(*args)
                    if phase == 'recorded':
                        self.die()
                with patch.object(ai, 'bundle_info', side_effect=info), \
                        patch.object(ai, 'verify_bundle', side_effect=lambda name, app: info(app)), \
                        patch.object(ai, 'require_closed'), patch.object(ai.subprocess, 'run', side_effect=copy), \
                        patch.object(Path, 'rename', rename), patch.object(ai, 'record', side_effect=record):
                    self.killed(lambda: ai.place_bundle('chatgpt', source, destination))
                with patch.object(ai, 'verify_bundle', side_effect=lambda name, app: info(app)):
                    self.assertTrue(ai.recover_app('chatgpt', destination))
                expected = '1.0.0' if phase in ('copy', 'backup') else '2.0.0'
                self.assertEqual((destination / 'version').read_text(), expected)
                self.assertEqual(json.loads(ai.receipt_path('chatgpt').read_text())['version'], expected)
                self.assertFalse(list(directory.glob('.1bite-*')))
                self.assertFalse(ai.pending_path('chatgpt').exists())

    def test_configuration_crash_preserves_original_and_can_finish_on_rerun(self):
        path = self.home / 'managed-shell'
        path.write_bytes(b'previous template\n')
        original = os.replace
        def replace(source, destination):
            if Path(destination) == path:
                self.die()
            return original(source, destination)
        with patch.object(configure.os, 'replace', side_effect=replace):
            self.killed(lambda: configure.write(path, b'updated template\n'))
        self.assertEqual(path.read_bytes(), b'previous template\n')
        self.assertTrue(any(p.read_bytes() == b'previous template\n'
                            for p in self.home.glob('managed-shell.backup-*')))
        configure.write(path, b'updated template\n')
        configure.write(path, b'updated template\n')
        self.assertEqual(path.read_bytes(), b'updated template\n')

    def test_invalid_app_transaction_does_not_remove_other_directories(self):
        destination = self.home / 'Applications/ChatGPT.app'
        personal = self.home / 'personal'
        personal.mkdir()
        (personal / 'keep').write_text('unchanged')
        ai.begin_install('chatgpt', destination, '1.0.0', staging=str(personal))
        with self.assertRaisesRegex(ValueError, 'staging path'):
            ai.recover_app('chatgpt', destination)
        self.assertEqual((personal / 'keep').read_text(), 'unchanged')

    def test_download_crash_before_receipt_is_revalidated_on_rerun(self):
        original = Path.replace
        def replace(path, target):
            result = original(path, target)
            if str(target).endswith('.dmg'):
                self.die()
            return result
        def download(name, url, destination, digest=None):
            destination.write_bytes(b'complete test DMG')
        with patch.object(desktop.vendor, 'download', side_effect=download), \
                patch.object(desktop.subprocess, 'run'), patch.object(Path, 'replace', replace):
            self.killed(lambda: desktop.prepare('google-chrome'))
        self.assertIsNone(desktop.prepared('google-chrome'))
        with patch.object(desktop.vendor, 'download', side_effect=download) as fetch, \
                patch.object(desktop.subprocess, 'run'):
            desktop.prepare('google-chrome')
            desktop.prepare('google-chrome')
            self.assertEqual(fetch.call_count, 1)
        self.assertIsNotNone(desktop.prepared('google-chrome'))
        self.assertFalse((self.home / 'Applications').exists())


if __name__ == '__main__':
    unittest.main()
