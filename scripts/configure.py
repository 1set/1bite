#!/usr/bin/env python3
"""Install public templates; preserve personal settings and back up entry files."""

import argparse
import json
import os
from pathlib import Path
import plistlib
import pwd
import re
import shutil
import subprocess
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
SOURCE_LINE = '[ -f "$HOME/.config/1bite/shell.zsh" ] && source "$HOME/.config/1bite/shell.zsh"'
ENV_SOURCE_LINE = '[ -f "$HOME/.config/1bite/env.zsh" ] && source "$HOME/.config/1bite/env.zsh"'
SHELL_SOURCE_LINES = (SOURCE_LINE, 'source "$HOME/.config/1bite/shell.zsh"',
                      'source ~/.config/1bite/shell.zsh',
                      '. "$HOME/.config/1bite/shell.zsh"',
                      '[[ -f "$HOME/.config/1bite/shell.zsh" ]] && source "$HOME/.config/1bite/shell.zsh"')
ENV_SOURCE_LINES = (ENV_SOURCE_LINE, 'source "$HOME/.config/1bite/env.zsh"',
                    'source ~/.config/1bite/env.zsh', '. "$HOME/.config/1bite/env.zsh"',
                    '[[ -f "$HOME/.config/1bite/env.zsh" ]] && source "$HOME/.config/1bite/env.zsh"')
SHELL_LOADER_FRAGMENTS = ('.config/1bite/shell.zsh', '.config/1bite/env.zsh')
VIM_SOURCE_LINE = "if filereadable(expand('$HOME/.config/1bite/vimrc')) | execute 'source ' . fnameescape(expand('$HOME/.config/1bite/vimrc')) | endif"
VIM_SOURCE_LINES = (VIM_SOURCE_LINE,)
PROFILE_PATH = Path('Library/Application Support/iTerm2/DynamicProfiles/1bite.json')
PROFILE_BACKUP_PATH = PROFILE_PATH.parent.parent / '1bite-backups'
ITERM_DEFAULT_STATE_PATH = Path('.config/1bite/iterm2-default.json')
ITERM_PREFERENCES_PATH = Path('Library/Preferences/com.googlecode.iterm2.plist')
ITERM_DEFAULT_KEY = 'Default Bookmark Guid'
ITERM_GUID_PATTERN = re.compile(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}')
VSCODE_PATH = Path('Library/Application Support/Code/User/settings.json')
KIRO_PATH = Path('.kiro/settings/permissions.yaml')
GIT_IGNORE_PATH = Path('.config/1bite/gitignore-global')
OBSIDIAN_TEMPLATE_PATH = Path('.config/1bite/obsidian-vault')
OBSIDIAN_COMMAND_PATHS = (Path('.local/bin/ob'), Path('.local/bin/obn'))
ZSH_MODULES = ('framework.zsh', 'options.zsh', 'tools.zsh', 'development.zsh',
               'utilities.zsh', 'media.zsh', 'git-functions.zsh', 'terminal.zsh')
DOCKER_ZSH_COMPLETIONS = {
    '_docker': Path('/Applications/Docker.app/Contents/Resources/etc/docker.zsh-completion'),
    '_docker-compose': Path('/Applications/Docker.app/Contents/Resources/etc/docker-compose.zsh-completion'),
}
GIT_DEFAULT_SECTIONS = {
    'alias', 'branch', 'color', 'commit', 'core', 'delta', 'diff', 'difftool', 'fetch', 'help', 'init',
    'interactive', 'merge', 'mergetool', 'pull', 'push', 'rebase', 'rerere', 'tag',
}
GIT_PRIVATE_SECTIONS = {'credential', 'filter', 'http', 'include', 'includeif', 'user', 'url'}
OBSIDIAN_REQUIRED = {
    '.gitignore', '.obsidian/app.json', '.obsidian/appearance.json',
    '.obsidian/core-plugins.json', '.obsidian/graph.json',
    '.obsidian/snippets/wide.css', '.obsidian/templates.json',
    '.obsidian/themes/Tokyo Night/LICENSE',
    '.obsidian/themes/Tokyo Night/manifest.json',
    '.obsidian/themes/Tokyo Night/theme.css', '_attachments/.gitkeep',
    '_templates/.gitkeep',
}


