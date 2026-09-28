#!/usr/bin/env python3
"""Read declared local state and public release metadata; never install or upgrade."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import importlib.util
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('official_ai', ROOT / 'scripts/official_ai.py')
official_ai = importlib.util.module_from_spec(spec)
spec.loader.exec_module(official_ai)

STATES = ('current', 'update_available', 'ahead', 'missing', 'repair_needed', 'different',
          'preserved', 'manual', 'unknown')
TEMPLATES = {
    'claude-settings.json': ('CLAUDE_CONFIG_DIR', '.claude/settings.json', True),
    'codex-config.toml': ('CODEX_HOME', '.codex/config.toml', True),
    'kiro-permissions.json': (None, '.kiro/settings/permissions.yaml', True),
    'env.zsh': (None, '.config/1bite/env.zsh', False),
    'shell.zsh': (None, '.config/1bite/shell.zsh', False),
    'zsh/framework.zsh': (None, '.config/1bite/zsh/framework.zsh', False),
    'zsh/options.zsh': (None, '.config/1bite/zsh/options.zsh', False),
    'zsh/tools.zsh': (None, '.config/1bite/zsh/tools.zsh', False),
    'zsh/development.zsh': (None, '.config/1bite/zsh/development.zsh', False),
    'zsh/utilities.zsh': (None, '.config/1bite/zsh/utilities.zsh', False),
    'zsh/media.zsh': (None, '.config/1bite/zsh/media.zsh', False),
    'zsh/git-functions.zsh': (None, '.config/1bite/zsh/git-functions.zsh', False),
    'zsh/terminal.zsh': (None, '.config/1bite/zsh/terminal.zsh', False),
    'vimrc': (None, '.config/1bite/vimrc', False),
    'iterm2-profile.json': (None, 'Library/Application Support/iTerm2/DynamicProfiles/1bite.json', False),
    'vscode-settings.json': (None, 'Library/Application Support/Code/User/settings.json', True),
    'obsidian-vault/.gitignore': (None, '.config/1bite/obsidian-vault/.gitignore', False),
    'obsidian-vault/.obsidian/app.json': (None, '.config/1bite/obsidian-vault/.obsidian/app.json', False),
    'obsidian-vault/.obsidian/appearance.json': (None, '.config/1bite/obsidian-vault/.obsidian/appearance.json', False),
    'obsidian-vault/.obsidian/core-plugins.json': (None, '.config/1bite/obsidian-vault/.obsidian/core-plugins.json', False),
    'obsidian-vault/.obsidian/graph.json': (None, '.config/1bite/obsidian-vault/.obsidian/graph.json', False),
    'obsidian-vault/.obsidian/snippets/wide.css': (None, '.config/1bite/obsidian-vault/.obsidian/snippets/wide.css', False),
    'obsidian-vault/.obsidian/templates.json': (None, '.config/1bite/obsidian-vault/.obsidian/templates.json', False),
    'obsidian-vault/.obsidian/themes/Tokyo Night/LICENSE': (None, '.config/1bite/obsidian-vault/.obsidian/themes/Tokyo Night/LICENSE', False),
    'obsidian-vault/.obsidian/themes/Tokyo Night/manifest.json': (None, '.config/1bite/obsidian-vault/.obsidian/themes/Tokyo Night/manifest.json', False),
    'obsidian-vault/.obsidian/themes/Tokyo Night/theme.css': (None, '.config/1bite/obsidian-vault/.obsidian/themes/Tokyo Night/theme.css', False),
    'obsidian-vault/_attachments/.gitkeep': (None, '.config/1bite/obsidian-vault/_attachments/.gitkeep', False),
    'obsidian-vault/_templates/.gitkeep': (None, '.config/1bite/obsidian-vault/_templates/.gitkeep', False),
}
EXTERNAL_APPS = {'chatgpt', 'kiro', 'kiro-cli', 'claude-desktop'}


def command(*args):
    env = {**os.environ, 'HOMEBREW_NO_AUTO_UPDATE': '1', 'GIT_TERMINAL_PROMPT': '0', 'GIT_OPTIONAL_LOCKS': '0'}
    return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, env=env, timeout=45).strip()


def shell(function, *args):
    # Function names come only from this file; arguments are passed as argv, never interpolated.
    return command('/bin/bash', '-c', 'source "$1"; shift; ' + function + ' "$@"',
                   'maintenance', str(ROOT / '1bite'), *args)


def version_key(value):
    match = re.fullmatch(r'v?(\d+(?:\.\d+)*)(?:_(\d+))?', value or '')
    if not match:
        return None
    parts = tuple(int(part) for part in match[1].split('.'))
    return parts + (0,) * max(0, 12 - len(parts)) + (int(match[2] or 0),)


def compare(installed, latest):
    if not installed:
        return 'missing'
    if not latest:
        return 'unknown'
    if not isinstance(installed, str) or not isinstance(latest, str):
        return 'unknown'
    if installed == latest:
        return 'current'
    # Casks sometimes include a separate build number. Compare both components.
    old, new = installed.split(','), latest.split(',')
    if len(old) != len(new) or any(version_key(v) is None for v in old + new):
        return 'manual'
    a, b = tuple(map(version_key, old)), tuple(map(version_key, new))
    return 'update_available' if a < b else ('ahead' if a > b else 'current')


def compare_formula(name, installed, latest):
    def normalize(value):
        if not isinstance(value, str):
            return value
        if name == 'tmux':
            match = re.fullmatch(r'(\d+\.\d+)([a-z]?)(_[0-9]+)?', value)
            if match:
                return match[1] + '.' + str(ord(match[2]) - ord('a') + 1 if match[2] else 0) + (match[3] or '')
        if name == 'imagemagick' and re.fullmatch(r'\d+(?:\.\d+)*-\d+(?:_\d+)?', value):
            return value.replace('-', '.')
        return value
    return compare(normalize(installed), normalize(latest))


def public_text(url, payload=None):
    args = ['curl', '--disable', '--config', str(ROOT / 'config/download.curlrc'), '--fail',
            '--silent', '--location', '--retry', '0', '--max-time', '20', '--max-filesize', '12000000']
    if payload is not None:
        args += ['--header', 'Content-Type: application/json', '--header', 'Accept: application/json;api-version=7.2-preview.1',
                 '--data-binary', json.dumps(payload)]
    return command(*args, url)


def public_json(url, payload=None):
    return json.loads(public_text(url, payload))


def homebrew_release(sources):
    try:
        version = public_json(sources['maintenance-homebrew'])['tag_name']
        if version_key(version) is None:
            raise ValueError('Invalid Homebrew release version')
        return version
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        # Public API access can be denied on shared networks. The official latest
        # release redirect exposes the same stable tag without API authentication.
        target = command('curl', '--disable', '--config', str(ROOT / 'config/download.curlrc'),
                         '--fail', '--silent', '--location', '--head', '--output', os.devnull,
                         '--retry', '0', '--max-time', '20', '--proto', '=https',
                         '--proto-redir', '=https', '--write-out', '%{url_effective}',
                         sources['maintenance-homebrew-release'])
        match = re.fullmatch(r'https://github\.com/Homebrew/brew/releases/tag/(v?\d+(?:\.\d+)+)', target)
        if not match:
            raise ValueError('Invalid Homebrew release redirect')
        return match[1]


def gallery_versions(data):
    versions = {}
    for result in data['results']:
        for extension in result['extensions']:
            name = (extension['publisher']['publisherName'] + '.' + extension['extensionName']).lower()
            candidates = []
            for item in extension['versions']:
                props = {p['key']: p['value'] for p in item.get('properties', [])}
                if (props.get('Microsoft.VisualStudio.Code.PreRelease', 'false') != 'true'
                        and item.get('targetPlatform', '') in ('', 'universal', 'darwin-arm64')
                        and version_key(item['version']) is not None):
                    candidates.append((version_key(item['version']), item['version'],
                                       props.get('Microsoft.VisualStudio.Code.Engine', 'unknown')))
            if candidates:
                _, version, engine = max(candidates)
                versions[name] = (version, engine)
    return versions


class Checker:
    def __init__(self, root=ROOT, home=None, config_dir=None, with_claude=False, with_docker=False):
        self.with_claude = with_claude
        self.with_docker = with_docker
        self.root, self.home = root, home or Path.home()
        self.config_dir = config_dir or root / 'config'
        self.items, self.issues = [], []
        self.sources = {name: url for name, kind, url in
                        (line.split('\t') for line in (root / 'config/sources.tsv').read_text().splitlines())}

    def attempt(self, component, function, *args):
        try:
            return function(*args)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, official_ai.ET.ParseError, subprocess.SubprocessError):
            # Never expose raw command output, credentials, proxy URLs or private paths.
            self.issues.append({'component': component, 'reason': 'query_failed'})
            return None

    def add(self, component, installed=None, latest=None, manager='unknown', status=None, note='', **extra):
        if any(value is not None and not isinstance(value, str) for value in (installed, latest)):
            self.issues.append({'component': component, 'reason': 'query_failed'})
            installed = installed if isinstance(installed, str) else None
            latest = latest if isinstance(latest, str) else None
            status = 'unknown'
        state = status or compare(installed, latest)
        action = 'none'
        if state in ('missing', 'repair_needed'):
            action = 'setup' if manager != 'original' else 'original_updater'
        elif state == 'update_available':
            action = 'update' if manager in ('homebrew', 'native', 'npm', 'vscode') else 'original_updater'
        elif state in ('different', 'manual', 'unknown'):
            action = 'review'
        self.items.append(dict(component=component, installed=installed, latest=latest, manager=manager,
                               status=state, next_action=action, note=note, **extra))

    def packages(self):
        formulae = (self.root / 'config/formulae.txt').read_text().split()
        casks = [line.split('\t') for line in (self.root / 'config/casks.tsv').read_text().splitlines()
                 if (self.with_claude or not line.startswith('claude-desktop\t'))
                 and (self.with_docker or not line.startswith('docker-desktop\t'))]
        fonts = [line.split('\t') for line in (self.root / 'config/font-casks.tsv').read_text().splitlines()]
        local = self.attempt('homebrew:inventory', lambda: json.loads(command('brew', 'info', '--json=v2', '--installed')))
        by_name, managed_casks = {}, {}
        if local is not None:
            for item in local['formulae']:
                tap = item.get('tap')
                if tap in ('homebrew/core', 'charmbracelet/tap'):
                    for name in [item['name'], *item.get('aliases', [])]:
                        by_name[name if tap == 'homebrew/core' else tap + '/' + name] = item
            managed_casks = {item['token']: item for item in local['casks']}
        # Existing core copies retain their own catalog and upgrade channel.
        channels = {name: (name.rsplit('/', 1)[-1] if name.startswith('charmbracelet/tap/')
                          and name not in by_name and name.rsplit('/', 1)[-1] in by_name else name)
                    for name in formulae}
        queries = ([('formula', name) for name in formulae] +
                   [('cask', name) for name, _ in casks if name not in EXTERNAL_APPS] +
                   [('cask', name) for name, _ in fonts])
        def entry(kind, name):
            if kind == 'formula' and name.startswith('charmbracelet/tap/'):
                # Read generated public metadata as text; never evaluate Ruby or change tap trust.
                content = public_text(self.sources['maintenance-charm'] + name.rsplit('/', 1)[-1] + '.rb')
                versions = re.findall(r'^\s*version "([0-9]+(?:\.[0-9]+)*)"\s*$', content, re.M)
                revisions = re.findall(r'^\s*revision (\d+)\s*$', content, re.M)
                if len(versions) != 1 or len(revisions) > 1:
                    raise ValueError('Unsupported Charm formula metadata')
                return {'name': name, 'versions': {'stable': versions[0]},
                        'revision': int(revisions[0]) if revisions else 0}
            data = public_json(self.sources['maintenance-catalog'] + f'{kind}/{name}.json')
            if not isinstance(data, dict):
                raise ValueError('Invalid catalog entry')
            versions = data.get('versions')
            version = data.get('version') if kind == 'cask' else (versions.get('stable') if isinstance(versions, dict) else None)
            if not isinstance(version, str) or not version:
                raise ValueError('Missing catalog version')
            return data
        def fetch(pair):
            kind, name = pair
            if kind == 'formula':
                name = channels[name]
            try:
                return entry(kind, name)
            except (OSError, ValueError, subprocess.SubprocessError):
                if kind == 'formula' and '/' not in name:
                    try:
                        alias = public_text(self.sources['maintenance-aliases'] + name)
                        match = re.fullmatch(r'\.\./Formula/[a-z0-9]/([a-z0-9@+_.-]+)\.rb', alias)
                        if match:
                            return entry(kind, match[1])
                    except (OSError, ValueError, subprocess.SubprocessError):
                        pass
                return None
        with ThreadPoolExecutor(max_workers=6) as executor:
            catalog = dict(zip(queries, executor.map(fetch, queries)))
        for (kind, name), data in catalog.items():
            if data is None:
                self.issues.append({'component': kind + ':' + name, 'reason': 'catalog_unavailable'})
        for name in formulae:
            data = catalog[('formula', name)]
            item = by_name.get(data.get('name') if data else channels[name]) or by_name.get(channels[name])
            installed = item.get('linked_keg') if item else None
            if not installed and item and item.get('installed'):
                installed = item['installed'][-1]['version']
            latest = None
            if data and data.get('versions', {}).get('stable'):
                latest = data['versions']['stable'] + ('_' + str(data['revision']) if data.get('revision') else '')
            state = compare_formula(name.rsplit('/', 1)[-1], installed, latest) if local is not None else 'unknown'
            note = ('Charm official tap metadata; ' if channels[name].startswith('charmbracelet/tap/')
                    else 'Homebrew core stable catalog; ') + 'dependencies are handled by Homebrew.'
            if item and item.get('pinned'):
                state, note = 'manual', 'Pinned formula: review the pin; setup does not unpin it.'
            if data and (data.get('disabled') or data.get('deprecated')):
                state, note = 'manual', 'Upstream formula is disabled/deprecated; review replacement before updating.'
            self.add('formula:' + name, installed, latest, 'homebrew', state, note)
        with ThreadPoolExecutor(max_workers=5) as executor:
            names = ('chatgpt', 'kiro', 'kiro-cli', 'codex') + (('claude-desktop', 'claude') if self.with_claude else ())
            official = dict(zip(names, executor.map(
                lambda name: self.attempt('official:' + name, official_ai.release, name, self.sources), names)))
        for name, app in casks:
            external = name in EXTERNAL_APPS
            data = catalog.get(('cask', name))
            vendor = official.get(name) if external else None
            latest = vendor.get('version') if vendor else (data.get('version') if data else None)
            if vendor and vendor.get('build'):
                latest += ',' + vendor['build']
            path = self.attempt('cask:' + name, shell, 'app_path', app)
            installed, state = None, None
            managed = not external and name in managed_casks and path == '/Applications/' + app
            manager = 'homebrew' if managed else 'original'
            if external and path and (not Path(path).exists() or
                    self.attempt('cask:' + name, official_ai.managed, name, Path(path), self.home)):
                manager = 'native'
            if path is None:
                state = 'unknown'
            elif Path(path).exists():
                info = self.attempt('cask:' + name, lambda: plistlib.loads((Path(path) / 'Contents/Info.plist').read_bytes()))
                if info:
                    installed = str(info.get('CFBundleShortVersionString', '')) or None
                    if latest and ',' in latest and installed:
                        installed += ',' + str(info.get('CFBundleVersion', 'unknown'))
                    try:
                        shell('app_healthy', app)
                    except (OSError, subprocess.SubprocessError):
                        state = 'repair_needed'
                else:
                    state = 'repair_needed'
            else:
                state, manager = 'missing', 'native' if external else 'homebrew'
            if data and (data.get('disabled') or data.get('deprecated')):
                state = 'manual'
            self.add('cask:' + name, installed, latest, manager, state,
                     'Official stable/latest metadata; default prepares desktop DMGs. --managed-desktop --update updates recorded apps; other copies use their own updater.' if external else
                     'Actual app version, including self-updates; user/unmanaged copies use their own updater.')
        for name, filename in fonts:
            data = catalog.get(('cask', name))
            latest = data.get('version') if data else None
            item = managed_casks.get(name)
            path = self.home / 'Library/Fonts' / filename
            installed = None
            if item:
                installed = item.get('version')
                if not installed and item.get('installed'):
                    entry = item['installed'][-1]
                    installed = entry.get('version') if isinstance(entry, dict) else str(entry)
            if path.is_file() and path.stat().st_size:
                state = compare(installed, latest) if installed else 'preserved'
                manager = 'homebrew' if item else 'original'
            else:
                state = 'repair_needed' if item else 'missing'
                manager = 'homebrew'
            if data and (data.get('disabled') or data.get('deprecated')):
                state = 'manual'
            self.add('font:' + name, installed, latest, manager, state,
                     'Homebrew Nerd Font cask; verify the declared regular face in ~/Library/Fonts.')
        for name in (('claude', 'codex') if self.with_claude else ('codex',)):
            executable = shutil.which(name)
            value = self.attempt('cli:' + name, command, name, '--version') if executable else None
            match = re.search(r'\d+(?:\.\d+)+(?:[-+][\w.]+)?', value or '')
            installed = match[0] if match else None
            owned = self.attempt('cli:' + name, official_ai.managed, name, self.home / '.local/bin' / name, self.home)
            manager = 'native' if not executable or (owned and executable == str(self.home / '.local/bin' / name)) else 'original'
            latest = official[name]['version'] if official.get(name) else None
            self.add('cli:' + name, installed, latest, manager=manager,
                     status=None if installed else ('repair_needed' if executable else 'missing'),
                     note='Official latest release; setup updates its recorded native installs without migrating other managers.')

    def extensions(self):
        names = (self.root / 'config/vscode-extensions.txt').read_text().split()
        local = self.attempt('vscode:inventory', shell, 'code_cli', '--list-extensions', '--show-versions')
        installed = dict(line.lower().rsplit('@', 1) for line in (local or '').splitlines() if '@' in line)
        payload = {'filters': [{'criteria': [{'filterType': 7, 'value': name} for name in names] +
                               [{'filterType': 8, 'value': 'Microsoft.VisualStudio.Code'}],
                               'pageNumber': 1, 'pageSize': len(names)}], 'flags': 17}
        data = self.attempt('vscode:catalog', public_json, self.sources['maintenance-gallery'], payload)
        available = self.attempt('vscode:catalog', gallery_versions, data) if data else {}
        for name in names:
            latest, engine = (available or {}).get(name, (None, None))
            if latest is None:
                self.issues.append({'component': 'vscode:' + name, 'reason': 'catalog_version_missing'})
            self.add('vscode:' + name, installed.get(name), latest, 'vscode', 'unknown' if local is None else None,
                     'Stable darwin-arm64/universal release; VS Code resolves editor compatibility during update.',
                     requires_vscode=engine)

    def repository(self, component, path, source, branch):
        if not path.exists():
            self.add(component, manager='git', status='missing')
            return
        installed = self.attempt(component, command, 'git', '-C', str(path), 'rev-parse', 'HEAD')
        remote = self.attempt(component, command, 'git', '-C', str(path), 'remote', 'get-url', 'origin')
        expected = {source, source.removesuffix('.git'), source.replace('https://github.com/', 'git@github.com:')}
        if not installed or remote not in expected:
            self.add(component, installed, manager='original', status='manual', note='Archive/custom origin: review original source.')
            return
        upstream = self.attempt(component, command, 'git', '-C', str(path), 'ls-remote', 'origin', 'refs/heads/' + branch)
        latest = upstream.split()[0] if upstream and re.match(r'^[a-f0-9]{40}\s', upstream) else None
        dirty = self.attempt(component, command, 'git', '-C', str(path), 'status', '--porcelain', '--untracked-files=no')
        state = 'unknown' if latest is None or dirty is None else ('different' if installed != latest or dirty else 'current')
        self.add(component, installed, latest, 'git', state,
                 'No fetch/pull performed. A different hash may be behind, ahead or diverged; review before --ff-only pull.')

    def configurations(self):
        for name, (variable, relative, preserve) in TEMPLATES.items():
            if name == 'claude-settings.json' and not self.with_claude:
                continue
            target = self.home / relative
            if variable and os.environ.get(variable):
                target = Path(os.environ[variable]) / target.name
            def check():
                if not target.is_absolute() or target.is_symlink():
                    return 'manual'
                if not target.exists():
                    return 'missing'
                if target.read_bytes() == (self.config_dir / name).read_bytes():
                    return 'current'
                return 'preserved' if preserve else 'different'
            state = self.attempt('config:' + name, check) or 'unknown'
            self.add('config:' + name, manager='configuration', status=state,
                     note='Compare selected template bytes only; never log personal contents or hashes. Existing AI/editor files are preserved.')

    def run(self):
        self.attempt('section:packages', self.packages)
        self.attempt('section:extensions', self.extensions)
        self.repository('one-bite-repository', self.root, self.sources['maintenance-one-bite'], 'master')
        self.repository('ohmyzsh', Path(os.environ.get('ZSH') or self.home / '.oh-my-zsh'),
                        self.sources['maintenance-ohmyzsh'], 'master')
        zsh_root = Path(os.environ.get('ZSH') or self.home / '.oh-my-zsh')
        zsh_custom = Path(os.environ.get('ZSH_CUSTOM') or zsh_root / 'custom')
        self.repository('powerlevel10k', zsh_custom / 'themes/powerlevel10k',
                        self.sources['powerlevel10k'], 'master')
        self.attempt('section:configurations', self.configurations)
        brew = self.attempt('homebrew', command, 'brew', '--version')
        release = self.attempt('homebrew', homebrew_release, self.sources)
        match = re.search(r'\d+(?:\.\d+)+', brew or '')
        self.add('homebrew', match[0] if match else None, release, 'homebrew',
                 note='brew update refreshes Homebrew metadata; it does not upgrade installed packages.')
        self.add('macos', manager='system', status='manual', note='Review System Settings > General > Software Update on the Mac.')
        expected = (['formula:' + name for name in (self.root / 'config/formulae.txt').read_text().split()]
                    + ['cask:' + line.split('\t')[0] for line in (self.root / 'config/casks.tsv').read_text().splitlines()]
                    + ['font:' + line.split('\t')[0] for line in (self.root / 'config/font-casks.tsv').read_text().splitlines()]
                    + ['vscode:' + name for name in (self.root / 'config/vscode-extensions.txt').read_text().split()]
                    + ['config:' + name for name in TEMPLATES] +
                    ['cli:claude', 'cli:codex', 'powerlevel10k'])
        if not self.with_claude:
            expected = [name for name in expected if name not in ('cask:claude-desktop', 'cli:claude', 'config:claude-settings.json')]
        if not self.with_docker:
            expected = [name for name in expected if name != 'cask:docker-desktop']
        present = {item['component'] for item in self.items}
        for component in expected:
            if component not in present:
                self.add(component, status='unknown', note='Provider failed before this item could be checked.')
        for item in self.items:
            if item['status'] == 'unknown' and not any(issue['component'] == item['component'] for issue in self.issues):
                self.issues.append({'component': item['component'], 'reason': 'undetermined'})
        return {'schema_version': 1, 'script_version': (self.root / 'VERSION').read_text().strip(),
                'checked_at': datetime.now(timezone.utc).isoformat(), 'complete': not self.issues,
                'attention_required': bool(self.issues) or any(item['status'] not in ('current', 'ahead', 'preserved') for item in self.items),
                'summary': {state: sum(item['status'] == state for item in self.items) for state in STATES},
                'items': self.items, 'issues': self.issues}


def save(report, directory):
    path = directory / 'updates.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, indent=2) + '\n')
    temporary.replace(path)
    rows = ['# Maintenance check', '', f"Complete: {report['complete']}. This report never installs updates.", '',
            '| Component | Installed | Reference | Status | Next action |', '| --- | --- | --- | --- | --- |']
    for item in report['items']:
        cells = [item[key] or '-' for key in ('component', 'installed', 'latest', 'status', 'next_action')]
        rows.append('| ' + ' | '.join(str(value).replace('|', '\\|').replace('\n', ' ') for value in cells) + ' |')
    rows += ['', 'Read docs/maintenance.md before applying updates. Unknown is not current.', '']
    (directory / 'updates.md').write_text('\n'.join(rows))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config-dir', type=Path, default=ROOT / 'config')
    parser.add_argument('--with-claude', action='store_true', default=os.environ.get('ONE_BITE_WITH_CLAUDE') == 'true')
    parser.add_argument('--with-docker', action='store_true', default=os.environ.get('ONE_BITE_WITH_DOCKER') == 'true')
    args = parser.parse_args()
    directory = Path(os.environ['RUN_DIR'])
    report = Checker(config_dir=args.config_dir, with_claude=args.with_claude, with_docker=args.with_docker).run()
    save(report, directory)
    print('Maintenance status:', json.dumps(report['summary']))
    print('Reports:', directory / 'updates.md', 'and updates.json')
    if not report['complete']:
        print('Some checks failed. Read issues in updates.json; fix connectivity/tools and rerun.')
        raise SystemExit(1)


if __name__ == '__main__':
    main()
