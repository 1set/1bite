import contextlib
import importlib.util
import io
import http.server
import json
import os
from pathlib import Path
import subprocess
import shlex
import shutil
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('configure', ROOT / 'scripts/configure.py')
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)
runtime_spec = importlib.util.spec_from_file_location('runtime_smoke', ROOT / 'scripts/runtime-smoke.py')
runtime_smoke = importlib.util.module_from_spec(runtime_spec)
runtime_spec.loader.exec_module(runtime_smoke)


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='setup test ')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def apply(self, config_dir=ROOT / 'config'):
        with contextlib.redirect_stdout(io.StringIO()):
            configure.configure(self.home, config_dir, with_claude=True)

    def snapshot(self):
        return {str(p.relative_to(self.home)): p.read_bytes()
                for p in self.home.rglob('*') if p.is_file()}

    def git_config(self, *args, check=True):
        env = {key: value for key, value in os.environ.items()
               if not key.startswith('GIT_CONFIG_') and key != 'XDG_CONFIG_HOME'}
        env.update(HOME=str(self.home), XDG_CONFIG_HOME=str(self.home / '.config'), GIT_CONFIG_NOSYSTEM='1')
        return subprocess.run(['git', 'config', '--global', *args], env=env, text=True,
                              capture_output=True, check=check)

    def test_claude_configuration_is_opt_in_and_unselected_private_files_are_untouched(self):
        with contextlib.redirect_stdout(io.StringIO()):
            configure.configure(self.home, ROOT / 'config')
            configure.verify(self.home)
        self.assertFalse((self.home / '.claude').exists())
        private = self.home / '.claude'
        private.mkdir()
        settings = private / 'settings.json'
        settings.write_text('{invalid personal config')
        before = self.snapshot()
        with contextlib.redirect_stdout(io.StringIO()):
            configure.configure(self.home, ROOT / 'config')
            configure.verify(self.home)
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.snapshot(), before)
        settings.unlink()
        self.apply()
        self.assertTrue(settings.is_file())
        before = self.snapshot()
        with contextlib.redirect_stdout(io.StringIO()):
            configure.configure(self.home, ROOT / 'config')
        self.assertEqual(self.snapshot(), before)

    def test_configuration_cli_ignores_unselected_claude_override(self):
        env = {**os.environ, 'HOME': str(self.home), 'CODEX_HOME': str(self.home / '.codex'),
               'ZDOTDIR': str(self.home), 'CLAUDE_CONFIG_DIR': 'invalid-relative-path', 'ONE_BITE_WITH_CLAUDE': 'false'}
        command = ['python3', str(ROOT / 'scripts/configure.py')]
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.home / '.claude').exists())
        before = self.snapshot()
        result = subprocess.run(command + ['--with-claude'], env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.snapshot(), before)

    def test_complete_template_contract(self):
        actual = {str(p.relative_to(ROOT / 'config')): p.read_text()
                  for p in sorted((ROOT / 'config').rglob('*'))
                  if p.is_file() and p.name != '.DS_Store'}
        expected = json.loads((ROOT / 'tests/fixtures/config-golden.json').read_text())
        self.assertEqual(actual, expected)

    def test_iterm_default_is_managed_across_upgrade_but_respects_a_later_user_choice(self):
        legacy = '703f9b42-2cc7-4a89-8e5e-887014d02daa'
        current = '84911aa0-4114-494c-a17c-6a2ef38b5b34'
        personal = '11111111-1111-4111-8111-111111111111'
        user_selected = '22222222-2222-4222-8222-222222222222'
        state = self.home / configure.ITERM_DEFAULT_STATE_PATH
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({'schema_version': 1, 'original_guid': personal,
                                     'managed_guid': legacy}) + '\n')
        configure.write_iterm_default(self.home, legacy)
        self.apply()
        self.assertEqual(configure.read_iterm_default(self.home), current)
        self.assertEqual(json.loads(state.read_text()),
                         {'schema_version': 1, 'original_guid': personal,
                          'managed_guid': current})
        before = self.snapshot()
        self.apply()
        self.assertEqual(self.snapshot(), before)

        configure.write_iterm_default(self.home, user_selected)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.apply()
            configure.verify(self.home, with_claude=True)
        self.assertEqual(configure.read_iterm_default(self.home), user_selected)
        self.assertIn('iTerm2 default profile is a preserved user override', output.getvalue())

        preference = self.home / configure.ITERM_PREFERENCES_PATH
        preference.write_bytes(configure.plistlib.dumps({}))
        with self.assertRaisesRegex(ValueError, 'valid default profile Guid'):
            configure.verify_iterm_default(self.home, current)

    def test_obsidian_starter_and_command_are_managed_without_workspace_state(self):
        self.apply()
        source = configure.obsidian_template_files(ROOT / 'config')
        installed = self.home / configure.OBSIDIAN_TEMPLATE_PATH
        actual = {str(path.relative_to(installed)): path.read_bytes()
                  for path in installed.rglob('*') if path.is_file()}
        self.assertEqual(actual, source)
        self.assertFalse((installed / '.obsidian/workspace.json').exists())
        for relative in configure.OBSIDIAN_COMMAND_PATHS:
            command = self.home / relative
            self.assertEqual(command.read_bytes(), (ROOT / 'scripts/ob.py').read_bytes())
            self.assertTrue(command.stat().st_mode & 0o111)
        configure.verify(self.home, with_claude=True)

    def test_obsidian_template_updates_back_up_outside_the_scaffold(self):
        self.apply()
        external = self.home / 'external-config'
        shutil.copytree(ROOT / 'config', external)
        selected = external / 'obsidian-vault/.obsidian/app.json'
        data = json.loads(selected.read_text())
        data['showLineNumber'] = False
        selected.write_text(json.dumps(data, indent=2) + '\n')
        before = (self.home / configure.OBSIDIAN_TEMPLATE_PATH / '.obsidian/app.json').read_bytes()
        self.apply(external)
        configure.verify(self.home, with_claude=True, config_dir=external)
        backups = list((self.home / '.config/1bite/backups/obsidian-vault').glob('app.json.backup-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), before)
        managed = self.home / configure.OBSIDIAN_TEMPLATE_PATH
        self.assertEqual({str(path.relative_to(managed)) for path in managed.rglob('*') if path.is_file()},
                         set(configure.obsidian_template_files(external)))

    def test_obsidian_unknown_or_symlinked_managed_entries_fail_before_writes(self):
        self.apply()
        managed = self.home / configure.OBSIDIAN_TEMPLATE_PATH
        unknown = managed / 'personal-note.md'
        unknown.write_text('keep me\n')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'unknown entry'):
            self.apply()
        self.assertEqual(self.snapshot(), before)
        unknown.unlink()
        app = managed / '.obsidian/app.json'
        app.unlink()
        app.symlink_to(self.home / 'elsewhere')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.apply()
        self.assertEqual(self.snapshot(), before)

    def test_fresh_install_and_repeat_are_identical(self):
        self.apply()
        before = self.snapshot()
        self.apply()
        self.assertEqual(before, self.snapshot())
        configure.verify(self.home, with_claude=True)
        for path in ('.claude/settings.json', '.codex/config.toml', '.kiro/settings/permissions.yaml'):
            self.assertEqual((self.home / path).stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.home / '.codex/auth.json').exists())

    def test_git_defaults_global_ignore_repair_and_privacy_boundary(self):
        defaults = configure.validate_git_defaults((ROOT / 'config/git-defaults.json').read_text())
        self.assertFalse({key.split('.', 1)[0].lower() for key in defaults} & configure.GIT_PRIVATE_SECTIONS)
        self.apply()
        values = configure.git_values(self.home)
        self.assertTrue(all(key.lower() in values for key in defaults))
        self.assertFalse({'user.name', 'user.email', 'credential.helper'} & values.keys())
        ignore = self.home / configure.GIT_IGNORE_PATH
        self.assertEqual(ignore.read_bytes(), (ROOT / 'config/gitignore-global').read_bytes())
        self.assertEqual(self.git_config('--path', '--get', 'core.excludesFile').stdout.strip(), str(ignore))
        self.git_config('--unset-all', 'alias.st')
        with self.assertRaisesRegex(ValueError, 'alias.st'):
            configure.verify(self.home, with_claude=True)
        self.apply()
        configure.verify(self.home, with_claude=True)
        self.assertEqual(self.git_config('--get', 'alias.st').stdout.strip(), defaults['alias.st'])

    def test_git_existing_identity_credentials_alias_and_ignore_are_preserved(self):
        personal_ignore = self.home / '.gitignore-private'
        personal_ignore.write_text('private.cache\n')
        personal = ('[user]\n\tname = Private User\n\temail = private@example.invalid\n'
                    '[credential]\n\thelper = private-helper\n'
                    '[url "ssh://private.invalid/"]\n\tinsteadOf = private:\n'
                    '[alias]\n\tst = status --porcelain=v2\n'
                    '[core]\n\texcludesFile = ~/.gitignore-private\n')
        (self.home / '.gitconfig').write_text(personal)
        self.apply()
        self.assertEqual(self.git_config('--get', 'user.name').stdout.strip(), 'Private User')
        self.assertEqual(self.git_config('--get', 'user.email').stdout.strip(), 'private@example.invalid')
        self.assertEqual(self.git_config('--get', 'credential.helper').stdout.strip(), 'private-helper')
        self.assertEqual(self.git_config('--get', 'url.ssh://private.invalid/.insteadof').stdout.strip(), 'private:')
        self.assertEqual(self.git_config('--get', 'alias.st').stdout.strip(), 'status --porcelain=v2')
        self.assertEqual(self.git_config('--path', '--get', 'core.excludesFile').stdout.strip(), str(personal_ignore))
        self.assertEqual(personal_ignore.read_text(), 'private.cache\n')
        self.assertFalse((self.home / configure.GIT_IGNORE_PATH).exists())
        backups = list((self.home / '.config/1bite/backups').glob('gitconfig.backup-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), personal)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
        before = self.snapshot()
        self.apply()
        configure.verify(self.home, with_claude=True)
        self.assertEqual(self.snapshot(), before)

    def test_personal_configs_auth_and_shell_are_preserved(self):
        files = {'.claude/settings.json': '{"env":{"PERSONAL_SETTING":"yes"}}\n',
                 '.codex/config.toml': 'model = "personal-choice"\n',
                 '.codex/auth.json': '{"existing":"credential"}\n',
                 '.kiro/settings/permissions.yaml': 'rules:\n  - capability: shell\n    effect: allow\n',
                 '.kiro/auth.json': '{"existing":"credential"}\n',
                 '.zshrc': 'export PERSONAL=yes\n', '.zprofile': '# personal profile\n',
                 '.vimrc': 'set ignorecase\n'}
        for name, text in files.items():
            target = self.home / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        self.apply()
        for name, text in files.items():
            if name in ('.zshrc', '.zprofile', '.vimrc'):
                self.assertTrue((self.home / name).read_text().startswith(text))
                backups = list(self.home.glob(name + '.backup-*'))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_text(), text)
            else:
                self.assertEqual((self.home / name).read_text(), text)
        before = self.snapshot()
        self.apply()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual((self.home / '.vimrc').read_text().splitlines().count(configure.VIM_SOURCE_LINE), 1)

    def test_configuration_prints_zsh_ownership_and_restart_guidance(self):
        (self.home / '.zshrc').write_text('alias personal="printf personal"\n')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            configure.configure(self.home, ROOT / 'config')
        text = output.getvalue()
        self.assertIn('Zsh review: preserved existing non-empty', text)
        self.assertIn('.zshrc.backup-*', text)
        self.assertIn('Zsh entry files remain user-owned:', text)
        self.assertIn('Managed settings live separately under ~/.config/1bite/zsh/', text)
        self.assertIn('Restart a non-iTerm shell safely with: exec zsh', text)
        self.assertIn('quit and reopen the app', text)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            configure.configure(self.home, ROOT / 'config')
        self.assertIn('Zsh entry unchanged:', output.getvalue())

    def test_unrecognized_one_bite_loader_requires_manual_merge_before_writes(self):
        zshrc = self.home / '.zshrc'
        zshrc.write_text('if [[ -r "$HOME/.config/1bite/shell.zsh" ]]; then source "$HOME/.config/1bite/shell.zsh"; fi\n')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, r'line 1 looks like an unrecognized One Bite loader.*Expected line'):
            self.apply()
        self.assertEqual(self.snapshot(), before)

    def test_recognized_shell_loader_variants_update_without_touching_surrounding_content(self):
        zshrc = self.home / '.zshrc'
        zprofile = self.home / '.zprofile'
        vimrc = self.home / '.vimrc'
        zshrc.write_text('export BEFORE=yes\nsource ~/.config/1bite/shell.zsh\nexport AFTER=yes\n')
        zprofile.write_text('# profile before\n. "$HOME/.config/1bite/env.zsh"\n# profile after\n')
        vimrc.write_text('set ignorecase\n' + configure.VIM_SOURCE_LINE + '\nset cursorline\n')
        before_zshrc, before_zprofile = zshrc.read_text(), zprofile.read_text()
        self.apply()
        self.assertEqual(zshrc.read_text(),
                         'export BEFORE=yes\n' + configure.SOURCE_LINE + '\nexport AFTER=yes\n')
        self.assertEqual(zprofile.read_text(),
                         '# profile before\n' + configure.ENV_SOURCE_LINE + '\n# profile after\n')
        self.assertEqual(vimrc.read_text(),
                         'set ignorecase\n' + configure.VIM_SOURCE_LINE + '\nset cursorline\n')
        self.assertEqual(next(self.home.glob('.zshrc.backup-*')).read_text(), before_zshrc)
        self.assertEqual(next(self.home.glob('.zprofile.backup-*')).read_text(), before_zprofile)
        self.assertFalse(list(self.home.glob('.vimrc.backup-*')))
        snapshot = self.snapshot()
        self.apply()
        self.assertEqual(self.snapshot(), snapshot)

    def test_duplicate_recognized_shell_loaders_collapse_but_similar_personal_lines_remain(self):
        personal = 'echo "$HOME/.config/1bite/shell.zsh"\n'
        (self.home / '.zshrc').write_text('source ~/.config/1bite/shell.zsh\n' + personal
                                          + '. "$HOME/.config/1bite/shell.zsh"\n')
        self.apply()
        rows = (self.home / '.zshrc').read_text().splitlines()
        self.assertEqual(rows.count(configure.SOURCE_LINE), 1)
        self.assertIn(personal.strip(), rows)

    def test_vim_template_loads_core_defaults(self):
        executable = shutil.which('vim')
        if not executable:
            self.skipTest('vim is unavailable')
        self.apply()
        result_file = self.home / 'vim-options.txt'
        expression = "call writefile([string(&number), string(&expandtab), string(&shiftwidth), " \
                     "string(&tabstop), string(&modelines), string(&swapfile)], " \
                     + json.dumps(str(result_file)) + ")"
        result = subprocess.run([executable, '-Nu', str(self.home / '.vimrc'), '-es', '-i', 'NONE',
                                 '-c', expression, '-c', 'qall!'], capture_output=True, text=True,
                                env={**os.environ, 'HOME': str(self.home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result_file.read_text().splitlines(), ['1', '1', '4', '4', '0', '0'])

    def test_kiro_policy_reporting_and_missing_empty_or_symlink_rejection(self):
        self.apply()
        self.assertEqual(configure.kiro_policy_status(self.home), 'default-ask')
        policy = self.home / configure.KIRO_PATH
        policy.write_text('rules:\n  - capability: shell\n    effect: allow\n')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            configure.configure(self.home, ROOT / 'config')
            configure.verify(self.home, with_claude=True)
        self.assertIn('not audited', output.getvalue())
        self.assertEqual(configure.kiro_policy_status(self.home), 'custom-unreviewed')
        policy.write_text('   \n')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.snapshot(), before)
        policy.unlink()
        with self.assertRaises(FileNotFoundError):
            configure.verify(self.home, with_claude=True)
        for path in (policy, policy.parent, policy.parent.parent):
            with self.subTest(path=path):
                if path.is_dir():
                    path.rmdir()
                path.symlink_to(self.home / 'missing')
                with self.assertRaises(ValueError):
                    self.apply()
                with self.assertRaises(ValueError):
                    configure.verify(self.home, with_claude=True)
                path.unlink()

    def test_kiro_external_rule_contract(self):
        capabilities = ('all', 'builtin', 'filesystem', 'fs_read', 'fs_write', 'shell', 'web_fetch',
                        'web_search', 'mcp', 'subagent', 'skill', 'power', 'context', 'diagnostics', 'sandbox_network')
        for capability in capabilities:
            for effect in ('ask', 'deny', 'allow'):
                configure.validate_kiro(json.dumps({'rules': [dict(capability=capability, effect=effect,
                                                                 match=['*'], exclude=['example'])]}))
        invalid = [None, [], {}, {'rules': []}, {'rules': {}}, {'rules': [], 'extra': True}]
        rules = [None, {}, {'capability': 'all'}, {'effect': 'ask'},
                 {'capability': [], 'effect': 'ask'}, {'capability': 'unknown', 'effect': 'ask'},
                 {'capability': 'all', 'effect': []}, {'capability': 'all', 'effect': 'trust'},
                 {'capability': 'all', 'effect': 'ask', 'extra': True}]
        for key in ('match', 'exclude'):
            rules += [dict(capability='all', effect='ask', **{key: value})
                      for value in (None, '*', [], [''], [1])]
        invalid += [{'rules': [rule]} for rule in rules]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                configure.validate_kiro(json.dumps(value))

    def test_invalid_external_config_does_not_write(self):
        external = self.home / 'external'
        shutil.copytree(ROOT / 'config', external)
        for name, invalid in [('claude-settings.json', '[]'),
                              ('codex-config.toml', 'bad = ['),
                              ('kiro-permissions.json', '{}'), ('iterm2-profile.json', '{}'), ('vscode-settings.json', '[]')]:
            with self.subTest(name=name):
                path = external / name
                original = path.read_text()
                path.write_text(invalid)
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    self.apply(external)
                self.assertEqual(self.snapshot(), before)
                path.write_text(original)

    def test_external_templates_and_existing_invalid_config(self):
        external = self.home / 'external'
        shutil.copytree(ROOT / 'config', external)
        (external / 'codex-config.toml').write_text('model_reasoning_effort = "high"\n')
        self.apply(external)
        self.assertEqual((self.home / '.codex/config.toml').read_text(), 'model_reasoning_effort = "high"\n')
        (self.home / '.claude/settings.json').write_text('{bad')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.snapshot(), before)

    def test_symlink_is_not_replaced(self):
        target = self.home / 'personal'
        target.write_text('# keep me\n')
        (self.home / '.zshrc').symlink_to(target)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, r'dotfile-manager symlink.*Add this exact line.*\.config/1bite/shell\.zsh'):
            self.apply()
        self.assertEqual(self.snapshot(), before)
        self.assertTrue((self.home / '.zshrc').is_symlink())

    def test_vimrc_symlink_is_not_replaced(self):
        target = self.home / 'personal-vimrc'
        target.write_text('set nonumber\n')
        (self.home / '.vimrc').symlink_to(target)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(target.read_text(), 'set nonumber\n')
        self.assertTrue((self.home / '.vimrc').is_symlink())

    def test_vim_verify_rejects_symlink_entry_and_managed_files(self):
        self.apply()
        for index, relative in enumerate(('.vimrc', '.config/1bite/vimrc')):
            with self.subTest(relative=relative):
                path = self.home / relative
                content = path.read_bytes()
                target = self.home / f'vim-target-{index}'
                target.write_bytes(content)
                path.unlink()
                path.symlink_to(target)
                with self.assertRaisesRegex(ValueError, 'symlinks'):
                    configure.verify(self.home, with_claude=True)
                path.unlink()
                path.write_bytes(content)

    def test_managed_file_update_keeps_backup(self):
        self.apply()
        path = self.home / '.config/1bite/shell.zsh'
        path.write_text('# old managed content\n')
        self.apply()
        backups = list(path.parent.glob('shell.zsh.backup-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), '# old managed content\n')
        module = self.home / '.config/1bite/zsh/development.zsh'
        module.write_text('# old managed module\n')
        self.apply()
        backups = list(module.parent.glob('development.zsh.backup-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), '# old managed module\n')
        self.assertEqual(module.read_bytes(), (ROOT / 'config/zsh/development.zsh').read_bytes())
        vim = self.home / '.config/1bite/vimrc'
        vim.write_text('" old managed vim content\n')
        self.apply()
        backups = list(vim.parent.glob('vimrc.backup-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), '" old managed vim content\n')

    def test_managed_zsh_modules_are_required_and_symlinks_are_rejected(self):
        self.apply()
        module = self.home / '.config/1bite/zsh/tools.zsh'
        content = module.read_bytes()
        module.unlink()
        with self.assertRaisesRegex(ValueError, 'zsh/tools.zsh'):
            configure.verify(self.home, with_claude=True)
        module.write_bytes(content)
        target = self.home / 'personal-tools.zsh'
        target.write_bytes(content)
        module.unlink()
        module.symlink_to(target)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.apply()
        self.assertEqual(self.snapshot(), before)

    def test_iterm_updates_keep_backups_and_temporary_files_outside_watched_folder(self):
        self.apply()
        profile = self.home / configure.PROFILE_PATH
        old = profile.read_bytes()
        artifact = profile.with_name(profile.name + '.backup-review')
        artifact.write_bytes(old)
        with self.assertRaisesRegex(ValueError, 'DynamicProfiles'):
            configure.verify(self.home, with_claude=True)
        stale = profile.with_name('.' + profile.name + '12345678')
        stale.write_text('{incomplete')
        before = (artifact.read_bytes(), artifact.stat().st_mtime_ns, artifact.stat().st_mode)
        profile.write_text(old.decode().replace('"Unlimited Scrollback": true', '"Unlimited Scrollback": false'))
        original = configure.tempfile.mkstemp
        watched = []

        def create(*args, **kwargs):
            result = original(*args, **kwargs)
            watched.extend(p.name for p in profile.parent.iterdir() if p.is_file() and p != profile)
            return result

        with mock.patch.object(configure.tempfile, 'mkstemp', side_effect=create):
            self.apply()
        self.assertEqual(watched, [])
        backup_dir = self.home / configure.PROFILE_BACKUP_PATH
        moved = backup_dir / artifact.name
        self.assertEqual((moved.read_bytes(), moved.stat().st_mtime_ns, moved.stat().st_mode), before)
        self.assertEqual((backup_dir / stale.name).read_text(), '{incomplete')
        self.assertEqual(len(list(backup_dir.glob(profile.name + '.backup-*'))), 2)
        self.assertEqual(profile.read_bytes(), old)
        self.assertEqual([p.name for p in profile.parent.iterdir()], [profile.name])
        snapshot = self.snapshot()
        timestamp = profile.stat().st_mtime_ns
        self.apply()
        self.assertEqual(self.snapshot(), snapshot)
        self.assertEqual(profile.stat().st_mtime_ns, timestamp)

    def test_iterm_backup_symlinks_and_collisions_are_rejected_before_writes(self):
        self.apply()
        profile = self.home / configure.PROFILE_PATH
        artifact = profile.with_name(profile.name + '.backup-review')
        artifact.symlink_to(profile)
        before = profile.read_bytes()
        with self.assertRaises(ValueError):
            self.apply()
        artifact.unlink()
        backup_dir = self.home / configure.PROFILE_BACKUP_PATH
        artifact.write_bytes(before)
        (backup_dir / artifact.name).write_bytes(b'previous backup')
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(artifact.read_bytes(), before)
        self.assertEqual((backup_dir / artifact.name).read_bytes(), b'previous backup')
        self.assertEqual(profile.read_bytes(), before)

    def test_entire_keyboard_contract_in_real_zsh(self):
        shell = ROOT / 'config/shell.zsh'
        # Each declared binding must be active in a real interactive Zsh.
        commands = [line for line in (ROOT / 'config/zsh/options.zsh').read_text().splitlines()
                    if line.startswith("bindkey '")]
        self.assertEqual(len(commands), 13)
        for command in commands:
            sequence, widget = command[len('bindkey '):].rsplit(' ', 1)
            result = subprocess.run(['zsh', '-fic', f'source "$1"; bindkey {sequence}',
                                     'test', str(shell)], text=True, capture_output=True, check=True,
                                     env={**os.environ, 'HOME': str(self.home), 'ZSH': str(self.home / '.oh-my-zsh')})
            self.assertEqual(result.stdout.strip().split()[-1], widget)
            self.assertEqual(result.stderr, '')
        profile = json.loads((ROOT / 'config/iterm2-profile.json').read_text())['Profiles'][0]
        self.assertEqual(profile['Guid'], '84911aa0-4114-494c-a17c-6a2ef38b5b34')
        self.assertNotEqual(profile['Guid'], '703f9b42-2cc7-4a89-8e5e-887014d02daa')
        self.assertNotIn('Default Bookmark', profile)
        self.assertEqual(profile['Normal Font'], 'MesloLGSNF-Regular 13')
        self.assertEqual(profile['Non Ascii Font'], 'MesloLGSNF-Regular 13')
        self.assertFalse(profile['Use Non-ASCII Font'])
        self.assertIs(profile['Unlimited Scrollback'], True)
        self.assertEqual(profile['Scrollback Lines'], 0)
        self.assertIs(profile['Mouse Reporting'], True)
        self.assertEqual(profile['Terminal Type'], 'xterm-256color')
        self.assertEqual(set(profile['Keyboard Map']), {
            '0xf702-0x240000', '0xf703-0x240000', '0xf702-0x280000', '0xf703-0x280000',
            '0xf702-0x300000', '0xf703-0x300000', '0xf729-0x0', '0xf72b-0x0', '0x7f-0x80000'})

    def test_fzf_zsh_integration_supports_current_and_legacy_interfaces(self):
        tools = ROOT / 'config/zsh/tools.zsh'
        for modern in (False, True):
            with self.subTest(modern=modern), tempfile.TemporaryDirectory(prefix='fzf-shell-') as directory:
                version = Path(directory) / 'fzf/fixture'
                binary = version / 'bin/fzf'
                binary.parent.mkdir(parents=True)
                binary.write_text("""#!/bin/sh
if [ "$1" = --zsh ]; then
""" + ("""cat <<'EOF'
typeset -g FZF_TEST_SOURCE=modern
function fzf-history-widget { :; }
zle -N fzf-history-widget
bindkey '^R' fzf-history-widget
EOF
exit 0
""" if modern else """exit 2
""") + """fi
exit 0
""")
                binary.chmod(0o755)
                shell = version / 'shell'
                if not modern:
                    shell.mkdir()
                    (shell / 'completion.zsh').write_text('typeset -g FZF_TEST_COMPLETION=legacy\n')
                    (shell / 'key-bindings.zsh').write_text(
                        "typeset -g FZF_TEST_SOURCE=legacy\n"
                        "function fzf-history-widget { :; }\n"
                        "zle -N fzf-history-widget\n"
                        "bindkey '^R' fzf-history-widget\n")
                env = {**os.environ, 'PATH': str(binary.parent) + ':/usr/bin:/bin'}
                runtime = Path(directory) / 'runtime'
                runtime.mkdir()
                with mock.patch.dict(os.environ, env, clear=True):
                    runtime_smoke.check_fzf(runtime, tools)


class InstallerTests(unittest.TestCase):
    def run_shell(self, script, env=None, cwd=None):
        with tempfile.TemporaryDirectory(prefix='setup-shell-state-') as state:
            shell_env = {key: value for key, value in os.environ.items()
                         if not key.startswith(('GIT_', 'HOMEBREW_GIT'))
                         and key not in ('HOMEBREW_PREFIX', 'HOMEBREW_FORCE_BREWED_GIT')}
            shell_env.update(HOMEBREW_PREFIX=state + '/brew', GIT_CONFIG_GLOBAL=state + '/global',
                             GIT_CONFIG_SYSTEM=state + '/system', XDG_CONFIG_HOME=state + '/xdg')
            shell_env.update(env or {})
            shell_env['TEST_STATE'] = state
            guard = 'python3() { echo "Unexpected Python installer invocation in shell test" >&2; return 99; }; '
            return subprocess.run(['bash', '-c', 'source "$1"; ' + guard + script, 'test', str(ROOT / '1bite')],
                                  input='', text=True, capture_output=True, cwd=cwd,
                                  env=shell_env)

    def test_complete_package_iteration_survives_stdin_consumers(self):
        result = self.run_shell("""
WITH_CLAUDE=true
ensure_formula() { cat >/dev/null; echo "CHECK formula:$1"; }
ensure_cask() { cat >/dev/null; echo "CHECK cask:$1"; }
ensure_font_cask() { cat >/dev/null; echo "CHECK font:$1"; }
git() { :; }
ensure_git_lfs_filters() { :; }
install_packages
""")
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = ['CHECK formula:' + name for name in (ROOT / 'config/formulae.txt').read_text().split()]
        expected += ['CHECK cask:' + line.split('\t')[0] for line in (ROOT / 'config/casks.tsv').read_text().splitlines()]
        expected += ['CHECK font:' + line.split('\t')[0] for line in (ROOT / 'config/font-casks.tsv').read_text().splitlines()]
        self.assertEqual([line for line in result.stdout.splitlines() if line.startswith('CHECK ')], expected)

    def test_formula_skip_install_update_and_repair(self):
        for installed, healthy, update, operation in [
            ('false', 'false', 'false', 'install'), ('true', 'true', 'false', None),
            ('true', 'true', 'true', 'upgrade'), ('true', 'false', 'false', 'reinstall')]:
            with self.subTest(operation=operation):
                result = self.run_shell(f'INSTALLED={installed}; HEALTHY={healthy}; UPDATE={update}; ' + """
brew() { if [[ "$1" == list ]]; then [[ "$INSTALLED" == true ]]; else touch "$TEST_STATE/healthy"; echo "MUTATE $*"; fi; }
probe_formula() { [[ "$HEALTHY" == true || -f "$TEST_STATE/healthy" ]]; }
ensure_formula go
echo "ACTION $STEP_ACTION"
""")
                self.assertEqual(result.returncode, 0, result.stderr)
                if operation:
                    self.assertIn(f'MUTATE {operation} --formula homebrew/core/go', result.stdout)
                else:
                    self.assertNotIn('MUTATE', result.stdout)
                    self.assertIn('ACTION skipped', result.stdout)

    def test_neofetch_preserves_healthy_command_and_installs_only_verified_release(self):
        healthy = self.run_shell(
            'neofetch() { echo "Neofetch 7.1.0"; return 1; }; ensure_neofetch; echo "$STEP_ACTION"')
        self.assertEqual(healthy.returncode, 0, healthy.stderr)
        self.assertIn('Preserving healthy neofetch', healthy.stdout)
        self.assertTrue(healthy.stdout.rstrip().endswith('preserved'))

        with tempfile.TemporaryDirectory(prefix='neofetch-home-') as directory:
            env = {**os.environ, 'HOME': directory, 'PATH': str(Path(directory) / '.local/bin') + ':' + os.environ['PATH']}
            script = r'''
command() {
  if [[ "$1" == -v && "$2" == neofetch ]]; then
    if [[ -x "$HOME/.local/bin/neofetch" ]]; then echo "$HOME/.local/bin/neofetch"; return 0; fi
    return 1
  fi
  builtin command "$@"
}
source_url() { echo https://official.invalid/neofetch; }
source_digest() { printf 'a%.0s' {1..64}; echo; }
curl() {
  local output=
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == -o ]]; then output=$2; shift 2; else shift; fi
  done
  printf '#!/bin/bash\necho "Neofetch 7.1.0"\nexit 1\n' >"$output"
}
shasum() { printf 'a%.0s' {1..64}; echo "  $3"; }
ensure_neofetch
echo "ACTION $STEP_ACTION"
'''
            installed = self.run_shell(script, env=env)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            target = Path(directory) / '.local/bin/neofetch'
            self.assertTrue(target.stat().st_mode & 0o111)
            self.assertIn('ACTION installed', installed.stdout)

            other = Path(directory) / 'other'
            failed = self.run_shell(script.replace("printf 'a%.0s' {1..64}; echo \"  $3\"", "printf 'b%.0s' {1..64}; echo \"  $3\""), env={
                **env, 'HOME': str(other), 'PATH': str(other / '.local/bin') + ':' + os.environ['PATH']})
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn('checksum mismatch', failed.stderr)
            self.assertFalse((Path(directory) / 'other/.local/bin/neofetch').exists())

    def test_cask_skip_update_repair_and_preserve(self):
        for managed, healthy, update, operation in [
            ('true', 'true', 'false', None), ('true', 'true', 'true', 'upgrade'),
            ('true', 'false', 'false', 'reinstall'), ('false', 'true', 'true', None),
            ('false', 'false', 'false', 'install')]:
            with self.subTest(managed=managed, operation=operation):
                result = self.run_shell(f'MANAGED={managed}; HEALTHY={healthy}; UPDATE={update}; ' + """
brew() { if [[ "$1" == list ]]; then [[ "$MANAGED" == true ]]; else touch "$TEST_STATE/healthy"; echo "MUTATE $*"; fi; }
app_healthy() { [[ "$HEALTHY" == true || -f "$TEST_STATE/healthy" ]]; }
ensure_cask example Never-Existing-Setup-Test-Example.app
""")
                self.assertEqual(result.returncode, 0, result.stderr)
                if operation:
                    self.assertIn(f'MUTATE {operation} --cask homebrew/cask/example', result.stdout)
                else:
                    self.assertNotIn('MUTATE', result.stdout)

    def test_font_cask_skip_update_repair_and_preserve(self):
        for managed, healthy, update, operation, action in [
            ('true', 'true', 'false', None, 'skipped'),
            ('true', 'true', 'true', 'upgrade', 'update-checked'),
            ('true', 'false', 'false', 'reinstall', 'repaired'),
            ('false', 'true', 'true', None, 'preserved'),
            ('false', 'false', 'false', 'install', 'installed'),
        ]:
            with self.subTest(managed=managed, healthy=healthy, operation=operation):
                result = self.run_shell(f'MANAGED={managed}; HEALTHY={healthy}; UPDATE={update}; ' + r'''
brew() {
  if [[ "$1" == list ]]; then [[ "$MANAGED" == true ]];
  else touch "$TEST_STATE/healthy"; echo "MUTATE $*"; fi
}
font_cask_healthy() { [[ "$HEALTHY" == true || -f "$TEST_STATE/healthy" ]]; }
ensure_font_cask font-example ExampleNerdFont-Regular.ttf
echo "ACTION $STEP_ACTION"
''')
                self.assertEqual(result.returncode, 0, result.stderr)
                if operation:
                    self.assertIn(f'MUTATE {operation} --cask homebrew/cask/font-example', result.stdout)
                else:
                    self.assertNotIn('MUTATE', result.stdout)
                self.assertIn('ACTION ' + action, result.stdout)

    def test_ai_installation_dispatch_skips_healthy_and_propagates_failure(self):
        commands = ('check_agent claude', 'check_agent codex',
                    'ensure_cask chatgpt ChatGPT.app', 'ensure_cask kiro Kiro.app',
                    "ensure_cask kiro-cli 'Kiro CLI.app'")
        for command in commands:
            for healthy, update, status in [('true', 'false', 0), ('false', 'false', 0),
                                            ('true', 'true', 0), ('false', 'true', 23)]:
                with self.subTest(command=command, healthy=healthy, update=update, status=status):
                    result = self.run_shell(f'DESKTOP_MODE=managed; HEALTHY={healthy}; UPDATE={update}; STATUS={status}; ' + """
brew() { echo WRONG >&2; return 99; }
npm() { echo WRONG >&2; return 99; }
app_path() { printf '/Applications/%s\n' "$1"; }
agent_healthy() { [[ "$HEALTHY" == true || -f "$TEST_STATE/healthy" ]]; }
app_healthy() { agent_healthy; }
claude() { echo claude-version; }
codex() { echo codex-version; }
python3() { echo "OFFICIAL $*" >&2; touch "$TEST_STATE/healthy"; echo installed; return "$STATUS"; }
""" + command + '; echo "ACTION $STEP_ACTION"')
                    self.assertEqual(result.returncode, status, result.stderr)
                    self.assertNotIn('WRONG', result.stdout + result.stderr)
                    if healthy == 'true' and update == 'false':
                        self.assertNotIn('OFFICIAL', result.stderr)
                        self.assertIn('ACTION preserved', result.stdout)
                    else:
                        self.assertIn('official_ai.py', result.stderr)
                        self.assertEqual('--update' in result.stderr, update == 'true')
                        self.assertEqual('--healthy' in result.stderr, healthy == 'true')
                    if status:
                        self.assertNotIn('ACTION', result.stdout)

    def test_default_desktops_preserve_healthy_apps_and_prepare_missing_ones(self):
        for healthy in ('true', 'false'):
            result = self.run_shell(f'DESKTOP_MODE=download; HEALTHY={healthy}; ' + """
app_healthy() { [[ "$HEALTHY" == true ]]; }
brew() { echo WRONG; return 91; }
python3() { echo "DOWNLOAD $*" >&2; echo prepared; }
ensure_cask chatgpt ChatGPT.app
echo "ACTION $STEP_ACTION; MANUAL $MANUAL_STEPS"
""")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('WRONG', result.stdout)
            if healthy == 'true':
                self.assertNotIn('DOWNLOAD', result.stderr)
                self.assertIn('ACTION preserved', result.stdout)
            else:
                self.assertIn('desktop.py chatgpt', result.stderr)
                self.assertIn('ACTION prepared; MANUAL  chatgpt', result.stdout)

    def test_default_kiro_uses_vendor_installer_without_managed_hooks(self):
        result = self.run_shell("""
DESKTOP_MODE=download
app_healthy() { [[ -f "$TEST_STATE/healthy" ]]; }
download_installer() { echo "DOWNLOAD $1"; }
run_package_installer() { echo "VENDOR $1"; touch "$TEST_STATE/healthy"; }
python3() { echo WRONG; return 91; }
agent_healthy() { return 1; }
ensure_cask kiro-cli 'Kiro CLI.app'
ensure_kiro_shell
echo "MANUAL $MANUAL_STEPS"
""")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('DOWNLOAD kiro-cli', result.stdout)
        self.assertIn('VENDOR /bin/bash', result.stdout)
        self.assertIn('kiro-cli-onboarding', result.stdout)
        self.assertNotIn('WRONG', result.stdout)

    def test_failures_do_not_continue(self):
        for script in [
            'brew() { return 1; }; ensure_formula go',
            'agent_healthy() { return 1; }; brew() { return 1; }; npm() { return 1; }; '
            'python3() { return 23; }; check_agent codex',
            'brew() { return 0; }; probe_formula() { return 1; }; ensure_formula go']:
            result = self.run_shell(script + '; echo WRONG')
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('WRONG', result.stdout)

    def test_homebrew_download_policy_defaults_and_personal_override(self):
        result = self.run_shell('unset HOMEBREW_CURLRC; configure_downloads; '
                                'test "$HOMEBREW_CURLRC" = "$ROOT/config/download.curlrc"; '
                                'bash -c \'test -f "$HOMEBREW_CURLRC"\'')
        self.assertEqual(result.returncode, 0, result.stderr)
        for override in ('/private/custom.curlrc', '1'):
            result = self.run_shell(f'export HOMEBREW_CURLRC={override}; configure_downloads; '
                                    f'test "$HOMEBREW_CURLRC" = {override}')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Preserving', result.stdout)
            self.assertNotIn('/private/custom.curlrc', result.stdout)

    def test_real_curl_policy_downloads_and_aborts_stalled_transfers(self):
        release = threading.Event()

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.flush()
                if self.path == '/stall':
                    release.wait(10)
                else:
                    self.wfile.write(b'OK')

        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = ['curl', '--disable', '--config', str(ROOT / 'config/download.curlrc'),
                    '--silent', '--noproxy', '*', '--retry', '0']
            url = f'http://127.0.0.1:{server.server_port}'
            healthy = subprocess.run([*base, url + '/ok'], capture_output=True, timeout=5)
            self.assertEqual(healthy.returncode, 0, healthy.stderr)
            self.assertEqual(healthy.stdout, b'OK')
            # Shorten the public policy's 60-second stall interval for the test.
            stalled = subprocess.run([*base, '--speed-time', '1', url + '/stall'],
                                     capture_output=True, timeout=5)
            self.assertEqual(stalled.returncode, 28, stalled.stderr)
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_unrelated_tap_warning_does_not_change_trust_or_block_go(self):
        result = self.run_shell('''
INSTALLED=false
brew() {
  case "$1" in
    list) [[ "$INSTALLED" == true ]];;
    install) echo 'Warning: unrelated tap is not trusted' >&2; touch "$TEST_STATE/healthy";;
    *) echo WRONG >&2; return 9;;
  esac
}
probe_formula() { [[ -f "$TEST_STATE/healthy" ]]; }
ensure_formula go
echo "$STEP_ACTION"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'installed')
        self.assertNotIn('WRONG', result.stderr)
        failed = self.run_shell('brew() { if [[ "$1" == list ]]; then return 1; else return 28; fi; }; '
                                'ensure_formula go; echo WRONG')
        self.assertEqual(failed.returncode, 28)
        self.assertNotIn('WRONG', failed.stdout)

    def test_homebrew_refresh_is_explicit(self):
        for update in ('false', 'true'):
            result = self.run_shell(f'UPDATE={update}; ' + '''
export HOMEBREW_ASK=1
xcode-select() { return 0; }
command() { return 0; }
brew() { [[ "$HOMEBREW_NO_ASK" == 1 && -z "${HOMEBREW_ASK+x}" ]] || return 99; echo "MUTATE $*"; }
bootstrap
bash -c '[[ "$HOMEBREW_NO_ASK" == 1 && -z "${HOMEBREW_ASK+x}" ]]'
''')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual('MUTATE update' in result.stdout, update == 'true')

    def test_entire_managed_package_surface_uses_official_names(self):
        formulae = (ROOT / 'config/formulae.txt').read_text().split()
        casks = [line.split('\t')[0] for line in (ROOT / 'config/casks.tsv').read_text().splitlines()
                 if line.split('\t')[0] not in ('chatgpt', 'kiro', 'kiro-cli', 'claude-desktop')]
        for kind, names in [('formula', formulae), ('cask', casks)]:
            for name in names:
                for installed, healthy, update, operation in [
                    ('false', 'false', 'false', 'install'), ('true', 'false', 'false', 'reinstall'),
                    ('true', 'true', 'true', 'upgrade'), ('true', 'true', 'false', 'skip')]:
                    with self.subTest(kind=kind, name=name, operation=operation):
                        prefix = ('' if '/' in name else 'homebrew/core/') if kind == 'formula' else 'homebrew/cask/'
                        script = f'DESKTOP_MODE=managed; INSTALLED={installed}; HEALTHY={healthy}; UPDATE={update}; EXPECTED={prefix}{name}; KIND={kind}; ' + '''
brew() {
  [[ "$2" == "--$KIND" && "$3" == "$EXPECTED" && $# == 3 ]] || return 99
  case "$1" in
    list) [[ "$INSTALLED" == true ]];;
    install|upgrade|reinstall) touch "$TEST_STATE/healthy"; echo "$1";;
    *) return 98;;
  esac
}
probe_formula() { [[ "$HEALTHY" == true || -f "$TEST_STATE/healthy" ]]; }
app_healthy() { [[ "$HEALTHY" == true || -f "$TEST_STATE/healthy" ]]; }
git() { :; }
ensure_git_lfs_filters() { :; }
'''
                        script += (f'ensure_formula {name}' if kind == 'formula' else
                                   f'ensure_cask {name} Never-Existing-Setup-Test-Example.app')
                        result = self.run_shell(script)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stdout.strip(), '' if operation == 'skip' else operation)

    def test_charm_existing_core_channel_and_failures(self):
        for name in ('glow', 'pop', 'gum', 'crush'):
            for healthy, update, operation in [('true', 'false', ''), ('true', 'true', 'upgrade'),
                                               ('false', 'false', 'reinstall')]:
                script = f'HEALTHY={healthy}; UPDATE={update}; CORE=homebrew/core/{name}; ' + """
brew() {
  [[ "$2" == --formula ]] || return 98
  if [[ "$1" == list ]]; then [[ "$3" == "$CORE" ]]; return; fi
  [[ "$3" == "$CORE" ]] || return 99
  echo "$1"
  touch "$TEST_STATE/healthy"
}
probe_formula() { [[ "$HEALTHY" == true || -f "$TEST_STATE/healthy" ]]; }
"""
                result = self.run_shell(script + f'ensure_formula charmbracelet/tap/{name}')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), operation)
            for operation, installed in [('install', 'false'), ('upgrade', 'true'), ('reinstall', 'true')]:
                script = f'INSTALLED={installed}; UPDATE=true; OPERATION={operation}; ' + """
brew() {
  case "$1" in
    list) [[ "$INSTALLED" == true ]];;
    "$OPERATION") return 22;;
    *) return 99;;
  esac
}
probe_formula() { [[ "$OPERATION" != reinstall ]]; }
"""
                result = self.run_shell(script + f'ensure_formula charmbracelet/tap/{name}; echo WRONG')
                self.assertEqual(result.returncode, 22, result.stderr)
                self.assertNotIn('WRONG', result.stdout)

    def test_node_probe_covers_npm_and_npx(self):
        for broken in ('npm', 'npx'):
            with self.subTest(broken=broken):
                result = self.run_shell(
                    f'node() {{ return 0; }}; npm() {{ return 0; }}; npx() {{ return 0; }}; '
                    f'{broken}() {{ return 1; }}; probe_formula node')
                self.assertNotEqual(result.returncode, 0)

    def test_git_lfs_repeat_keeps_global_config_metadata_and_custom_filters(self):
        with tempfile.TemporaryDirectory(prefix='lfs-config-') as directory:
            target = Path(directory) / 'gitconfig'
            prefix = f'export GIT_CONFIG_GLOBAL={shlex.quote(str(target))}; '
            values = {'clean':'git-lfs clean -- %f', 'smudge':'git-lfs smudge -- %f',
                      'process':'git-lfs filter-process', 'required':'true'}
            setup = prefix + '; '.join('git config --global filter.lfs.' + key + ' ' + shlex.quote(value)
                                      for key, value in values.items())
            self.assertEqual(self.run_shell(setup).returncode, 0)
            before = (target.read_bytes(), target.stat().st_mtime_ns)
            result = self.run_shell(prefix + 'ensure_git_lfs_filters; ensure_git_lfs_filters')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((target.read_bytes(), target.stat().st_mtime_ns), before)
            for key in values:
                self.assertEqual(self.run_shell(prefix + 'git config --global filter.lfs.' + key + ' custom').returncode, 0)
                before = (target.read_bytes(), target.stat().st_mtime_ns)
                result = self.run_shell(prefix + 'ensure_git_lfs_filters')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((target.read_bytes(), target.stat().st_mtime_ns), before)
                self.assertEqual(self.run_shell(prefix + 'git config --global filter.lfs.' + key + ' ' + shlex.quote(values[key])).returncode, 0)
            target.unlink()
            result = self.run_shell(prefix + 'git() { if [[ "$1 $2" == "config --list" ]]; then return 0; fi; '
                                    'if [[ "$1" == config ]]; then return 1; fi; echo "INIT $*"; }; ensure_git_lfs_filters')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'INIT lfs install --skip-repo')

    @unittest.skipIf(os.geteuid() == 0, 'root can read mode-000 files')
    def test_unreadable_git_config_stops_before_lfs_and_resumes_without_reinstall(self):
        with tempfile.TemporaryDirectory(prefix='git-permission-') as directory:
            root = Path(directory)
            system = root / 'gitconfig'
            global_config = root / 'global'
            system.write_text('[example]\nvalue = PRIVATE_SYSTEM_VALUE\n')
            global_config.write_text('[example]\nvalue = PRIVATE_GLOBAL_VALUE\n[filter "lfs"]\n'
                                     'clean = git-lfs clean -- %f\nsmudge = git-lfs smudge -- %f\n'
                                     'process = git-lfs filter-process\nrequired = true\n')
            before = (global_config.read_bytes(), global_config.stat().st_mtime_ns, global_config.stat().st_mode)
            env = dict(HOME=directory, XDG_CONFIG_HOME=directory, GIT_CONFIG_SYSTEM=str(system),
                       GIT_CONFIG_GLOBAL=str(global_config), HOMEBREW_PREFIX=directory,
                       LC_ALL='C', NO_COLOR='1')
            managed_git = root / 'opt/git/bin/git'
            managed_git.parent.mkdir(parents=True)
            managed_git.symlink_to(shutil.which('git'))
            prefix = '''
brew() { if [[ "$1" == list ]]; then return 0; fi; echo MUTATION; return 99; }
git() { if [[ "$1" == lfs ]]; then echo MUTATION; return 99; fi; command git "$@"; }
'''
            try:
                system.chmod(0)
                # --version alone incorrectly considers this Git installation healthy.
                healthy = self.run_shell('probe_formula git', env=env, cwd=directory)
                self.assertEqual(healthy.returncode, 0, healthy.stderr)
                for operation in ('step_run formula:git ensure_formula git', 'ensure_git_lfs_filters'):
                    with self.subTest(operation=operation):
                        failed = self.run_shell(prefix + operation + '; echo WRONG', env=env, cwd=directory)
                        self.assertEqual(failed.returncode, 128, failed.stderr)
                        self.assertIn('Permission denied', failed.stderr)
                        self.assertIn('Repair the file named above', failed.stderr)
                        self.assertNotIn('WRONG', failed.stdout)
                        self.assertNotIn('MUTATION', failed.stdout)
                        self.assertNotIn('PRIVATE_', failed.stdout + failed.stderr)
                        self.assertEqual(system.stat().st_mode & 0o777, 0)
            finally:
                system.chmod(0o600)
            resumed = self.run_shell(prefix + 'ensure_formula git; ensure_git_lfs_filters; echo "$STEP_ACTION"',
                                     env=env, cwd=directory)
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertEqual(resumed.stdout.strip(), 'skipped')
            self.assertEqual(resumed.stderr, '')
            self.assertEqual((global_config.read_bytes(), global_config.stat().st_mtime_ns,
                              global_config.stat().st_mode), before)

    @unittest.skipIf(os.geteuid() == 0, 'root can read mode-000 files')
    def test_homebrew_git_config_checked_when_path_git_is_healthy(self):
        with tempfile.TemporaryDirectory(prefix='brew-git-permission-') as directory:
            root = Path(directory)
            system = root / 'brew/etc/gitconfig'
            global_config = root / 'global'
            system.parent.mkdir(parents=True)
            system.write_text('[example]\nvalue = PRIVATE_SYSTEM_VALUE\n')
            global_config.write_text('[example]\nvalue = PRIVATE_GLOBAL_VALUE\n')
            before = (global_config.read_bytes(), global_config.stat().st_mtime_ns,
                      global_config.stat().st_mode)
            real_git = shlex.quote(shutil.which('git'))
            path_git = root / 'path/bin/git'
            brewed_git = root / 'brew/bin/git'
            managed_git = root / 'brew/opt/git/bin/git'
            override_git = root / 'override/git'
            for executable, config in ((path_git, root / 'absent'), (brewed_git, system),
                                       (managed_git, system), (override_git, system)):
                executable.parent.mkdir(parents=True, exist_ok=True)
                executable.write_text('#!/bin/bash\nexport GIT_CONFIG_SYSTEM=' + shlex.quote(str(config)) +
                                      '\nexec ' + real_git + ' "$@"\n')
                executable.chmod(0o755)
            env = dict(HOME=directory, HOMEBREW_PREFIX=str(root / 'brew'),
                       GIT_CONFIG_GLOBAL=str(global_config), LC_ALL='C', NO_COLOR='1',
                       PATH=str(path_git.parent) + os.pathsep + os.environ['PATH'])
            mutation = root / 'brew-called'
            stub = 'brew() { if [[ "$1" == list ]]; then return 0; fi; touch ' + shlex.quote(str(mutation)) + '; }; '
            try:
                system.chmod(0)
                healthy = self.run_shell('git config --list >/dev/null; probe_formula git',
                                         env=env, cwd=directory)
                self.assertEqual(healthy.returncode, 0, healthy.stderr)
                for operation in ('step_run formula:git ensure_formula git', 'ensure_git_lfs_filters',
                                  'run_package_installer brew install --formula charmbracelet/tap/glow'):
                    with self.subTest(operation=operation):
                        failed = self.run_shell(stub + operation + '; echo WRONG', env=env, cwd=directory)
                        self.assertEqual(failed.returncode, 128, failed.stderr)
                        self.assertIn('Permission denied', failed.stderr)
                        self.assertIn('using ' + str(brewed_git), failed.stderr)
                        self.assertNotIn('PRIVATE_', failed.stdout + failed.stderr)
                        self.assertNotIn('WRONG', failed.stdout)
                        self.assertFalse(mutation.exists())
                # Also check keg-only Git and an explicit Homebrew Git override.
                brewed_git.unlink()
                failed = self.run_shell('check_git_configuration', env=env, cwd=directory)
                self.assertEqual(failed.returncode, 128, failed.stderr)
                self.assertIn('using ' + str(managed_git), failed.stderr)
                managed_git.unlink()
                failed = self.run_shell('check_git_configuration',
                                        env={**env, 'HOMEBREW_GIT_PATH': str(override_git)}, cwd=directory)
                self.assertEqual(failed.returncode, 128, failed.stderr)
                self.assertIn('using ' + str(override_git), failed.stderr)
                brewed_git.symlink_to(override_git)
                managed_git.symlink_to(override_git)
            finally:
                system.chmod(0o600)
            resumed = self.run_shell(stub + 'ensure_formula git; echo "$STEP_ACTION"; '
                                     'run_package_installer brew install --formula charmbracelet/tap/glow',
                                     env=env, cwd=directory)
            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertEqual(resumed.stdout.strip(), 'skipped')
            self.assertTrue(mutation.exists())
            mutation.unlink()
            # Recheck immediately before later brew calls even if an earlier check passed.
            try:
                failed = self.run_shell(stub + 'check_git_configuration; chmod 000 ' + shlex.quote(str(system)) +
                                        '; run_package_installer brew install --formula charmbracelet/tap/glow; echo WRONG',
                                        env=env, cwd=directory)
            finally:
                system.chmod(0o600)
            self.assertEqual(failed.returncode, 128, failed.stderr)
            self.assertNotIn('WRONG', failed.stdout)
            self.assertFalse(mutation.exists())
            self.assertEqual((global_config.read_bytes(), global_config.stat().st_mtime_ns,
                              global_config.stat().st_mode), before)

    def test_broken_managed_git_is_repaired_even_when_path_git_is_healthy(self):
        with tempfile.TemporaryDirectory(prefix='brew-git-binary-') as directory:
            root = Path(directory)
            managed_git = root / 'opt/git/bin/git'
            managed_git.parent.mkdir(parents=True)
            linked_git = root / 'bin/git'
            linked_git.parent.mkdir()
            linked_git.symlink_to(managed_git)
            real_git = shutil.which('git')
            for broken in (False, True):
                with self.subTest(broken=broken):
                    if broken:
                        managed_git.write_text('#!/bin/bash\nexit 23\n')
                        managed_git.chmod(0o755)
                    env = {'HOMEBREW_PREFIX': directory, 'REAL_GIT': real_git}
                    self.assertNotEqual(self.run_shell('probe_formula git', env=env).returncode, 0)
                    result = self.run_shell('''
brew() {
  if [[ "$1" == list ]]; then return 0; fi
  [[ "$*" == 'reinstall --formula homebrew/core/git' ]] || return 99
  rm -f "$HOMEBREW_PREFIX/opt/git/bin/git"
  ln -s "$REAL_GIT" "$HOMEBREW_PREFIX/opt/git/bin/git"
  echo REPAIRED
}
ensure_formula git
echo "$STEP_ACTION"
''', env=env)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.splitlines(), ['REPAIRED', 'repaired'])
                    managed_git.unlink()

    def test_git_configuration_probe_accepts_absent_files_and_reports_bad_includes(self):
        with tempfile.TemporaryDirectory(prefix='git-config-') as directory:
            root = Path(directory)
            system = root / 'gitconfig'
            included = root / 'included'
            env = dict(HOME=directory, XDG_CONFIG_HOME=directory, GIT_CONFIG_SYSTEM=str(system),
                       GIT_CONFIG_GLOBAL=str(root / 'global'), LC_ALL='C', NO_COLOR='1')
            result = self.run_shell('check_git_configuration', env=env, cwd=directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout + result.stderr, '')
            system.write_text('[include]\npath = ./included\n')
            included.write_text('[invalid\n')
            result = self.run_shell('check_git_configuration; echo WRONG', env=env, cwd=directory)
            self.assertEqual(result.returncode, 128, result.stderr)
            self.assertIn('/included', result.stderr)
            self.assertIn('Repair the file named above', result.stderr)
            self.assertNotIn('WRONG', result.stdout)

    def test_git_lfs_initialization_failure_stops_its_step(self):
        result = self.run_shell('brew() { return 0; }; probe_formula() { return 0; }; '
                                'git() { if [[ "$1 $2" == "config --list" ]]; then return 0; fi; '
                                'if [[ "$1" == config ]]; then return 1; fi; return 23; }; '
                                'step_run formula:git-lfs ensure_formula git-lfs; echo WRONG')
        self.assertEqual(result.returncode, 23)
        self.assertNotIn('WRONG', result.stdout)

    def test_templates_before_agents_and_optional_extension_progress(self):
        script = """
activate_paths() { :; }
check_install_target() { :; }
network_check() { :; }
bootstrap() { :; }
ensure_formula() { :; }
ensure_cask() { :; }
ensure_font_cask() { :; }
ensure_ohmyzsh() { :; }
ensure_powerlevel10k() { :; }
ensure_neofetch() { :; }
ensure_kiro_shell() { :; }
ensure_extension() { :; }
git() { :; }
ensure_git_lfs_filters() { :; }
apply_configuration() { echo CONFIGURED; }
check_agent() { echo "AGENT $1"; }
verify_installation() { echo VERIFIED; }
prepare_sogou_installer() { echo SOGOU-PREPARED; }
prepare_doubao_input_installer() { echo DOUBAO-PREPARED; }
execute_mode
echo "TOTAL $COMPLETED_STEPS $STEP_TOTAL"
"""
        default_count = (12 + len((ROOT / 'config/formulae.txt').read_text().split())
                         + len((ROOT / 'config/casks.tsv').read_text().splitlines())
                         + len((ROOT / 'config/font-casks.tsv').read_text().splitlines())
                         + len((ROOT / 'config/vscode-extensions.txt').read_text().split()) - 2)
        for enabled in ('false', 'true'):
            for claude in ('false', 'true'):
                result = self.run_shell(f'WITH_SOGOU={enabled}; WITH_CLAUDE={claude}; ' + script)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertLess(result.stdout.index('CONFIGURED'), result.stdout.index('AGENT codex'))
                self.assertEqual('AGENT claude' in result.stdout, claude == 'true')
                self.assertEqual('app:claude-desktop' in result.stdout, claude == 'true')
                if claude == 'true':
                    self.assertLess(result.stdout.index('CONFIGURED'), result.stdout.index('AGENT claude'))
                count = default_count + 2 * (claude == 'true') + (enabled == 'true')
                self.assertIn(f'TOTAL {count} {count}', result.stdout)
                self.assertGreater(result.stdout.index('DOUBAO-PREPARED'), result.stdout.index('VERIFIED'))
                if enabled == 'true':
                    self.assertGreater(result.stdout.index('SOGOU-PREPARED'), result.stdout.index('DOUBAO-PREPARED'))
                else:
                    self.assertNotIn('SOGOU-PREPARED', result.stdout)

    def test_claude_plan_requires_flag_even_with_managed_update_or_internal_environment(self):
        for flags in ('', '--managed-desktop', '--update', '--managed-desktop --update'):
            for selected in (False, True):
                result = self.run_shell('main --plan ' + flags + (' --with-claude' if selected else ''),
                                        env={'ONE_BITE_WITH_CLAUDE': 'true'})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual('claude-desktop\t' in result.stdout, selected)
                self.assertEqual('anthropic\t' in result.stdout, selected)

    def test_chrome_location_selection_and_no_duplicate_installation(self):
        for system, user in [('true', 'false'), ('false', 'true'), ('true', 'true'), ('false', 'false')]:
            script = f'SYSTEM={system}; USER_APP={user}; ' + """
bundle_healthy() {
  if [[ "$1" == '/Applications/Google Chrome.app' ]]; then [[ "$SYSTEM" == true ]];
  elif [[ "$1" == "$HOME/Applications/Google Chrome.app" ]]; then [[ "$USER_APP" == true ]];
  else return 1; fi
}
"""
            result = self.run_shell(script + 'app_path "Google Chrome.app"')
            user_selected = system == 'false' and user == 'true'
            expected = str(Path.home() / 'Applications/Google Chrome.app') if user_selected else '/Applications/Google Chrome.app'
            self.assertEqual(result.stdout.strip(), expected)
            if system == user == 'false':
                continue
            for managed in ('false', 'true'):
                for update in ('false', 'true'):
                    run = self.run_shell(script + f'DESKTOP_MODE=managed; MANAGED={managed}; UPDATE={update}; ' + """
brew() { if [[ "$1" == list ]]; then [[ "$MANAGED" == true ]]; else echo "MUTATE $*"; fi; }
ensure_cask google-chrome 'Google Chrome.app'
echo "ACTION $STEP_ACTION"
""")
                    self.assertEqual(run.returncode, 0, run.stderr)
                    if not user_selected and managed == update == 'true':
                        self.assertIn('MUTATE upgrade --cask homebrew/cask/google-chrome', run.stdout)
                    else:
                        self.assertNotIn('MUTATE', run.stdout)
                        self.assertRegex(run.stdout, r'ACTION (preserved|skipped)')

    def test_obsidian_cask_preserves_a_healthy_user_application(self):
        result = self.run_shell(r'''
bundle_healthy() { [[ "$1" == "$HOME/Applications/Obsidian.app" ]]; }
brew() { echo "WRONG $*"; return 99; }
echo "PATH $(app_path 'Obsidian.app')"
ensure_cask obsidian 'Obsidian.app'
echo "ACTION $STEP_ACTION"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PATH ' + str(Path.home() / 'Applications/Obsidian.app'), result.stdout)
        self.assertIn('ACTION preserved', result.stdout)
        self.assertNotIn('WRONG', result.stdout)

    def test_kiro_locations_versions_identity_and_manager_actions(self):
        for compatible in ('/Applications/Kiro.app', str(Path.home() / 'Applications/Kiro.app')):
            result = self.run_shell('COMPATIBLE=' + shlex.quote(compatible) + '; ' + """
bundle_healthy() { return 0; }
bundle_identifier() { echo dev.kiro.desktop; }
bundle_version() { if [[ "$1" == "$COMPATIBLE" ]]; then echo 1.0.437; else echo 0.9.1; fi; }
app_path Kiro.app
""")
            self.assertEqual(result.stdout.strip(), compatible)
        for system, user in [('true', 'false'), ('false', 'true'), ('true', 'true'), ('false', 'false')]:
            for version in ('0.9.1', '1.0.437', '2.0.0', 'invalid'):
                for identity in ('dev.kiro.desktop', 'other.application'):
                    script = f'SYSTEM={system}; USER_APP={user}; VERSION={version}; IDENTITY={identity}; ' + """
bundle_healthy() {
  if [[ "$1" == /Applications/Kiro.app ]]; then [[ "$SYSTEM" == true ]];
  elif [[ "$1" == "$HOME/Applications/Kiro.app" ]]; then [[ "$USER_APP" == true ]];
  else return 1; fi
}
bundle_version() { echo "$VERSION"; }
bundle_identifier() { echo "$IDENTITY"; }
"""
                    selected_user = system == 'false' and user == 'true'
                    result = self.run_shell(script + 'app_path Kiro.app')
                    expected = str(Path.home() / 'Applications/Kiro.app') if selected_user else '/Applications/Kiro.app'
                    self.assertEqual(result.stdout.strip(), expected)
                    healthy = (system == 'true' or user == 'true') and version[0] in '12' and identity == 'dev.kiro.desktop'
                    result = self.run_shell(script + 'app_healthy Kiro.app')
                    self.assertEqual(result.returncode == 0, healthy, result.stderr)
                    if not healthy and selected_user:
                        result = self.run_shell(script + 'python3() { return 1; }; brew() { echo WRONG; }; ensure_cask kiro Kiro.app')
                        self.assertNotEqual(result.returncode, 0)
                        self.assertNotIn('WRONG', result.stdout)
                    if not healthy:
                        continue
                    for managed in ('true', 'false'):
                        for update in ('true', 'false'):
                            result = self.run_shell(script + f'DESKTOP_MODE=managed; MANAGED={managed}; UPDATE={update}; ' + """
brew() { if [[ "$1" == list ]]; then [[ "$MANAGED" == true ]]; else echo "MUTATE $*"; fi; }
python3() { echo preserved; }
ensure_cask kiro Kiro.app
""")
                            self.assertEqual(result.returncode, 0, result.stderr)
                            self.assertNotIn('MUTATE', result.stdout)
    def test_platform_contract(self):
        for arch, version, uid, accepted in [('arm64', '26.6.2', 501, True), ('arm64', '27.0', 501, True),
                                             ('arm64', '15.7', 501, False), ('x86_64', '26.6.2', 501, False),
                                             ('arm64', '26.6.2', 0, False)]:
            result = self.run_shell(f'uname() {{ echo {arch}; }}; sw_vers() {{ echo {version}; }}; '
                                    f'id() {{ echo {uid}; }}; check_install_target')
            self.assertEqual(result.returncode == 0, accepted)

    def test_cli_invalid_arguments_and_side_effect_free_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'not-created'
            result = subprocess.run([str(ROOT / '1bite'), '--plan', '--log-dir', str(target)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn('https://chatgpt.com/codex/install.sh', result.stdout)
            self.assertIn('prepare the official Doubao Input Method ZIP', result.stdout)
            self.assertNotIn('prepare official Sogou ZIP', result.stdout)
            self.assertFalse(target.exists())
        for args in (['--unknown'], ['--plan', '--verify'], ['--config-dir'], ['--log-dir'], ['--diagnose', '--update'],
                     ['--verify', '--with-sogou'], ['--diagnose', '--with-sogou']):
            result = subprocess.run([str(ROOT / '1bite'), *args], capture_output=True)
            self.assertNotEqual(result.returncode, 0)

    def test_manifest_and_all_formula_probes(self):
        expected = {'git', 'git-lfs', 'gh', 'go', 'node', 'python', 'uv', 'ripgrep', 'duf', 'fd', 'bat',
                    'fzf', 'autojump', 'zoxide', 'jq', 'yq', 'tmux', 'tree', 'git-delta', 'tig', 'lazygit', 'wget',
                    'htop', 'shellcheck', 'shfmt', 'ffmpeg', 'imagemagick', 'fastfetch',
                    'charmbracelet/tap/glow', 'charmbracelet/tap/pop', 'charmbracelet/tap/gum', 'charmbracelet/tap/crush'}
        packages = (ROOT / 'config/formulae.txt').read_text().split()
        self.assertEqual(set(packages), expected)
        self.assertEqual(len(packages), len(expected))
        mapping = {'python': 'python3', 'ripgrep': 'rg', 'git-delta': 'delta', 'imagemagick': 'magick'}
        script = (ROOT / 'scripts/verify.sh').read_text()
        line = next(line for line in script.splitlines() if line.startswith('for executable in '))
        actual = line.removeprefix('for executable in ').removesuffix('; do').split()
        self.assertEqual(set(actual), {mapping.get(p, p.rsplit('/', 1)[-1]) for p in expected}
                         | {'npm', 'npx', 'neofetch', 'ob', 'obn', 'claude', 'codex'})
        for package in packages:
            result = self.run_shell(f'formula_command {package}')
            self.assertEqual(result.stdout.strip(), mapping.get(package, package.rsplit('/', 1)[-1]))



if __name__ == '__main__':
    unittest.main()