def write(path, content, preserve=False, backup_dir=None):
    if path.is_symlink():
        raise ValueError(f'Refusing to replace symlink: {path}')
    if path.exists() and (preserve or path.read_bytes() == content):
        print(f'Preserved: {path}')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = backup_dir or path.parent
    if staging.is_symlink():
        raise ValueError(f'Refusing symlink staging directory: {staging}')
    staging.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.exists():
        fd, backup = tempfile.mkstemp(prefix=path.name + '.backup-', dir=staging)
        os.close(fd)
        shutil.copy2(path, backup)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=staging)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(f'Configured: {path}')


def update_source_line(content, canonical, recognized):
    """Canonicalize one exact managed loader while preserving all other lines."""
    output, found = [], False
    for row in content.splitlines(keepends=True):
        body = row.rstrip('\r\n')
        ending = row[len(body):]
        if body in recognized:
            if not found:
                output.append(canonical + (ending or '\n'))
                found = True
        else:
            output.append(row)
    if found:
        return ''.join(output)
    if not content:
        separator = ''
    elif content.endswith('\n\n'):
        separator = ''
    elif content.endswith('\n'):
        separator = '\n'
    else:
        separator = '\n\n'
    return content + separator + canonical + '\n'


def unrecognized_source_line(content, recognized):
    """Find a likely loader that needs a human decision instead of duplicating it."""
    for number, row in enumerate(content.splitlines(), 1):
        body = row.strip()
        if not body or body.startswith('#') or body in recognized:
            continue
        if not any(fragment in body for fragment in SHELL_LOADER_FRAGMENTS):
            continue
        tokens = body.replace(';', ' ').replace('&&', ' ').replace('||', ' ').split()
        if 'source' in tokens or '.' in tokens:
            return number
    return None


def homebrew_prefix():
    prefix = Path(os.environ.get('HOMEBREW_PREFIX', '/opt/homebrew'))
    if not prefix.is_absolute():
        raise ValueError('HOMEBREW_PREFIX must be an absolute path')
    return prefix


def broken_zsh_completion_links(prefix=None):
    """Return dangling links that make compinit print during shell startup."""
    directory = (prefix or homebrew_prefix()) / 'share/zsh/site-functions'
    if not directory.exists():
        return []
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f'Homebrew Zsh completion path is not a regular directory: {directory}')
    try:
        return [path for path in sorted(directory.iterdir()) if path.is_symlink() and not path.exists()]
    except OSError as error:
        raise ValueError(f'Cannot inspect Homebrew Zsh completions: {directory}') from error


def repair_broken_zsh_completions(prefix=None):
    """Remove only dangling links created by Docker Desktop's Homebrew cask."""
    prefix = prefix or homebrew_prefix()
    for path in broken_zsh_completion_links(prefix):
        expected = DOCKER_ZSH_COMPLETIONS.get(path.name)
        if expected is None or Path(os.path.realpath(path)) != expected:
            raise ValueError(
                f'Broken Zsh completion symlink is not owned by One Bite: {path}. '
                'Repair its Homebrew package or remove that one link with its original manager, then rerun.')
        try:
            path.unlink()
        except OSError as error:
            raise ValueError(
                f'Cannot remove broken Docker Desktop completion link: {path}. '
                'Repair it with the account that owns the Homebrew prefix, then rerun.') from error
        print(f'Repaired: removed broken Docker Desktop completion link: {path}')


def verify_zsh_completions(prefix=None):
    broken = broken_zsh_completion_links(prefix)
    if broken:
        raise ValueError(
            f'Broken Zsh completion symlink causes compinit startup output: {broken[0]}. '
            'Run ./1bite --configure-only to repair known Docker Desktop links; '
            'repair any other link with its original package manager.')


def relocate_profile_artifacts(home):
    """Keep backups and interrupted writes outside iTerm2's watched directory."""
    profile = home / PROFILE_PATH
    destination = home / PROFILE_BACKUP_PATH
    if destination.is_symlink():
        raise ValueError(f'Refusing symlink backup directory: {destination}')
    artifacts = list(sorted(profile.parent.glob(profile.name + '.backup-*')))
    temporary_prefix = '.' + profile.name
    artifacts.extend(sorted(path for path in profile.parent.glob(temporary_prefix + '*')
                            if len(path.name) == len(temporary_prefix) + 8
                            and set(path.name[len(temporary_prefix):])
                            <= set('abcdefghijklmnopqrstuvwxyz0123456789_')))
    for path in artifacts:
        if not path.is_file() or path.is_symlink() or (destination / path.name).exists():
            raise ValueError(f'Refusing unsafe or colliding iTerm2 profile artifact: {path}')
    if artifacts:
        destination.mkdir(mode=0o700, parents=True, exist_ok=True)
        for path in artifacts:
            path.rename(destination / path.name)
            print(f'Relocated iTerm2 backup: {path.name}')


