#!/usr/bin/env python3
"""Install the vendor's Zsh hooks without enabling other system integrations."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

COMMANDS = ('kiro-cli', 'kiro-cli-chat', 'kiro-cli-term')
# Full vendor-loader contract: a nonempty but truncated file is not a working hook.
HELPERS = {f'{rc}.{phase}.zsh': '[ -x ~/.local/bin/kiro-cli ] && eval "$(~/.local/bin/kiro-cli init zsh '
           + phase + ' --rcfile ' + rc + ')"'
           for rc in ('zshrc', 'zprofile') for phase in ('pre', 'post')}


def helpers_healthy(directory):
    return all((directory / name).is_file() and (directory / name).read_text() == content
               for name, content in HELPERS.items())


def runnable(path):
    if not path or not os.access(path, os.X_OK):
        return False
    try:
        return subprocess.run([str(path), '--version'], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def integration_status(cli):
    result = subprocess.run([str(cli), 'integrations', 'status', '--format', 'json', 'dotfiles', 'zsh'],
                            capture_output=True, text=True, check=True, timeout=30)
    data = json.loads(result.stdout)
    if data.get('errors') or not isinstance(data.get('integrations'), list):
        raise ValueError('Kiro integration status failed; inspect with kiro-cli integrations status dotfiles zsh')
    rows = [item for item in data['integrations'] if item.get('shell') == 'zsh']
    if len(rows) != 2 or {item.get('file_name') for item in rows} != {'.zshrc', '.zprofile'}:
        raise ValueError('Kiro Zsh integration status format changed; update setup before proceeding')
    if any(type(item.get('installed')) is not bool for item in rows):
        raise ValueError('Kiro integration status must contain boolean installation results')
    return all(item['installed'] for item in rows)


def check_kiro_home_support(cli, home):
    override = os.environ.get('KIRO_HOME')
    if not override:
        return
    if not Path(override).is_absolute():
        raise ValueError('KIRO_HOME must be absolute')
    if Path(override) == home / '.kiro':
        return
    # Older CLIs silently ignore KIRO_HOME and would change the default profile.
    result = subprocess.run([str(cli), '--version'], capture_output=True, text=True, check=True, timeout=15)
    match = re.fullmatch(r'kiro-cli (\d+)\.(\d+)\.(\d+)', result.stdout.strip())
    if not match or tuple(map(int, match.groups())) < (2, 3, 0):
        raise ValueError('A custom KIRO_HOME requires Kiro CLI 2.3.0 or newer; update the selected CLI '
                         'with its original manager before rerunning setup. No settings were changed.')


def inline_preference(cli, home, verify):
    kiro_home = Path(os.environ.get('KIRO_HOME') or home / '.kiro')
    if not kiro_home.is_absolute():
        raise ValueError('KIRO_HOME must be absolute')
    path = kiro_home / 'settings/cli.json'
    if any(item.is_symlink() for item in (kiro_home, path.parent, path)):
        raise ValueError('Refusing to change Kiro CLI settings through a symlink')
    data = json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(data, dict) or ('inline.enabled' in data and type(data['inline.enabled']) is not bool):
        raise ValueError('Kiro inline preference must be a boolean in CLI settings')
    if 'inline.enabled' not in data:
        if verify:
            raise ValueError('Kiro inline history-sharing preference is unset; rerun setup')
        subprocess.run([str(cli), 'inline', 'disable'], stdout=subprocess.DEVNULL, check=True, timeout=15,
                       pass_fds=(9,) if os.environ.get('ONE_BITE_LOCKED') == '1' else ())
        if not path.is_file():
            raise ValueError('Kiro did not create settings in the requested configuration directory; '
                             'check the selected CLI version and KIRO_HOME before rerunning setup')
        if json.loads(path.read_text()).get('inline.enabled') is not False:
            raise ValueError('Kiro did not save the disabled inline history-sharing preference')
        print('Kiro inline history-based AI suggestions: disabled for new settings.', file=sys.stderr)
        return True
    print('Kiro inline history-based AI suggestions: preserving your ' +
          ('enabled' if data['inline.enabled'] else 'disabled') + ' preference.', file=sys.stderr)
    return False


def verify_generated_hooks(cli):
    for rc in ('zshrc', 'zprofile'):
        for phase in ('pre', 'post'):
            result = subprocess.run([str(cli), 'init', 'zsh', phase, '--rcfile', rc],
                                    capture_output=True, text=True, check=True, timeout=15)
            subprocess.run(['/bin/zsh', '-n'], input=result.stdout, text=True, check=True,
                           stdout=subprocess.DEVNULL, timeout=15)


def configure(home, app, verify=False):
    shell_home = Path(os.environ.get('ZDOTDIR') or home)
    if not shell_home.is_absolute():
        raise ValueError('ZDOTDIR must be absolute')
    binaries = home / '.local/bin'
    helpers = home / 'Library/Application Support/kiro-cli/shell'
    protected = [shell_home / '.zshrc', shell_home / '.zprofile', *[helpers / name for name in HELPERS]]
    for directory in (shell_home, binaries, helpers):
        protected.extend([directory, *[parent for parent in directory.parents if parent != home and home in parent.parents]])
    for path in protected:
        if path.is_symlink():
            raise ValueError(f'Refusing Kiro integration through symlink: {path}')
    links = []
    for name in COMMANDS:
        target = binaries / name
        if runnable(target):
            continue
        # Only repair broken links to the vendor app; preserve unknown user commands.
        if target.exists() or (target.is_symlink() and not str(target.resolve()).endswith(
                '/Kiro CLI.app/Contents/MacOS/' + name)):
            raise ValueError(f'Existing command is broken; repair it with its original manager: {name}')
        candidate = shutil.which(name)
        source = Path(candidate) if runnable(candidate) else app / 'Contents/MacOS' / name
        if not runnable(source):
            raise ValueError(f'Kiro CLI application is missing a runnable {name}')
        links.append((target, source))
    if verify and links:
        raise ValueError('Kiro CLI links are missing or broken; rerun setup')
    selected_cli = next((source for target, source in links if target.name == 'kiro-cli'), binaries / 'kiro-cli')
    check_kiro_home_support(selected_cli, home)
    if links:
        binaries.mkdir(parents=True, exist_ok=True)
        for target, source in links:
            if target.is_symlink():
                target.unlink()
            target.symlink_to(source)
    cli = binaries / 'kiro-cli'
    os.environ['PATH'] = str(binaries) + os.pathsep + os.environ.get('PATH', '')
    preference_changed = inline_preference(cli, home, verify)
    verify_generated_hooks(cli)
    installed = integration_status(cli) and helpers_healthy(helpers)
    if verify and not installed:
        raise ValueError('Kiro Zsh integration is incomplete; rerun setup')
    if not installed:
        # Native installer backs up changed dotfiles and keeps pre/post blocks at the edges.
        subprocess.run([str(cli), 'integrations', 'install', '--silent', 'dotfiles', 'zsh'],
                       pass_fds=(9,) if os.environ.get('ONE_BITE_LOCKED') == '1' else (), check=True, timeout=60)
        if not integration_status(cli) or not helpers_healthy(helpers):
            raise ValueError('Kiro Zsh loader contract changed or installation is incomplete; update setup')
    action = 'checked' if verify else ('installed-or-updated' if links or not installed or preference_changed else 'skipped')
    print(action)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    configure(Path.home(), args.app, args.verify)


if __name__ == '__main__':
    main()
