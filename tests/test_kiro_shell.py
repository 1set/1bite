import contextlib
import importlib.util
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
spec = importlib.util.spec_from_file_location('kiro_shell', ROOT / 'scripts/kiro-shell.py')
kiro = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kiro)


class KiroShellTests(unittest.TestCase):
    def test_full_verifier_uses_the_stable_vendor_contract(self):
        verifier = (ROOT / 'scripts/verify.sh').read_text()
        self.assertIn('scripts/kiro-shell.py\" --verify', verifier)
        self.assertNotIn('fig_preexec', verifier)
        self.assertNotIn('fig_precmd', verifier)

    def test_custom_kiro_home_requires_supported_cli_before_any_writes(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'KIRO_HOME': directory + '/custom'}):
            home = Path(directory)
            for version, supported in [('1.29.2', False), ('2.2.9', False), ('2.3.0', True),
                                       ('2.21.1', True), ('3.0.0', True), ('unknown', False)]:
                with self.subTest(version=version), patch.object(kiro.subprocess, 'run') as run:
                    run.return_value.stdout = 'kiro-cli ' + version
                    if supported:
                        kiro.check_kiro_home_support('kiro-cli', home)
                    else:
                        with self.assertRaisesRegex(ValueError, 'requires Kiro CLI 2.3.0'):
                            kiro.check_kiro_home_support('kiro-cli', home)
            with patch.object(kiro, 'runnable', side_effect=lambda p: bool(p) and '/Kiro CLI.app/' in str(p)), \
                    patch.object(kiro.shutil, 'which', return_value=None), patch.object(kiro.subprocess, 'run') as run:
                run.return_value.stdout = 'kiro-cli 1.29.2'
                with self.assertRaisesRegex(ValueError, 'requires Kiro CLI 2.3.0'):
                    kiro.configure(home, home / 'Kiro CLI.app')
                self.assertEqual(list(home.iterdir()), [])
            with patch.dict(os.environ, {'KIRO_HOME': str(home / '.kiro')}), \
                    patch.object(kiro.subprocess, 'run') as run:
                kiro.check_kiro_home_support('kiro-cli', home)
                run.assert_not_called()

    def test_status_requires_complete_boolean_zsh_contract(self):
        rows = [dict(shell='zsh', file_name=name, installed=True) for name in ('.zshrc', '.zprofile')]
        valid = {'errors': [], 'integrations': rows + [dict(shell='bash', installed=False)]}
        invalid = [{'errors': ['failed'], 'integrations': rows}, {'integrations': []},
                   {'integrations': rows[:1]}, {'integrations': rows + rows},
                   {'integrations': [dict(rows[0], installed='true'), rows[1]]}]
        for data in [valid, *invalid]:
            with self.subTest(data=data), patch.object(kiro.subprocess, 'run') as run:
                run.return_value.stdout = json.dumps(data)
                if data is valid:
                    self.assertTrue(kiro.integration_status('kiro-cli'))
                else:
                    with self.assertRaises(ValueError):
                        kiro.integration_status('kiro-cli')
        rows[0]['installed'] = False
        with patch.object(kiro.subprocess, 'run') as run:
            run.return_value.stdout = json.dumps(valid)
            self.assertFalse(kiro.integration_status('kiro-cli'))

    def test_permission_preference_preserves_choices_and_rejects_invalid(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'KIRO_HOME': directory}):
            home = Path(directory)
            path = home / 'settings/cli.json'
            path.parent.mkdir()
            for value in (True, False):
                path.write_text(json.dumps({'inline.enabled': value, 'personal': 'keep'}))
                before = path.read_bytes()
                with patch.object(kiro.subprocess, 'run') as run:
                    self.assertFalse(kiro.inline_preference('kiro-cli', home, False))
                    run.assert_not_called()
                self.assertEqual(path.read_bytes(), before)
            for data in ([], {'inline.enabled': 'true'}):
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    kiro.inline_preference('kiro-cli', home, False)
            path.write_text('{}')
            with self.assertRaises(ValueError):
                kiro.inline_preference('kiro-cli', home, True)
            path.unlink()
            path.symlink_to(home / 'unknown')
            with self.assertRaises(ValueError):
                kiro.inline_preference('kiro-cli', home, False)

    def test_existing_unknown_broken_commands_and_symlink_dotfiles_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'ZDOTDIR': directory}):
            home = Path(directory)
            binaries = home / '.local/bin'
            binaries.mkdir(parents=True)
            command = binaries / 'kiro-cli'
            for link in (False, True):
                if link:
                    command.symlink_to(home / 'unknown-manager/missing')
                else:
                    command.write_text('personal broken command')
                with patch.object(kiro, 'runnable', return_value=False), self.assertRaises(ValueError):
                    kiro.configure(home, home / 'Kiro CLI.app')
                self.assertTrue(command.is_symlink() if link else command.is_file())
                command.unlink()
            (home / '.zshrc').symlink_to(home / 'personal')
            with self.assertRaises(ValueError):
                kiro.configure(home, home / 'Kiro CLI.app')
            self.assertFalse(list(binaries.iterdir()))

    def test_owned_broken_links_repair_and_healthy_commands_preserve(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'ZDOTDIR': directory}):
            home = Path(directory)
            binaries = home / '.local/bin'
            binaries.mkdir(parents=True)
            app = home / 'Applications/Kiro CLI.app'
            source = app / 'Contents/MacOS'
            source.mkdir(parents=True)
            for name in kiro.COMMANDS:
                ((source / name).resolve()).write_text('#!/bin/sh\nexit 0\n')
                ((source / name).resolve()).chmod(0o755)
                (binaries / name).symlink_to(home / 'old/Kiro CLI.app/Contents/MacOS' / name)
            helpers = home / 'Library/Application Support/kiro-cli/shell'
            helpers.mkdir(parents=True)
            for name, content in kiro.HELPERS.items():
                (helpers / name).write_text(content)
            with patch.object(kiro.shutil, 'which', return_value=None), \
                    patch.object(kiro, 'inline_preference', return_value=False), \
                    patch.object(kiro, 'verify_generated_hooks'), patch.object(kiro, 'integration_status', return_value=True):
                with self.assertRaises(ValueError):
                    kiro.configure(home, app, verify=True)
                with contextlib.redirect_stdout(io.StringIO()):
                    kiro.configure(home, app)
                for name in kiro.COMMANDS:
                    self.assertEqual((binaries / name).resolve(), (source / name).resolve())
                # Healthy independently managed commands remain untouched.
                personal = home / 'personal-cli'
                personal.write_text('#!/bin/sh\nexit 0\n')
                personal.chmod(0o755)
                (binaries / 'kiro-cli').unlink()
                (binaries / 'kiro-cli').symlink_to(personal)
                with contextlib.redirect_stdout(io.StringIO()):
                    kiro.configure(home, app)
                self.assertEqual((binaries / 'kiro-cli').resolve(), personal.resolve())

    @unittest.skipUnless(Path('/Applications/Kiro CLI.app').is_dir(), 'Requires the real macOS vendor app')
    def test_real_vendor_hooks_repeat_repair_zdotdir_and_zsh_execution(self):
        self.check_vendor_hooks(custom_home=False)

    @unittest.skipUnless(Path('/Applications/Kiro CLI.app').is_dir(), 'Requires the real macOS vendor app')
    def test_real_vendor_custom_home_support_or_safe_rejection(self):
        self.check_vendor_hooks(custom_home=True)

    def check_vendor_hooks(self, custom_home):
        with tempfile.TemporaryDirectory(prefix='kiro shell test ') as directory:
            home = Path(directory)
            shell = home / 'custom-zsh'
            shell.mkdir()
            (shell / '.zshrc').write_text('export ONE_BITE_PERSONAL=preserved\n')
            vendor_bin = '/Applications/Kiro CLI.app/Contents/MacOS'
            env = {'PATH':vendor_bin + os.pathsep + os.environ['PATH'], 'HOME':directory, 'ZDOTDIR':str(shell),
                   'SHELL':'/bin/zsh', 'TERM':'xterm-256color'}
            settings_home = home / ('custom-kiro' if custom_home else '.kiro')
            if custom_home:
                env['KIRO_HOME'] = str(settings_home)
                with patch.dict(os.environ, env, clear=True):
                    try:
                        kiro.check_kiro_home_support(Path(vendor_bin) / 'kiro-cli', home)
                    except ValueError:
                        result = subprocess.run([sys.executable, str(ROOT / 'scripts/kiro-shell.py'),
                                                 '--app', '/Applications/Kiro CLI.app'],
                                                env=env, capture_output=True, text=True, timeout=60)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn('requires Kiro CLI 2.3.0', result.stderr)
                        self.assertFalse((home / '.local').exists())
                        self.assertFalse((home / '.kiro').exists())
                        self.assertFalse(settings_home.exists())
                        return
            args = [sys.executable, str(ROOT / 'scripts/kiro-shell.py'), '--app', '/Applications/Kiro CLI.app']

            def run(extra=()):
                return subprocess.run([*args, *extra], env=env, capture_output=True, text=True, check=True, timeout=60)

            self.assertIn('installed-or-updated', run().stdout)
            helpers = home / 'Library/Application Support/kiro-cli/shell'
            tracked = [shell / '.zshrc', shell / '.zprofile', *helpers.glob('*.zsh'),
                       settings_home / 'settings/cli.json']
            before = {p:p.read_bytes() for p in tracked}
            self.assertIn('skipped', run().stdout)
            self.assertEqual(before, {p:p.read_bytes() for p in tracked})
            run(['--verify'])
            # Vendor releases may implement their post hook without the old
            # private fig_preexec/fig_precmd function names. The public
            # contract is a healthy integration whose login shell continues
            # into the user's existing configuration.
            command = 'print -r -- "$ONE_BITE_PERSONAL"'
            result = subprocess.run(['zsh', '-lic', command], env=env, capture_output=True, text=True, check=True, timeout=15)
            self.assertEqual(result.stdout.strip(), 'preserved')
            self.assertEqual(result.stderr, '')
            result = subprocess.run(['zsh', '-lc', 'printf noninteractive-ok'], env=env, capture_output=True, text=True, check=True, timeout=15)
            self.assertEqual(result.stdout, 'noninteractive-ok')
            self.assertEqual(result.stderr, '')
            (helpers / 'zshrc.post.zsh').unlink()
            with self.assertRaises(subprocess.CalledProcessError):
                run(['--verify'])
            run()
            run(['--verify'])
            (helpers / 'zshrc.post.zsh').write_text('# interrupted write: nonempty but no hook\n')
            with self.assertRaises(subprocess.CalledProcessError):
                run(['--verify'])
            run()
            run(['--verify'])
            self.assertFalse((home / '.bashrc').exists())
            self.assertFalse((home / '.zshrc').exists())


if __name__ == '__main__':
    unittest.main()