def validate(claude, codex, profile):
    if not isinstance(json.loads(claude), dict):
        raise ValueError('Claude settings must be a JSON object')
    tomllib.loads(codex)
    data = json.loads(profile)
    if not isinstance(data, dict) or len(data.get('Profiles', [])) != 1:
        raise ValueError('Expected one iTerm2 dynamic profile')
    item = data['Profiles'][0]
    if not item.get('Guid') or not item.get('Name') or not item.get('Keyboard Map'):
        raise ValueError('iTerm2 profile needs Guid, Name and Keyboard Map')
    if not ITERM_GUID_PATTERN.fullmatch(item['Guid']):
        raise ValueError('iTerm2 profile Guid must be a UUID')
    if 'Default Bookmark' in item:
        raise ValueError('Dynamic Profiles cannot select the iTerm2 default with Default Bookmark')


def live_iterm_preferences(home):
    return (Path('/usr/bin/defaults').is_file()
            and home.resolve() == Path(pwd.getpwuid(os.getuid()).pw_dir).resolve())


def read_iterm_default(home):
    preference = home / ITERM_PREFERENCES_PATH
    if preference.is_symlink() or (preference.exists() and not preference.is_file()):
        raise ValueError(f'Refusing unsafe iTerm2 preferences file: {preference}')
    if preference.exists() and not os.access(preference, os.R_OK | os.W_OK):
        raise ValueError(f'iTerm2 preferences are not readable and writable: {preference}')
    defaults = Path('/usr/bin/defaults')
    if live_iterm_preferences(home):
        result = subprocess.run([defaults, 'read', 'com.googlecode.iterm2', ITERM_DEFAULT_KEY],
                                text=True, capture_output=True)
        return result.stdout.strip() if result.returncode == 0 else None
    if not preference.exists():
        return None
    try:
        value = plistlib.loads(preference.read_bytes()).get(ITERM_DEFAULT_KEY)
    except (OSError, plistlib.InvalidFileException) as error:
        raise ValueError(f'Cannot read iTerm2 preferences: {preference}') from error
    return value if isinstance(value, str) and value else None


def write_iterm_default(home, guid):
    preference = home / ITERM_PREFERENCES_PATH
    preference.parent.mkdir(parents=True, exist_ok=True)
    defaults = Path('/usr/bin/defaults')
    if live_iterm_preferences(home):
        subprocess.run([defaults, 'write', 'com.googlecode.iterm2',
                        ITERM_DEFAULT_KEY, '-string', guid], check=True)
        return
    data = {}
    if preference.exists():
        try:
            data = plistlib.loads(preference.read_bytes())
        except (OSError, plistlib.InvalidFileException) as error:
            raise ValueError(f'Cannot read iTerm2 preferences: {preference}') from error
    data[ITERM_DEFAULT_KEY] = guid
    write(preference, plistlib.dumps(data))


def configure_iterm_default(home, guid):
    """Own the default until the user explicitly selects a different profile."""
    state_path = home / ITERM_DEFAULT_STATE_PATH
    if state_path.is_symlink():
        raise ValueError(f'Refusing to replace symlink: {state_path}')
    current = read_iterm_default(home)
    if current is not None and not ITERM_GUID_PATTERN.fullmatch(current):
        raise ValueError('Current iTerm2 default profile Guid is invalid; review iTerm2 preferences')
    state = None
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except (OSError, ValueError) as error:
            raise ValueError(f'Invalid managed iTerm2 default state: {state_path}') from error
        if (not isinstance(state, dict) or state.get('schema_version') != 1
                or not isinstance(state.get('managed_guid'), str)
                or not ITERM_GUID_PATTERN.fullmatch(state['managed_guid'])
                or state.get('original_guid') is not None
                and (not isinstance(state.get('original_guid'), str)
                     or not ITERM_GUID_PATTERN.fullmatch(state['original_guid']))):
            raise ValueError(f'Invalid managed iTerm2 default state: {state_path}')
        if current is not None and current not in (state['managed_guid'], guid):
            print('Preserved: iTerm2 default profile was changed after One Bite configured it.')
            state['managed_guid'] = guid
            content = (json.dumps(state, indent=2) + '\n').encode()
            write(state_path, content, backup_dir=home / '.config/1bite/backups')
            return
    else:
        state = {'schema_version': 1, 'original_guid': current, 'managed_guid': guid}
    if current != guid:
        write_iterm_default(home, guid)
        if read_iterm_default(home) != guid:
            raise ValueError('iTerm2 did not retain the One Bite default profile Guid')
        print('Configured: One Bite is the iTerm2 default profile after iTerm2 is reopened.')
    else:
        print('Preserved: One Bite is already the iTerm2 default profile.')
    state['managed_guid'] = guid
    content = (json.dumps(state, indent=2) + '\n').encode()
    write(state_path, content, backup_dir=home / '.config/1bite/backups')


