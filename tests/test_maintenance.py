import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('maintenance', ROOT / 'scripts/check-updates.py')
maintenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(maintenance)


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='setup maintenance ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.home = Path(self.temp.name) / 'home'
        shutil.copytree(ROOT / 'config', self.root / 'config')
        shutil.copyfile(ROOT / 'VERSION', self.root / 'VERSION')
        (self.home / '.oh-my-zsh').mkdir(parents=True)
        (self.home / '.oh-my-zsh/custom/themes/powerlevel10k').mkdir(parents=True)
        self.formulae = (self.root / 'config/formulae.txt').read_text().split()
        self.casks = dict(line.split('\t') for line in (self.root / 'config/casks.tsv').read_text().splitlines())
        self.fonts = dict(line.split('\t') for line in (self.root / 'config/font-casks.tsv').read_text().splitlines())
        self.extensions = (self.root / 'config/vscode-extensions.txt').read_text().split()
        self.local = {'formulae': [dict(name=name.rsplit('/', 1)[-1], tap=name.rsplit('/', 1)[0] if '/' in name else 'homebrew/core', linked_keg='1.0.0', installed=[])
                                  for name in self.formulae], 'casks': []}
        for app in self.casks.values():
            directory = self.home / 'Applications' / app / 'Contents'
            directory.mkdir(parents=True)
            (directory / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString': '1.0.0'}))
        for name, filename in self.fonts.items():
            path = self.home / 'Library/Fonts' / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('font fixture')
            self.local['casks'].append({'token': name, 'version': '1.0.0',
                                        'installed': [{'version': '1.0.0'}]})
        for name, (_, relative, _) in maintenance.TEMPLATES.items():
            path = self.home / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((self.root / 'config' / name).read_bytes())
        self.commands = []

    def command(self, *args):
        self.commands.append(args)
        if args[:2] == ('brew', 'info'):
            return json.dumps(self.local)
        if args[0] in ('brew', 'claude', 'codex'):
            return 'version 1.0.0'
        if args[0] == 'git':
            if 'ls-remote' in args:
                return 'a' * 40 + '\trefs/heads/master'
            if 'rev-parse' in args:
                return 'a' * 40
            if 'status' in args:
                return ''
            if 'remote' in args:
                if args[2] == str(self.root):
                    return 'https://github.com/1set/1bite.git'
                if args[2].endswith('/powerlevel10k'):
                    return 'https://github.com/romkatv/powerlevel10k.git'
                return 'https://github.com/ohmyzsh/ohmyzsh.git'
        self.fail(f'Unexpected command {args}')

    def shell(self, function, *args):
        if function == 'app_path':
            return str(self.home / 'Applications' / args[0])
        if function == 'app_healthy':
            return ''
        if function == 'code_cli':
            self.assertEqual(args, ('--list-extensions', '--show-versions'))
            return '\n'.join(name + '@1.0.0' for name in self.extensions)
        self.fail(function)

    def fetch(self, url, payload=None):
        if payload:
            names = [c['value'] for c in payload['filters'][0]['criteria'] if c['filterType'] == 7]
            self.assertEqual(names, self.extensions)
            return {'results': [{'extensions': [dict(publisher={'publisherName': name.split('.')[0]},
                    extensionName=name.split('.')[1], versions=[dict(version='1.0.0', properties=[])]) for name in names]}]}
        if url.endswith('/releases/latest'):
            return {'tag_name': '1.0.0'}
        name = url.rsplit('/', 1)[1].removesuffix('.json')
        return {'name': name, 'versions': {'stable': '1.0.0'}, 'revision': 0, 'version': '1.0.0'}

    def check(self, fetch=None, text_fetch=None, command=None, with_claude=True):
        with patch.dict(os.environ, {}, clear=True), patch.object(maintenance, 'command', command or self.command), \
                patch.object(maintenance, 'shell', self.shell), patch.object(maintenance, 'public_json', fetch or self.fetch), \
                patch.object(maintenance, 'public_text', side_effect=text_fetch or (lambda url: '  version \"1.0.0\"\n' if url.endswith('.rb') else '../Formula/p/python@3.14.rb')), \
                patch.object(maintenance.official_ai, 'release', return_value={'version': '1.0.0'}) as releases, \
                patch.object(maintenance.shutil, 'which', side_effect=lambda name: str(self.home / '.local/bin' / name)):
            report = maintenance.Checker(self.root, self.home, with_claude=with_claude).run()
            if not with_claude:
                self.assertFalse(any(call.args[0].startswith('claude') for call in releases.call_args_list))
            return report

    def test_unselected_claude_is_not_queried_or_reported(self):
        original = self.shell
        def selected_shell(function, *args):
            self.assertNotIn('Claude.app', args)
            return original(function, *args)
        self.shell = selected_shell
        (self.home / '.claude/settings.json').unlink()
        report = self.check(with_claude=False)
        self.assertTrue(report['complete'], report['issues'])
        self.assertFalse(any('claude' in item['component'] for item in report['items']))
        self.assertFalse(any('claude' in args for args in self.commands))

    def test_complete_declared_surface_schema_and_nonmutating_commands(self):
        before = {p:p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        report = self.check()
        expected = ({'formula:' + name for name in self.formulae} | {'cask:' + name for name in self.casks}
                    | {'font:' + name for name in self.fonts}
                    | {'vscode:' + name for name in self.extensions}
                    | {'config:' + name for name in maintenance.TEMPLATES}
                    | {'cli:claude', 'cli:codex', 'homebrew', 'one-bite-repository', 'ohmyzsh',
                       'powerlevel10k', 'macos'})
        self.assertEqual({item['component'] for item in report['items']}, expected)
        self.assertEqual(len(report['items']), len(expected))
        self.assertEqual(sum(report['summary'].values()), len(expected))
        schema = json.loads((ROOT / 'docs/updates.schema.json').read_text())
        self.assertEqual(set(report), set(schema['required']))
        self.assertEqual(set(report['summary']), set(schema['properties']['summary']['required']))
        item_schema = schema['properties']['items']['items']
        for item in report['items']:
            self.assertTrue(set(item_schema['required']) <= item.keys() <= item_schema['properties'].keys())
            for name in ('status', 'manager', 'next_action'):
                self.assertIn(item[name], item_schema['properties'][name]['enum'])
        self.assertTrue(report['complete'])
        self.assertEqual(before, {p:p.read_bytes() for p in self.home.rglob('*') if p.is_file()})
        for args in self.commands:
            self.assertFalse(set(args) & {'install', 'upgrade', 'update', 'fetch', 'pull', 'reset', 'trust', '--force'})

    def test_charm_catalog_channels_and_metadata_failure(self):
        names = ('glow', 'pop', 'gum', 'crush')
        report = self.check(text_fetch=lambda url: '  version "2.0.0"\n  revision 1\n')
        rows = {item['component']:item for item in report['items']}
        for name in names:
            row = rows['formula:charmbracelet/tap/' + name]
            self.assertEqual((row['latest'], row['status']), ('2.0.0_1', 'update_available'))
            self.assertIn('Charm official tap', row['note'])
        # Core copies compare against core, without requesting or trusting a vendor tap.
        for item in self.local['formulae']:
            if item['name'] in names:
                item['tap'] = 'homebrew/core'
        def unexpected(url):
            self.fail('Unexpected Charm metadata request: ' + url)
        report = self.check(text_fetch=unexpected)
        rows = {item['component']:item for item in report['items']}
        for name in names:
            row = rows['formula:charmbracelet/tap/' + name]
            self.assertEqual(row['status'], 'current')
            self.assertIn('core stable catalog', row['note'])
        for item in self.local['formulae']:
            if item['name'] in names:
                item['tap'] = 'charmbracelet/tap'
        for content in ('version compute_version()\n', 'version "1.0.0"\nversion "2.0.0"\n'):
            report = self.check(text_fetch=lambda url: content)
            self.assertFalse(report['complete'])
            rows = {item['component']:item for item in report['items']}
            for name in names:
                self.assertEqual(rows['formula:charmbracelet/tap/' + name]['status'], 'unknown')

    def test_ai_tools_stay_with_official_installers_and_do_not_query_cask_versions(self):
        def fetch(url, payload=None):
            for name in ('chatgpt', 'kiro', 'kiro-cli', 'claude-code', 'codex'):
                self.assertFalse(url.endswith('/cask/' + name + '.json'), url)
            return self.fetch(url, payload)
        self.local['casks'] = [{'token': name} for name in ('chatgpt', 'kiro', 'kiro-cli')]
        rows = {item['component']: item for item in self.check(fetch)['items']}
        for name in ('cask:chatgpt', 'cask:kiro', 'cask:kiro-cli', 'cli:claude', 'cli:codex'):
            self.assertEqual((rows[name]['manager'], rows[name]['status'], rows[name]['latest']),
                             ('original', 'current', '1.0.0'))
        shutil.rmtree(self.home / 'Applications/ChatGPT.app')
        rows = {item['component']: item for item in self.check(fetch)['items']}
        self.assertEqual((rows['cask:chatgpt']['status'], rows['cask:chatgpt']['next_action']),
                         ('missing', 'setup'))

    def test_official_release_failure_is_partial_without_losing_components(self):
        checker = maintenance.Checker(self.root, self.home)
        result = checker.attempt('official:chatgpt', lambda: (_ for _ in ()).throw(maintenance.official_ai.ET.ParseError('bad xml')))
        self.assertIsNone(result)
        self.assertEqual(checker.issues, [{'component': 'official:chatgpt', 'reason': 'query_failed'}])

    def test_homebrew_api_denial_uses_official_stable_release_redirect(self):
        sources = maintenance.Checker(self.root, self.home).sources
        with patch.object(maintenance, 'public_json', side_effect=subprocess.CalledProcessError(22, ['curl'])), \
                patch.object(maintenance, 'command', return_value='https://github.com/Homebrew/brew/releases/tag/7.0.6') as command:
            self.assertEqual(maintenance.homebrew_release(sources), '7.0.6')
            self.assertIn('--head', command.call_args.args)
            self.assertEqual(command.call_args.args[-1], sources['maintenance-homebrew-release'])

    def test_homebrew_api_success_does_not_request_fallback(self):
        sources = maintenance.Checker(self.root, self.home).sources
        with patch.object(maintenance, 'public_json', return_value={'tag_name': '7.0.6'}), \
                patch.object(maintenance, 'command') as command:
            self.assertEqual(maintenance.homebrew_release(sources), '7.0.6')
            command.assert_not_called()

    def test_homebrew_fallback_rejects_unexpected_redirects_and_reports_failure(self):
        for target in ('https://example.com/7.0.6', 'https://github.com/Homebrew/brew/releases/latest',
                       'https://github.com/Homebrew/brew/releases/tag/7.0.6-rc1'):
            checker = maintenance.Checker(self.root, self.home)
            with self.subTest(target=target), patch.object(maintenance, 'public_json', return_value={}), \
                    patch.object(maintenance, 'command', return_value=target):
                self.assertIsNone(checker.attempt('homebrew', maintenance.homebrew_release, checker.sources))
                self.assertEqual(checker.issues, [{'component': 'homebrew', 'reason': 'query_failed'}])

    def test_version_comparison_full_supported_contract(self):
        cases = [(None, '1.0', 'missing'), ('1.0', None, 'unknown'), ('1.0', '1.0.0', 'current'),
                 ('v1.0.0', '1.0.0', 'current'), ('1.2.9', '1.10.0', 'update_available'),
                 ('2.0', '1.9', 'ahead'), ('1.0_1', '1.0_2', 'update_available'),
                 ('1.0_0', '1.0', 'current'), ('1.0,11', '1.0,12', 'update_available'),
                 ('1.0,12', '1.0,11', 'ahead'), ('1.0', '1.0,12', 'manual'),
                 ('1.0.0-beta', '1.0.0', 'manual'), ('HEAD-abc', '1.0', 'manual')]
        for installed, latest, expected in cases:
            with self.subTest(installed=installed, latest=latest):
                self.assertEqual(maintenance.compare(installed, latest), expected)

    def test_gallery_excludes_prerelease_and_wrong_architecture(self):
        data = {'results': [{'extensions': [dict(publisher={'publisherName': 'GoLang'}, extensionName='Go', versions=[
            dict(version='9.0.0', targetPlatform='linux-arm64'),
            dict(version='8.0.0', properties=[dict(key='Microsoft.VisualStudio.Code.PreRelease', value='true')]),
            dict(version='2.0.0', targetPlatform='darwin-arm64', properties=[dict(key='Microsoft.VisualStudio.Code.Engine', value='^1.90.0')]),
            dict(version='1.9.0'), dict(version='HEAD')])]}]}
        self.assertEqual(maintenance.gallery_versions(data), {'golang.go': ('2.0.0', '^1.90.0')})

    def test_live_alias_resolution_without_local_installation_and_special_versions(self):
        self.local['formulae'] = [item for item in self.local['formulae'] if item['name'] != 'python']
        def fetch(url, payload=None):
            if url.endswith('/formula/python.json'):
                raise subprocess.CalledProcessError(22, 'curl')
            return self.fetch(url, payload)
        report = self.check(fetch)
        row = next(item for item in report['items'] if item['component'] == 'formula:python')
        self.assertTrue(report['complete'])
        self.assertEqual((row['installed'], row['latest'], row['status']), (None, '1.0.0', 'missing'))
        for name, old, new, state in [('tmux', '3.6a', '3.7c', 'update_available'),
                                      ('tmux', '3.6', '3.6a', 'update_available'),
                                      ('tmux', '3.6c', '3.6b', 'ahead'),
                                      ('tmux', '3.6a_1', '3.6a_2', 'update_available'),
                                      ('imagemagick', '7.1.2-9', '7.1.2-31', 'update_available'),
                                      ('imagemagick', '7.1.2-31', '7.1.2-9', 'ahead'),
                                      ('imagemagick', '7.1.2-31_1', '7.1.2-31_1', 'current')]:
            self.assertEqual(maintenance.compare_formula(name, old, new), state)

    def test_alias_revision_pin_and_self_updated_app(self):
        python = next(item for item in self.local['formulae'] if item['name'] == 'python')
        python.update(name='python@3.14', aliases=['python'], linked_keg='3.14.3_1')
        self.local['formulae'][0]['pinned'] = True
        chrome = self.home / 'Applications/Google Chrome.app/Contents/Info.plist'
        chrome.write_bytes(plistlib.dumps({'CFBundleShortVersionString': '9.0.0'}))
        def fetch(url, payload=None):
            data = self.fetch(url, payload)
            if url.endswith('/formula/python.json'):
                data.update(name='python@3.14', versions={'stable': '3.14.3'}, revision=2)
            return data
        rows = {item['component']:item for item in self.check(fetch)['items']}
        self.assertEqual(rows['formula:python']['status'], 'update_available')
        self.assertEqual(rows['formula:python']['latest'], '3.14.3_2')
        self.assertEqual(rows['formula:' + self.formulae[0]]['status'], 'manual')
        self.assertEqual(rows['cask:google-chrome']['status'], 'ahead')
        self.assertEqual(rows['cask:google-chrome']['manager'], 'original')

    def test_partial_network_failure_keeps_all_items_and_no_private_errors(self):
        def fail(url, payload=None):
            raise OSError('secret-proxy-value must not appear')
        def command(*args):
            if args[0] == 'curl':
                raise OSError('secret-proxy-value must not appear')
            return self.command(*args)
        report = self.check(fail, command=command)
        self.assertFalse(report['complete'])
        self.assertTrue(report['issues'])
        self.assertEqual(len(report['items']), len(self.check()['items']))
        self.assertNotIn('secret-proxy-value', json.dumps(report))
        output = Path(self.temp.name) / 'report'
        output.mkdir()
        maintenance.save(report, output)
        self.assertEqual(json.loads((output / 'updates.json').read_text()), report)
        self.assertIn('unknown', (output / 'updates.md').read_text())

    def test_provider_schema_failure_still_covers_entire_manifest(self):
        self.local = {'formulae': [None], 'casks': []}
        report = self.check()
        self.assertFalse(report['complete'])
        rows = {item['component']:item for item in report['items']}
        for name in self.formulae:
            self.assertEqual(rows['formula:' + name]['status'], 'unknown')

    def test_personal_configuration_and_managed_drift_are_distinct(self):
        (self.home / '.claude/settings.json').write_text('{"personal-secret":"never-print"}')
        (self.home / '.config/1bite/env.zsh').write_text('# local changes\n')
        report = self.check()
        rows = {item['component']:item for item in report['items']}
        self.assertEqual(rows['config:claude-settings.json']['status'], 'preserved')
        self.assertEqual(rows['config:env.zsh']['status'], 'different')
        self.assertNotIn('never-print', json.dumps(report))

    def test_unexpected_git_origin_is_not_contacted(self):
        checker = maintenance.Checker(self.root, self.home)
        def command(*args):
            if 'rev-parse' in args:
                return 'a' * 40
            if 'remote' in args:
                return 'https://private-token@example.invalid/repo.git'
            self.fail('Unexpected remote contact')
        with patch.object(maintenance, 'command', command):
            checker.repository('one-bite-repository', self.root, 'https://github.com/1set/1bite.git', 'master')
        self.assertEqual(checker.items[0]['status'], 'manual')
        self.assertNotIn('private-token', json.dumps(checker.items))

    def test_check_mode_rejects_update_combination_before_execution(self):
        result = subprocess.run(['bash', str(ROOT / '1bite'), '--check-updates', '--update'],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--update is only valid', result.stderr)


if __name__ == '__main__':
    unittest.main()
