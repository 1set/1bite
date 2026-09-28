#!/usr/bin/env python3
"""Record only declared packages and public version metadata, never user config."""
import json
import os
from pathlib import Path
import subprocess
from configure import kiro_policy_status
from desktop import APPS as MANUAL_APPS

ROOT = Path(__file__).resolve().parents[1]


def output(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, timeout=60).strip()


def inventory():
    with_claude = os.environ.get('ONE_BITE_WITH_CLAUDE') == 'true'
    packages = (ROOT / 'config/formulae.txt').read_text().split()
    references = [output('/bin/bash', '-c', 'source "$1"; installed_formula_ref "$2"',
                         'inventory', str(ROOT / '1bite'), name) if '/' in name else 'homebrew/core/' + name
                  for name in packages]
    data = json.loads(output('brew', 'info', '--json=v2', '--formula', *references))
    formulae = {item['name']: [entry['version'] for entry in item['installed']]
                for item in data['formulae']}
    apps, pending = {}, []
    allow_prepared = os.environ.get('ONE_BITE_ALLOW_PREPARED_DESKTOPS') == '1'
    for line in (ROOT / 'config/casks.tsv').read_text().splitlines():
        token, app = line.split('\t')
        if token == 'claude-desktop' and not with_claude:
            continue
        path = output('/bin/bash', '-c', 'source "$1"; app_path "$2"',
                      'inventory', str(ROOT / '1bite'), app)
        if allow_prepared and token in MANUAL_APPS:
            healthy = subprocess.run(['/bin/bash', '-c', 'source "$1"; app_healthy "$2"',
                                      'inventory', str(ROOT / '1bite'), app],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
            if not healthy:
                apps[token] = None
                pending.append(token)
                continue
        apps[token] = output('/usr/libexec/PlistBuddy', '-c', 'Print :CFBundleShortVersionString',
                             f'{path}/Contents/Info.plist')
    tools = {}
    for name in ('claude', 'codex', 'kiro-cli', 'docker'):
        if name == 'claude' and not with_claude:
            continue
        try:
            tools[name] = output(name, '--version').splitlines()[0]
        except (OSError, subprocess.CalledProcessError):
            if not allow_prepared or name not in ('kiro-cli', 'docker'):
                raise
            tools[name] = None

    tools['go'] = output('go', 'version')
    extension_lines = output('/bin/bash', '-c', 'source "$1"; code_cli --list-extensions --show-versions',
                             'inventory', str(ROOT / '1bite')).splitlines()
    declared = (ROOT / 'config/vscode-extensions.txt').read_text().split()
    available = dict(line.lower().rsplit('@', 1) for line in extension_lines if '@' in line)
    extensions = {name: available[name] for name in declared}
    font_casks = [line.split('\t', 1)[0] for line in (ROOT / 'config/font-casks.tsv').read_text().splitlines()]
    omz = output('/bin/bash', '-c', 'source "$1"; omz_path', 'inventory', str(ROOT / '1bite'))
    try:
        omz_revision = output('git', '-C', omz, 'rev-parse', 'HEAD')
    except subprocess.CalledProcessError:
        omz_revision = 'unmanaged'
    p10k = output('/bin/bash', '-c', 'source "$1"; powerlevel10k_path',
                  'inventory', str(ROOT / '1bite'))
    try:
        p10k_revision = output('git', '-C', p10k, 'rev-parse', 'HEAD')
    except subprocess.CalledProcessError:
        p10k_revision = 'unmanaged'
    try:
        revision = output('git', '-C', str(ROOT), 'rev-parse', 'HEAD')
    except subprocess.CalledProcessError:
        revision = 'archive'
    return {'schema_version': 1, 'script_version': (ROOT / 'VERSION').read_text().strip(),
            'revision': revision, 'formulae': formulae, 'applications': apps, 'tools': tools,
            'pending_applications': pending, 'with_claude': with_claude,
            'font_casks': font_casks,
            'vscode_extensions': extensions, 'ohmyzsh_revision': omz_revision,
            'powerlevel10k_revision': p10k_revision,
            'kiro_permission_template': kiro_policy_status(Path.home())}


if __name__ == '__main__':
    data = inventory()
    if os.environ.get('RUN_DIR'):
        path = Path(os.environ['RUN_DIR']) / 'inventory.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, indent=2) + '\n')
        temporary.replace(path)
    print('Declared software inventory recorded.')