def verify_iterm_default(home, guid):
    state_path = home / ITERM_DEFAULT_STATE_PATH
    if state_path.is_symlink() or not state_path.is_file():
        raise ValueError('Managed iTerm2 default state is missing; rerun --configure-only')
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError) as error:
        raise ValueError(f'Invalid managed iTerm2 default state: {state_path}') from error
    if (state.get('schema_version') != 1 or state.get('managed_guid') != guid
            or state.get('original_guid') is not None
            and (not isinstance(state.get('original_guid'), str)
                 or not ITERM_GUID_PATTERN.fullmatch(state['original_guid']))):
        raise ValueError('Managed iTerm2 default state differs from the selected Dynamic Profile')
    current = read_iterm_default(home)
    if current == guid:
        print('One Bite is the iTerm2 default profile.')
    elif current is not None and ITERM_GUID_PATTERN.fullmatch(current):
        print('iTerm2 default profile is a preserved user override.')
    else:
        raise ValueError('iTerm2 does not have a valid default profile Guid; rerun --configure-only')


def validate_git_defaults(content):
    data = json.loads(content)
    if not isinstance(data, dict) or not data:
        raise ValueError('Git defaults must be a nonempty JSON object')
    for key, value in data.items():
        if (not isinstance(key, str) or not isinstance(value, str) or not value
                or not all(part and part.replace('-', '').isalnum() for part in key.split('.'))):
            raise ValueError('Git defaults require dotted string keys and nonempty string values')
        section = key.split('.', 1)[0].lower()
        if section in GIT_PRIVATE_SECTIONS or section not in GIT_DEFAULT_SECTIONS:
            raise ValueError(f'Private or unsupported Git configuration section: {section}')
    lowered = content.lower()
    if any(marker in lowered for marker in ('/users/', '@users.noreply.', 'proxy', 'corp.', 'private-host')):
        raise ValueError('Git defaults contain a personal or internal marker')
    return data


def validate_git_ignore(content):
    text = content.decode()
    if not any(line.strip() and not line.lstrip().startswith('#') for line in text.splitlines()):
        raise ValueError('Git global ignore template must contain patterns')
    lowered = text.lower()
    if any(marker in lowered for marker in ('/users/', 'corp.', 'private-host', 'credential', 'token')):
        raise ValueError('Git global ignore contains a personal or internal marker')
    return content


def obsidian_template_files(config_dir):
    root = config_dir / 'obsidian-vault'
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f'Obsidian template directory is missing or unsafe: {root}')
    files = {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError(f'Obsidian template contains a symlink: {relative}')
        if path.is_dir():
            continue
        if not path.is_file() or path.name.lower() in {'workspace.json', 'workspaces.json', '.ds_store'}:
            raise ValueError(f'Obsidian template contains an unsupported entry: {relative}')
        content = path.read_bytes()
        if len(content) > 1_000_000:
            raise ValueError(f'Obsidian template file is too large: {relative}')
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError as error:
            raise ValueError(f'Obsidian template file is not UTF-8 text: {relative}') from error
        lowered = text.lower()
        if any(marker in lowered for marker in ('/users/', '/home/', 'file://', 'dropbox')):
            raise ValueError(f'Obsidian template contains a private marker: {relative}')
        if path.suffix == '.json':
            json.loads(text)
        files[relative] = content
    missing = sorted(OBSIDIAN_REQUIRED - files.keys())
    if missing:
        raise ValueError('Obsidian template is incomplete: ' + ', '.join(missing))
    return files


def validate_managed_obsidian_tree(root, expected):
    if root.is_symlink():
        raise ValueError(f'Obsidian managed template must not be a symlink: {root}')
    if not root.exists():
        return
    if not root.is_dir():
        raise ValueError(f'Obsidian managed template path is not a directory: {root}')
    allowed_directories = {str(parent) for name in expected for parent in Path(name).parents
                           if str(parent) != '.'}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError(f'Obsidian managed template contains a symlink: {relative}')
        if path.is_dir():
            if relative not in allowed_directories:
                raise ValueError(f'Obsidian managed template contains an unknown directory: {relative}')
        elif not path.is_file() or relative not in expected:
            raise ValueError(f'Obsidian managed template contains an unknown entry: {relative}')


def git_environment(home):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith('GIT_CONFIG_') and key != 'XDG_CONFIG_HOME'}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'), GIT_CONFIG_NOSYSTEM='1',
               GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0')
    return env


