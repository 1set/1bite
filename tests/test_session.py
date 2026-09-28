import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='setup-session-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.logs = self.root / 'logs'

    def command(self, body):
        return ['/bin/bash', '-c', 'source "$1"; ' + body.strip() + '; run_session "$2"',
                'test', str(ROOT / '1bite'), str(self.logs)]

    def run_session(self, body, env=None):
        return subprocess.run(self.command(body), text=True, input='', capture_output=True, env=env, timeout=15)

    def reports(self):
        return [json.loads(path.read_text()) for path in sorted(self.logs.glob('*/result.json'))]

    def test_success_report_schema_and_environment_privacy(self):
        env = dict(os.environ, SECRET_TEST_TOKEN='NEVER_RECORD_THIS', HTTPS_PROXY='https://user:NEVER_RECORD_THIS@proxy.invalid')
        result = self.run_session('execute_mode() { STEP_TOTAL=1; step_run demo echo completed; }', env)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = self.reports()[0]
        schema = json.loads((ROOT / 'docs/result.schema.json').read_text())
        self.assertTrue(set(schema['required']) <= set(report) <= set(schema['properties']))
        self.assertEqual(report['status'], 'success')
        self.assertEqual(report['completed_steps'], 1)
        self.assertEqual(report['total_steps'], 1)
        self.assertIs(report['update'], False)
        self.assertFalse((self.logs / 'install.lock').exists())
        for path in self.logs.rglob('*'):
            if path.is_file():
                self.assertNotIn('NEVER_RECORD_THIS', path.read_text())
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        environment = json.loads(next(self.logs.glob('*/environment.json')).read_text())
        self.assertEqual(set(environment), {'schema_version', 'os', 'os_version', 'architecture',
                                           'hardware_model', 'memory_bytes', 'proxy_configured'})
        self.assertTrue(environment['proxy_configured'])
        self.assertIn('Result: success', next(self.logs.glob('*/run.log')).read_text())

    def test_prepared_desktops_are_reported_as_manual_work(self):
        home = self.root / 'home'
        downloads = home / 'Downloads/1bite'
        downloads.mkdir(parents=True)
        chatgpt = downloads / 'chatgpt-1.2.3.dmg'
        docker = downloads / 'docker-desktop-latest.dmg'
        stale = downloads / 'google-chrome-old.dmg'
        unselected = downloads / 'claude-desktop-latest.dmg'
        chatgpt.write_bytes(b'chatgpt dmg')
        docker.write_bytes(b'docker dmg')
        stale.write_bytes(b'old download from another run')
        unselected.write_bytes(b'unselected claude dmg')
        receipts = json.dumps([
            {'component': 'chatgpt', 'filename': chatgpt.name},
            {'component': 'docker-desktop', 'filename': docker.name},
            {'component': 'claude-desktop', 'filename': unselected.name},
        ])
        body = f'''DESKTOP_MODE=download; MANUAL_STEPS=" chatgpt docker-desktop";
execute_mode() {{
  STEP_TOTAL=1
  printf '%s\\n' {shlex.quote(receipts)} >"$RUN_DIR/desktop-installers.json"
  step_run demo echo prepared
}}'''
        result = self.run_session(body, dict(os.environ, HOME=str(home)))
        self.assertEqual(result.returncode, 0, result.stderr)
        report = self.reports()[0]
        self.assertEqual(report['desktop_mode'], 'download')
        self.assertEqual(report['manual_steps'], ['chatgpt', 'docker-desktop'])
        self.assertIn('[MANUAL]', result.stdout)
        self.assertIn('you must still install them', result.stdout)
        guide = next(self.logs.glob('*/manual-steps.txt')).read_text()
        self.assertIn('A completed download does not mean the application is installed', guide)
        self.assertIn('1. ChatGPT / Codex desktop app', guide)
        self.assertIn('2. Docker Desktop', guide)
        self.assertIn('Package: ' + str(chatgpt.resolve()), guide)
        self.assertIn(shlex.join(['open', str(docker.resolve())]), guide)
        self.assertIn('go env GOPATH GOBIN', guide)
        self.assertIn('Identity and credentials are never copied from another Mac', guide)
        self.assertIn('into Applications', guide)
        self.assertIn('Eject the installer disk from the Finder sidebar', guide)
        self.assertIn('wait for the Docker engine to start', guide)
        self.assertIn('DOCKER_DEFAULT_PLATFORM to linux/amd64', guide)
        self.assertIn('~/.config/1bite/zsh/', guide)
        self.assertIn('grep -nF ".config/1bite" ~/.zshrc ~/.zprofile', guide)
        self.assertIn('do not replace the whole file', guide)
        self.assertIn('--verify', guide)
        self.assertNotIn('cannot locate the package', guide)
        self.assertNotIn(str(stale.resolve()), guide)
        self.assertNotIn(str(unselected.resolve()), guide)
        self.assertNotIn('Claude Desktop', guide)

    def test_powerlevel10k_onboarding_is_specific_and_not_a_download(self):
        home = self.root / 'home'
        home.mkdir()
        body = '''DESKTOP_MODE=download; MANUAL_STEPS=" powerlevel10k-configure";
execute_mode() {
  STEP_TOTAL=1
  step_run demo echo configured
}'''
        result = self.run_session(body, dict(os.environ, HOME=str(home)))
        self.assertEqual(result.returncode, 0, result.stderr)
        guide = next(self.logs.glob('*/manual-steps.txt')).read_text()
        self.assertIn('run exec zsh', guide)
        self.assertIn('p10k configure', guide)
        self.assertIn('MesloLGS NF', guide)
        self.assertNotIn('These packages are ready', guide)

    def test_app_display_does_not_imply_homebrew_and_keeps_machine_ids(self):
        result = self.run_session('execute_mode() { step_run cask:claude-desktop true; }')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('app:claude-desktop', result.stdout)
        self.assertNotIn('cask:claude-desktop', result.stdout)
        events = next(self.logs.glob('*/events.tsv')).read_text()
        self.assertIn('cask:claude-desktop', events)
        result = self.run_session('execute_mode() { step_run cask:claude-desktop false; }')
        self.assertEqual(result.returncode, 1)
        self.assertIn('[FAILED] app:claude-desktop', result.stdout)
        self.assertIn('cask:claude-desktop', {r['last_step'] for r in self.reports()})

    def test_failure_and_resume_use_actual_state(self):
        marker = shlex.quote(str(self.root / 'installed'))
        fixed = shlex.quote(str(self.root / 'fixed'))
        body = f'''
first() {{ if [[ -f {marker} ]]; then STEP_ACTION=skipped; else touch {marker}; STEP_ACTION=installed; echo FIRST-INSTALL; fi; }}
second() {{ test -f {fixed}; }}
execute_mode() {{ STEP_TOTAL=2; step_run first first; step_run second second; }}
'''
        result = self.run_session(body)
        self.assertEqual(result.returncode, 1)
        report = self.reports()[0]
        self.assertEqual((report['status'], report['last_step'], report['completed_steps']), ('failed', 'second', 1))
        self.assertFalse((self.logs / 'install.lock').exists())
        (self.root / 'fixed').touch()
        result = self.run_session(body)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('FIRST-INSTALL', result.stdout)
        self.assertIn('skipped', result.stdout)
        self.assertEqual({report['status'] for report in self.reports()}, {'success', 'failed'})
        # A removed installation must be redone even though previous logs say success.
        (self.root / 'installed').unlink()
        result = self.run_session(body)
        self.assertEqual(result.returncode, 0)
        self.assertIn('FIRST-INSTALL', result.stdout)

    def test_installer_permissions_are_separate_from_private_logs_on_success_and_failure(self):
        installer = self.root / 'installer.sh'
        installer.write_text('mkdir -p "$1"\n: > "$1/config"\nexit "$2"\n')
        for code in (0, 23):
            with self.subTest(exit_code=code):
                software = self.root / f'software-{code}'
                body = 'execute_mode() { step_run package run_package_installer /bin/bash '
                body += f'{shlex.quote(str(installer))} {shlex.quote(str(software))} {code}; '
                body += ': > "$RUN_DIR/private-after"; echo AFTER; }'
                result = self.run_session(body)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual('AFTER' in result.stdout, code == 0)
                self.assertEqual(software.stat().st_mode & 0o777, 0o755)
                self.assertEqual((software / 'config').stat().st_mode & 0o777, 0o644)
                self.assertFalse((self.logs / 'install.lock').exists())
        for path in self.logs.rglob('*'):
            self.assertEqual(path.stat().st_mode & 0o777, 0o700 if path.is_dir() else 0o600)
        self.assertEqual({report['exit_code'] for report in self.reports()}, {0, 23})

    def test_underlying_exit_code_and_terminated_worker(self):
        for body, expected in [
            ('execute_mode() { STEP_TOTAL=1; step_run download bash -c "exit 22"; }', 22),
            ('''execute_mode() { STEP_TOTAL=1; step_run interrupted bash -c 'kill -INT "$PPID"'; }''', 130),
            ('''execute_mode() { STEP_TOTAL=1; step_run interrupted bash -c 'kill -TERM "$PPID"'; }''', 143)]:
            with self.subTest(expected=expected):
                result = self.run_session(body)
                self.assertEqual(result.returncode, expected, result.stderr)
                self.assertFalse((self.logs / 'install.lock').exists())
        self.assertEqual({report['exit_code'] for report in self.reports()}, {22, 130, 143})

    def test_concurrent_process_is_rejected(self):
        release = self.root / 'release'
        body = f'wait_for_release() {{ while [[ ! -f {shlex.quote(str(release))} ]]; do sleep 0.05; done; }}; '
        body += 'execute_mode() { touch "$RUN_DIR/ready"; STEP_TOTAL=1; step_run wait wait_for_release; }'
        process = subprocess.Popen(self.command(body),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            deadline = time.monotonic() + 5
            while not list(self.logs.glob('*/ready')) and time.monotonic() < deadline:
                time.sleep(0.01)
            result = self.run_session('execute_mode() { :; }')
            self.assertEqual(result.returncode, 75)
        finally:
            release.touch()
            process.communicate(timeout=5)

    def test_log_writer_failure_is_not_success(self):
        result = self.run_session('tee() { cat >/dev/null; return 1; }; execute_mode() { :; }')
        self.assertEqual(result.returncode, 74)
        self.assertEqual(self.reports()[0]['exit_code'], 74)
        self.assertFalse((self.logs / 'install.lock').exists())

    def test_plain_log_writer_failure_and_original_failure(self):
        for failure, expected in [('return 0', 74), ('return 22', 22)]:
            result = self.run_session('awk() { cat >/dev/null; return 1; }; '
                                      'execute_mode() { ' + failure + '; }')
            self.assertEqual(result.returncode, expected, result.stderr)
        self.assertEqual({report['exit_code'] for report in self.reports()}, {74, 22})
        self.assertFalse((self.logs / 'install.lock').exists())

    def test_colored_statuses_plain_logs_and_vendor_warnings_survive(self):
        env = {**os.environ, 'ONE_BITE_COLOR': 'always', 'ONE_BITE_ICONS': 'emoji', 'TERM': 'xterm-256color'}
        env.pop('NO_COLOR', None)
        result = self.run_session('''
action() { STEP_ACTION=$1; }
warning() { warn 'download needs attention'; STEP_ACTION=warning; }
execute_mode() {
  STEP_TOTAL=4
  step_run installed action installed
  step_run skipped action skipped
  step_run preserved action preserved
  step_run warning warning
  printf 'Warning: vendor tap\\n  details must survive\\n' >&2
}
''', env)
        self.assertEqual(result.returncode, 0, result.stderr)
        for tag, icon, color in [('1/4', '⏳', 36), ('OK', '✅', 32), ('SKIP', '⏭️', 34),
                                  ('KEEP', '📌', 34), ('WARN', '⚠️', 33), ('DONE', '⚠️', 33)]:
            self.assertIn(f'\x1b[{color}m{icon} [{tag}]', result.stdout)
        self.assertIn('[###############.....] 75% warning', result.stdout)
        self.assertNotIn('[OK] warning', result.stdout)
        self.assertIn('success (with setup warnings)', result.stdout)
        log = next(self.logs.glob('*/run.log')).read_text()
        plain = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout)
        plain = re.sub(r'^(?:⏳|✅|⏭️|⚠️|❌|ℹ️|📌) (?=\[)', '', plain, flags=re.M)
        self.assertEqual(log, plain)
        self.assertIn('Warning: vendor tap\n  details must survive\n', log)
        self.assertIn('\twarning\tnotice\n', next(self.logs.glob('*/events.tsv')).read_text())
        failure = self.run_session('execute_mode() { step_run bad bash -c "exit 23"; }', env)
        self.assertEqual(failure.returncode, 23)
        self.assertIn('\x1b[31m❌ [FAILED]', failure.stdout)
        failure = self.run_session('execute_mode() { fail "sample failure"; }', env)
        self.assertEqual(failure.returncode, 1)
        self.assertIn('\x1b[31m❌ [FAILED] ERROR: sample failure', failure.stdout)
        for log_path in self.logs.glob('*/run.log'):
            self.assertNotIn('\x1b', log_path.read_text())
            self.assertNotIn('❌', log_path.read_text())

    def test_color_modes_tty_detection_and_plain_fallback(self):
        base = {key:value for key,value in os.environ.items()
                if key not in ('ONE_BITE_COLOR', 'ONE_BITE_ICONS', 'NO_COLOR', 'CI', 'GITHUB_ACTIONS', 'LC_ALL', 'LC_CTYPE')}
        base.update(TERM='xterm-256color', LANG='en_US.UTF-8')
        args = ['/bin/bash', '-c', 'source "$1"; ui_init; ui_print warn "[WARN] sample"', 'test', str(ROOT / '1bite')]
        cases = [({}, False, False), ({'ONE_BITE_COLOR':'always', 'ONE_BITE_ICONS':'emoji'}, True, True),
                 ({'ONE_BITE_COLOR':'always', 'NO_COLOR':'1'}, False, False),
                 ({'ONE_BITE_COLOR':'always', 'TERM':'dumb'}, False, False)]
        for overrides, color, icons in cases:
            result = subprocess.run(args, env={**base, **overrides}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual('\x1b[' in result.stdout, color)
            self.assertEqual('⚠️' in result.stdout, icons)
        for setting in ['ONE_BITE_COLOR', 'ONE_BITE_ICONS']:
            result = self.run_session('execute_mode() { :; }', {**base, setting:'invalid'})
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn(f'ERROR: {setting} must be', result.stderr)
            self.assertFalse(self.logs.exists())
        for overrides, color, icons in [({}, True, True), ({'CI':'true'}, False, False),
                                        ({'ONE_BITE_COLOR':'never', 'ONE_BITE_ICONS':'ascii'}, False, False),
                                        ({'LANG':'C'}, True, False)]:
            master, slave = pty.openpty()
            try:
                process = subprocess.Popen(args, env={**base, **overrides}, stdout=slave, stderr=slave)
                os.close(slave)
                slave = None
                output = b''
                while True:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output += chunk
                self.assertEqual(process.wait(timeout=5), 0)
                self.assertEqual(b'\x1b[' in output, color)
                self.assertEqual('⚠️' in output.decode(), icons)
            finally:
                os.close(master)
                if slave is not None:
                    os.close(slave)

    def test_unterminated_output_reaches_terminal_before_command_finishes(self):
        release = self.root / 'release-output'
        body = 'execute_mode() { printf "PROMPT-WITHOUT-NEWLINE"; '
        body += f'while [[ ! -f {shlex.quote(str(release))} ]]; do sleep 0.05; done; }}'
        process = subprocess.Popen(self.command(body), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output = b''
        try:
            deadline = time.monotonic() + 5
            while b'PROMPT-WITHOUT-NEWLINE' not in output and time.monotonic() < deadline:
                if select.select([process.stdout], [], [], 0.1)[0]:
                    chunk = os.read(process.stdout.fileno(), 4096)
                    if not chunk:
                        break
                    output += chunk
            self.assertIn(b'PROMPT-WITHOUT-NEWLINE', output)
            self.assertIsNone(process.poll())
        finally:
            release.touch()
            process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0)
        self.assertIn('PROMPT-WITHOUT-NEWLINE', next(self.logs.glob('*/run.log')).read_text())

    def test_default_network_does_not_contact_claude(self):
        result = self.run_session('''MODE=diagnose
curl() { case "$*" in *claude*) return 99;; *) echo 200;; esac; }
execute_mode() { STEP_TOTAL=1; step_run network network_check; }
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('anthropic', next(self.logs.glob('*/network.tsv')).read_text())
        self.assertIs(self.reports()[0]['with_claude'], False)

    def test_network_statuses_and_diagnostics_failure(self):
        body = '''
MODE=diagnose
WITH_CLAUDE=true
curl() { case "$*" in *claude.ai*) echo 503;; *ghcr.io*) echo 401;; *) echo 200;; esac; }
execute_mode() { STEP_TOTAL=1; step_run network network_check; }
'''
        result = self.run_session(body)
        self.assertEqual(result.returncode, 1)
        lines = next(self.logs.glob('*/network.tsv')).read_text().splitlines()
        self.assertEqual(len(lines), 7)
        self.assertIn('ghcr\t401\t0', lines)
        self.assertIn('anthropic\t503\t0', lines)
        self.assertIn('[WARN] Network anthropic: HTTP 503', result.stdout)


if __name__ == '__main__':
    unittest.main()
