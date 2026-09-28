#!/usr/bin/env python3
"""Explain the remaining human steps using only this session's prepared packages."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import tempfile

ROOT = Path(__file__).resolve().parents[1]
APPS = {
    'docker-desktop': ('Docker Desktop', 'Docker.app',
                       'Open Docker, complete the vendor setup, and wait for the Docker engine to start.'),
    'google-chrome': ('Google Chrome', 'Google Chrome.app',
                      'Open Chrome from Applications; sign in if wanted and choose the default browser yourself.'),
    'chatgpt': ('ChatGPT / Codex desktop app', 'ChatGPT.app or Codex.app from the mounted image',
                'Open the installed app from Applications, sign in, and approve permissions as needed.'),
    'kiro': ('Kiro IDE', 'Kiro.app',
             'Open Kiro from Applications and complete sign-in and first-use setup. Initialize the IDE and Kiro CLI separately.'),
    'claude-desktop': ('Claude Desktop', 'Claude.app',
                       'Open Claude from Applications and sign in. Complete desktop and Claude Code CLI sign-in separately.'),
}


def read_json(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def package_path(directory, record, prefix, extension):
    """Never turn an unrelated/stale report or an escaping filename into an open command."""
    name = record.get('filename') if isinstance(record, dict) else None
    if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', name)
            or not name.startswith(prefix) or not name.endswith(extension)):
        return None
    path = directory / name
    return path if path.is_file() and not path.is_symlink() else None


def instructions(run_dir, config_dir, home=None, root=ROOT):
    result = read_json(run_dir / 'result.json', {})
    if result.get('mode') != 'install':
        return ''
    home = (home or Path.home()).resolve()
    directory = home / 'Downloads/1bite'
    complete = result.get('status') == 'success'
    claude = result.get('with_claude') is True
    docker = result.get('with_docker') is True
    pending = list(dict.fromkeys(name for name in result.get('manual_steps', [])
                                if name in (*APPS, 'doubao-input-installer', 'sogou-installer',
                                            'kiro-cli-onboarding', 'powerlevel10k-configure')
                                and (name != 'claude-desktop' or claude)
                                and (name != 'docker-desktop' or docker)))
    rows = read_json(run_dir / 'desktop-installers.json', [])
    packages = {row.get('component'): row for row in rows if isinstance(row, dict)} if isinstance(rows, list) else {}
    lines = []
    downloads = [name for name in pending if name not in ('kiro-cli-onboarding', 'powerlevel10k-configure')]
    if downloads:
        lines += ['[MANUAL] These packages are ready, but you must still install them:',
                  'A completed download does not mean the application is installed. Complete each item below; the commands are shown for you to copy and are not run automatically.',
                  'Open the package folder:', '  ' + shlex.join(['open', str(directory)])]
        if not complete:
            lines += ['This run did not finish. You can install the packages already listed below, then fix the earlier error and rerun the original command.']
        for number, name in enumerate(downloads, 1):
            if name == 'doubao-input-installer':
                record = read_json(run_dir / 'doubao-input-installer.json', {})
                path = package_path(directory, record, 'DoubaoInput-', '.zip')
                title = 'Doubao Input Method'
            elif name == 'sogou-installer':
                record = read_json(run_dir / 'sogou-installer.json', {})
                path = package_path(directory, record, 'SogouInput-', '.zip')
                title = 'Sogou Input Method'
            else:
                path = package_path(directory, packages.get(name), name + '-', '.dmg')
                title = APPS[name][0]
            lines += ['', f'{number}. {title}']
            if path:
                lines += ['   Package: ' + str(path), '   Open command: ' + shlex.join(['open', str(path)])]
            else:
                lines += ['   This run cannot locate the package. Check the download folder above or rerun the original command to prepare it again.']
            if name == 'doubao-input-installer':
                lines += ['   1) Double-click the ZIP to extract it, then open the included Doubao installer application and follow its prompts.',
                          '   2) Log out and back in if requested so macOS can load the new input method.',
                          '   3) Open System Settings > Keyboard > Text Input > Edit and add Doubao Input Method.',
                          '   4) Switch to Doubao from the menu bar, grant microphone access when you choose voice input, and test both typing and voice input in an editor.']
            elif name == 'sogou-installer':
                lines += ['   1) Double-click the ZIP to extract it, then open the official installer and follow its steps.',
                          '   2) Open System Settings > Keyboard > Text Input > Edit and add Sogou.',
                          '   3) Switch to Sogou from the menu bar and test text input in an editor.']
            else:
                lines += ['   1) Open the DMG, drag ' + APPS[name][1] + ' into Applications, and wait for the copy to finish.',
                          '   2) Eject the installer disk from the Finder sidebar, then open the copied app from Applications.',
                          '   3) ' + APPS[name][2]]
        lines += ['', 'If macOS asks to replace an app with the same name, quit the old app first and confirm only if you intend to update it.']
    if complete:
        lines += ['', '[MANUAL] First use and sign-in (skip completed items):',
                  '- Quit and reopen iTerm2, then open a new window with the default One Bite profile so its font and shell settings take effect.',
                  '- Zsh: ~/.zshrc and ~/.zprofile remain your files. One Bite settings live separately in ~/.config/1bite/zsh/.',
                  '  The installer changes only one recognized guarded loader in each entry file and leaves all other lines in order.',
                  '  Changed entry files have adjacent .backup-* copies. Put personal aliases and overrides after the One Bite loader.',
                  '  Inspect the loaders with: grep -nF ".config/1bite" ~/.zshrc ~/.zprofile',
                  '  An unchanged rerun only reports that the loader is current. Unknown loader syntax stops for manual review.',
                  '  Restart a non-iTerm shell with exec zsh. In iTerm2, open a new window with the One Bite profile so its updated font and shell settings take effect.',
                  '  If a dotfile manager owns either file, add the printed source line to its source file; do not replace the whole file.',
                  '- Go: run go env GOPATH GOBIN. The installer exports the effective GOPATH and adds GOBIN or each GOPATH/bin to PATH.',
                  '- Docker: new shells default DOCKER_DEFAULT_PLATFORM to linux/amd64 for portable Linux builds; set a project-specific value when another architecture is required.',
                  '- Git: shared aliases, delta/VS Code, push/pull defaults, and the global ignore file are configured. Identity and credentials are never copied from another Mac.',
                  '  Run git config --global --get user.name and git config --global --get user.email to review your identity.',
                  '  If either is empty, use your own values with git config --global user.name "Your Name" and git config --global user.email "you@example.com".',
                  '- Codex CLI: run codex in a new terminal and complete sign-in.']
        if 'powerlevel10k-configure' in pending:
            lines += ['- Powerlevel10k: in iTerm2, open a new window with Profiles > One Bite before starting the wizard; existing windows keep their previous font.',
                      '  The One Bite profile uses the installed MesloLGS Nerd Font. Run p10k configure in that new window if the wizard does not open.',
                      '  If P10k still offers a font download, cancel it, restart iTerm2, and verify that Settings > Profiles > One Bite > Text shows MesloLGS Nerd Font.',
                      '  The wizard creates your personal ~/.p10k.zsh. Existing explicit themes stay unchanged until you switch them yourself.']
        if claude:
            lines += ['- Claude Code CLI: run claude in a new terminal and complete sign-in.']
        if docker and 'docker-desktop' not in downloads:
            lines += ['- Docker Desktop: run open -a Docker, complete first-run setup, and wait for the engine to start.']
    if complete or 'kiro-cli-onboarding' in pending:
        lines += ['- Kiro CLI: run kiro-cli launch in a new terminal and complete the vendor sign-in and shell integration.',
                  '  If the command is not found, run open -a "Kiro CLI" to finish onboarding, then open a new terminal and retry.',
                  '  Run kiro-cli doctor --all for diagnostics. Approve only the system permissions you need.']
    if complete:
        command = ['/bin/bash', str(root / '1bite'), '--verify']
        if claude:
            command.append('--with-claude')
        if docker:
            command.append('--with-docker')
        if result.get('desktop_mode') == 'managed':
            command.append('--managed-desktop')
        if config_dir.resolve() != (root / 'config').resolve():
            command += ['--config-dir', str(config_dir.resolve())]
        command += ['--log-dir', str(run_dir.parent)]
        confirmations = []
        if 'doubao-input-installer' in pending:
            confirmations.append('Doubao installation, input-source switching, microphone permission, and voice input')
        if 'sogou-installer' in pending:
            confirmations.append('Sogou installation and input-source switching')
        confirmations += ['GUI sign-in', 'system permissions']
        lines += ['', '[CHECK] After installation and first launch, run this exact command in a new terminal:',
                  '  ' + shlex.join(command),
                  'This checks actual installations; a downloaded DMG without an installed app still fails. Preserve any custom directory environment variables used during installation.']
        if docker:
            lines += ['After the Docker engine starts, check container execution separately:',
                      '  ' + shlex.join(['/bin/bash', str(root / '1bite'), '--docker-smoke', '--log-dir', str(run_dir.parent)])]
        lines += [', '.join(confirmations) + ' still require manual confirmation.']
    return '\n'.join(lines).strip() + '\n' if lines else ''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--config-dir', type=Path, required=True)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    text = instructions(run_dir, args.config_dir)
    if not text:
        return
    destination = run_dir / 'manual-steps.txt'
    fd, temporary = tempfile.mkstemp(prefix='.manual-', dir=run_dir)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(text)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    print(text, end='')
    print('\nInstructions saved: ' + str(destination))


if __name__ == '__main__':
    main()