def inherited_lock_fd():
    try:
        os.fstat(9)
    except OSError:
        return ()
    return (9,)


def git_config(home, *args, check=True):
    result = subprocess.run(['git', 'config', '--global', '--includes', *args], text=True,
                            capture_output=True, env=git_environment(home), pass_fds=inherited_lock_fd())
    if check and result.returncode:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'unknown Git error'
        raise ValueError('Git global configuration cannot be read or updated: ' + detail)
    return result


def git_values(home):
    if not (home / '.gitconfig').exists() and not (home / '.config/git/config').exists():
        return {}
    result = git_config(home, '--null', '--list')
    values = {}
    for record in result.stdout.split('\0'):
        if not record:
            continue
        key, separator, value = record.partition('\n')
        if not separator:
            raise ValueError('Git returned a malformed global configuration entry')
        values.setdefault(key.lower(), []).append(value)
    return values


def backup_git_config(home):
    source = home / '.gitconfig'
    if not source.exists():
        return
    if source.is_symlink() or not source.is_file():
        raise ValueError(f'Refusing to update non-regular Git configuration: {source}')
    destination = home / '.config/1bite/backups'
    if destination.is_symlink():
        raise ValueError(f'Refusing symlink Git backup directory: {destination}')
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, backup = tempfile.mkstemp(prefix='gitconfig.backup-', dir=destination)
    os.close(fd)
    shutil.copy2(source, backup)
    os.chmod(backup, 0o600)
    print(f'Backed up Git configuration: {backup}')


def configure_git(home, defaults, ignore, current=None):
    current = current if current is not None else git_values(home)
    missing = [(key, value) for key, value in defaults.items() if key.lower() not in current]
    global_config = home / '.gitconfig'
    desired_ignore = defaults['core.excludesFile']
    active_ignore = current.get('core.excludesfile', [])
    if missing and global_config.is_symlink():
        raise ValueError(f'Refusing to update symlink Git configuration: {global_config}')
    if missing:
        backup_git_config(home)
    if not active_ignore or desired_ignore in active_ignore:
        write(home / GIT_IGNORE_PATH, ignore)
    else:
        print('Preserved: existing Git core.excludesFile and its contents')
    if missing:
        for key, value in missing:
            git_config(home, '--add', key, value)
    remaining = [key for key in defaults if key.lower() not in git_values(home)]
    if remaining:
        raise ValueError('Git defaults remain missing after configuration: ' + ', '.join(remaining))
    print(f'Git defaults ready: added {len(missing)}, preserved {len(defaults) - len(missing)} existing values.')


def verify_git(home, defaults, ignore):
    values = git_values(home)
    missing = [key for key in defaults if key.lower() not in values]
    if missing:
        raise ValueError('Missing Git defaults; rerun --configure-only: ' + ', '.join(missing))
    result = git_config(home, '--path', '--get', 'core.excludesFile')
    path = Path(result.stdout.strip())
    if not path.is_absolute():
        path = home / path
    if not path.is_file() or not os.access(path, os.R_OK):
        raise ValueError(f'Git global ignore file is missing or unreadable: {path}')
    managed = home / GIT_IGNORE_PATH
    if path.resolve() == managed.resolve() and path.read_bytes() != ignore:
        raise ValueError('Managed Git global ignore file differs from the selected template')
    print('Git defaults and global ignore verified; identity and credentials remain user-owned.')


def configure(home, config_dir, codex_home=None, claude_home=None, shell_home=None, with_claude=False):
    # Validate selected inputs and preserved AI files before making any changes.
    claude = (config_dir / 'claude-settings.json').read_text() if with_claude else '{}'
    codex = (config_dir / 'codex-config.toml').read_text()
    profile = (config_dir / 'iterm2-profile.json').read_text()
    shell = (config_dir / 'shell.zsh').read_bytes()
    zsh_modules = {name: (config_dir / 'zsh' / name).read_bytes() for name in ZSH_MODULES}
    environment = (config_dir / 'env.zsh').read_bytes()
    vim = (config_dir / 'vimrc').read_bytes()
    vscode = (config_dir / 'vscode-settings.json').read_bytes()
    kiro = (config_dir / 'kiro-permissions.json').read_bytes()
    git_defaults = validate_git_defaults((config_dir / 'git-defaults.json').read_text())
    git_ignore = validate_git_ignore((config_dir / 'gitignore-global').read_bytes())
    obsidian_files = obsidian_template_files(config_dir)
    obsidian_command = (ROOT / 'scripts/ob.py').read_bytes()
    current_git = git_values(home)
    if any(key.lower() not in current_git for key in git_defaults) and (home / '.gitconfig').is_symlink():
        raise ValueError(f'Refusing to update symlink Git configuration: {home / ".gitconfig"}')
    validate_kiro(kiro)
    if not isinstance(json.loads(vscode), dict):
        raise ValueError('VS Code defaults must be a JSON object')
    validate(claude, codex, profile)
    claude_path = (claude_home or home / '.claude') / 'settings.json'
    codex_path = (codex_home or home / '.codex') / 'config.toml'
    validate(
        claude_path.read_text() if with_claude and claude_path.exists() else claude,
        codex_path.read_text() if codex_path.exists() else codex,
        profile,
    )
    shell_home = shell_home or home
    zsh_directory = home / '.config/1bite/zsh'
    obsidian_directory = home / OBSIDIAN_TEMPLATE_PATH
    obsidian_command_paths = [home / path for path in OBSIDIAN_COMMAND_PATHS]
    paths = ([claude_path] if with_claude else []) + [codex_path, home / PROFILE_PATH,
             home / ITERM_DEFAULT_STATE_PATH, home / ITERM_PREFERENCES_PATH,
             home / '.config/1bite/shell.zsh', home / '.config/1bite/env.zsh',
             home / '.config/1bite/vimrc', home / '.vimrc',
             home / GIT_IGNORE_PATH, home / VSCODE_PATH, home / KIRO_PATH,
             obsidian_directory, *obsidian_command_paths,
             zsh_directory, *[zsh_directory / name for name in ZSH_MODULES],
             shell_home / '.zshrc', shell_home / '.zprofile']
    for path in paths:
        if path.is_symlink():
            if path in (shell_home / '.zshrc', shell_home / '.zprofile'):
                line = SOURCE_LINE if path.name == '.zshrc' else ENV_SOURCE_LINE
                raise ValueError(
                    f'Refusing to edit dotfile-manager symlink: {path}. Add this exact line to its '
                    f'manager-owned source file, then rerun: {line}')
            raise ValueError(f'Refusing to replace symlink: {path}')
    if zsh_directory.exists() and not zsh_directory.is_dir():
        raise ValueError(f'Managed Zsh module path is not a directory: {zsh_directory}')
    shell_entries = []
    for name in ('.zshrc', '.zprofile'):
        path = shell_home / name
        content = path.read_text() if path.exists() else ''
        if name == '.zprofile':
            recognized = (*ENV_SOURCE_LINES, *SHELL_SOURCE_LINES)
            canonical = ENV_SOURCE_LINE
        else:
            recognized = SHELL_SOURCE_LINES
            canonical = SOURCE_LINE
        conflict = unrecognized_source_line(content, recognized)
        if conflict is not None:
            raise ValueError(
                f'{path}: line {conflict} looks like an unrecognized One Bite loader. '
                f'Review it manually, keep one loader, and rerun. Expected line: {canonical}')
        shell_entries.append((path, content, canonical, recognized))
    validate_managed_obsidian_tree(obsidian_directory, obsidian_files)
    for path in (home / '.kiro', home / '.kiro/settings'):
        if path.is_symlink():
            raise ValueError(f'Refusing to configure Kiro through symlink: {path}')
    if (home / KIRO_PATH).exists():
        kiro_policy_status(home)
    repair_broken_zsh_completions()
    relocate_profile_artifacts(home)
    if with_claude:
        write(claude_path, claude.encode(), preserve=True)
    configure_git(home, git_defaults, git_ignore, current_git)
    write(codex_path, codex.encode(), preserve=True)
    write(home / PROFILE_PATH, profile.encode(), backup_dir=home / PROFILE_BACKUP_PATH)
    configure_iterm_default(home, json.loads(profile)['Profiles'][0]['Guid'])
    write(home / '.config/1bite/env.zsh', environment)
    # Publish dependencies before the loader so an upgrade never exposes a new
    # shell.zsh that points at modules which have not been installed yet.
    for name, content in zsh_modules.items():
        write(zsh_directory / name, content)
    write(home / '.config/1bite/shell.zsh', shell)
    write(home / '.config/1bite/vimrc', vim)
    obsidian_backup = home / '.config/1bite/backups/obsidian-vault'
    for relative, content in obsidian_files.items():
        destination = obsidian_directory / relative
        write(destination, content, backup_dir=obsidian_backup)
        destination.chmod(0o644)
    for obsidian_command_path in obsidian_command_paths:
        write(obsidian_command_path, obsidian_command,
              backup_dir=home / '.config/1bite/backups')
        obsidian_command_path.chmod(0o755)
    # Existing VS Code settings may be JSONC. Preserve their bytes, including comments.
    write(home / VSCODE_PATH, vscode, preserve=True)
    # JSON is valid YAML. Personal YAML policies remain byte-for-byte intact.
    write(home / KIRO_PATH, kiro, preserve=True)
    report_kiro(home)
    for path, original, canonical, recognized in shell_entries:
        content = update_source_line(original, canonical, recognized)
        write(path, content.encode())
        if content == original:
            print(f'Zsh entry unchanged: {path} already has the current One Bite loader.')
        elif original.strip():
            print(f'Zsh review: preserved existing non-empty {path} and added or updated only the recognized loader.')
            print(f'Review it against its adjacent backup: {path}.backup-*')
        else:
            print(f'Zsh entry initialized: {path} now loads the separate One Bite configuration.')
    print(f'Zsh entry files remain user-owned: {shell_home / ".zshrc"} and {shell_home / ".zprofile"}.')
    print('Managed settings live separately under ~/.config/1bite/zsh/. Put personal overrides after the One Bite loader.')
    print('Restart a non-iTerm shell safely with: exec zsh')
    print('For iTerm2, quit and reopen the app so the One Bite default profile and font take effect.')
    path = home / '.vimrc'
    content = path.read_text() if path.exists() else ''
    content = update_source_line(content, VIM_SOURCE_LINE, VIM_SOURCE_LINES)
    write(path, content.encode())


def validate_kiro(content):
    data = json.loads(content)
    capabilities = {'all', 'builtin', 'filesystem', 'fs_read', 'fs_write', 'shell', 'web_fetch',
                    'web_search', 'mcp', 'subagent', 'skill', 'power', 'context', 'diagnostics', 'sandbox_network'}
    if not isinstance(data, dict) or set(data) != {'rules'} or not isinstance(data['rules'], list) or not data['rules']:
        raise ValueError('Kiro permissions must contain a nonempty rules array')
    for rule in data['rules']:
        if (not isinstance(rule, dict) or not {'capability', 'effect'} <= rule.keys()
                or not rule.keys() <= {'capability', 'effect', 'match', 'exclude'}
                or not isinstance(rule['capability'], str) or rule['capability'] not in capabilities
                or not isinstance(rule['effect'], str) or rule['effect'] not in {'ask', 'deny', 'allow'}):
            raise ValueError('Invalid Kiro permission rule')
        for key in ('match', 'exclude'):
            if key in rule and (not isinstance(rule[key], list) or not rule[key]
                                or not all(isinstance(value, str) and value for value in rule[key])):
                raise ValueError('Kiro match/exclude must be nonempty arrays of patterns')


def kiro_policy_status(home):
    content = (home / KIRO_PATH).read_bytes()
    if not content.strip():
        raise ValueError('Kiro permission file is empty; review it before using the agent')
    return ('default-ask' if content == (ROOT / 'config/kiro-permissions.json').read_bytes()
            else 'custom-unreviewed')


def report_kiro(home):
    if kiro_policy_status(home) == 'default-ask':
        print('Kiro permission template: all capabilities ask (requires IDE 1.x; approve inside Kiro).')
    else:
        print('Kiro custom policy preserved, not audited by setup. Review effective permissions inside Kiro before use.')


def verify(home, codex_home=None, claude_home=None, shell_home=None, with_claude=False, config_dir=ROOT / 'config'):
    verify_zsh_completions()
    validate(((claude_home or home / '.claude') / 'settings.json').read_text() if with_claude else '{}',
             ((codex_home or home / '.codex') / 'config.toml').read_text(),
             (home / PROFILE_PATH).read_text())
    verify_iterm_default(home, json.loads((home / PROFILE_PATH).read_text())['Profiles'][0]['Guid'])
    if list((home / PROFILE_PATH).parent.glob('1bite.json.backup-*')):
        raise ValueError('iTerm2 backup files remain in DynamicProfiles; rerun --configure-only to relocate them')
    managed = home / '.config/1bite'
    obsidian_files = obsidian_template_files(config_dir)
    obsidian_directory = home / OBSIDIAN_TEMPLATE_PATH
    validate_managed_obsidian_tree(obsidian_directory, obsidian_files)
    for relative, content in obsidian_files.items():
        path = obsidian_directory / relative
        if path.is_symlink() or not path.is_file() or path.read_bytes() != content:
            raise ValueError(f'Managed Obsidian template differs from selected template: {relative}')
    for relative in OBSIDIAN_COMMAND_PATHS:
        obsidian_command = home / relative
        if (obsidian_command.is_symlink() or not obsidian_command.is_file()
                or obsidian_command.read_bytes() != (ROOT / 'scripts/ob.py').read_bytes()
                or not os.access(obsidian_command, os.X_OK)):
            raise ValueError(f'Managed Obsidian command differs from the release: {obsidian_command}')
    selected = {'shell.zsh': config_dir / 'shell.zsh', 'env.zsh': config_dir / 'env.zsh'}
    selected.update({'zsh/' + name: config_dir / 'zsh' / name for name in ZSH_MODULES})
    for relative, template in selected.items():
        path = managed / relative
        if path.is_symlink() or not path.is_file() or path.read_bytes() != template.read_bytes():
            raise ValueError(f'Managed shell configuration differs from selected template: {relative}')
    if not (home / VSCODE_PATH).is_file():
        raise ValueError('Missing VS Code configuration')
    vim = home / '.config/1bite/vimrc'
    vim_entry = home / '.vimrc'
    if vim.is_symlink() or vim_entry.is_symlink():
        raise ValueError('Vim configuration files must not be symlinks')
    if not vim.is_file() or vim.read_bytes() != (config_dir / 'vimrc').read_bytes():
        raise ValueError('Managed Vim configuration differs from the selected template')
    if any(path.is_symlink() for path in (home / '.kiro', home / '.kiro/settings', home / KIRO_PATH)):
        raise ValueError('Kiro permission file must not be a symlink')
    verify_git(home, validate_git_defaults((config_dir / 'git-defaults.json').read_text()),
               validate_git_ignore((config_dir / 'gitignore-global').read_bytes()))
    report_kiro(home)
    for name in ('.zshrc', '.zprofile'):
        line = ENV_SOURCE_LINE if name == '.zprofile' else SOURCE_LINE
        if ((shell_home or home) / name).read_text().splitlines().count(line) != 1:
            raise ValueError(f'{name}: expected exactly one configuration source line')
    if vim_entry.read_text().splitlines().count(VIM_SOURCE_LINE) != 1:
        raise ValueError('.vimrc: expected exactly one configuration source line')
    print('Configuration files verified.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config-dir', type=Path, default=ROOT / 'config')
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--with-claude', action='store_true', default=os.environ.get('ONE_BITE_WITH_CLAUDE') == 'true')
    args = parser.parse_args()
    # Resolve overrides only at the CLI boundary; tests that pass a temporary home stay isolated.
    directories = {'with_claude': args.with_claude}
    for variable, key in [('CODEX_HOME', 'codex_home'), ('CLAUDE_CONFIG_DIR', 'claude_home'),
                          ('ZDOTDIR', 'shell_home')]:
        if variable == 'CLAUDE_CONFIG_DIR' and not args.with_claude:
            continue
        if os.environ.get(variable):
            directory = Path(os.environ[variable]).expanduser()
            if not directory.is_absolute():
                raise ValueError(f'{variable} must be an absolute path')
            directories[key] = directory
    if args.verify:
        verify(Path.home(), config_dir=args.config_dir, **directories)
    else:
        configure(Path.home(), args.config_dir, **directories)


if __name__ == '__main__':
    main()
