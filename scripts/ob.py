#!/usr/bin/env python3
"""Open an Obsidian vault or create one from the reviewed One Bite starter."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


DEFAULT_TEMPLATE = Path.home() / '.config/1bite/obsidian-vault'
REQUIRED = {
    '.gitignore',
    '.obsidian/app.json',
    '.obsidian/appearance.json',
    '.obsidian/core-plugins.json',
    '.obsidian/graph.json',
    '.obsidian/snippets/wide.css',
    '.obsidian/templates.json',
    '.obsidian/themes/Tokyo Night/LICENSE',
    '.obsidian/themes/Tokyo Night/manifest.json',
    '.obsidian/themes/Tokyo Night/theme.css',
    '_attachments/.gitkeep',
    '_templates/.gitkeep',
}
PRIVATE_MARKERS = ('/users/', '/home/', 'file://', 'dropbox')
EXCLUDED_NAMES = {'workspace.json', 'workspaces.json', '.ds_store'}


def template_files(template):
    if template.is_symlink() or not template.is_dir():
        raise ValueError(f'Template directory is missing or unsafe: {template}')
    files = {}
    for path in sorted(template.rglob('*')):
        relative = path.relative_to(template)
        if path.is_symlink():
            raise ValueError(f'Template contains a symlink: {relative}')
        if path.is_dir():
            continue
        if not path.is_file() or path.name.lower() in EXCLUDED_NAMES:
            raise ValueError(f'Template contains an unsupported entry: {relative}')
        content = path.read_bytes()
        if len(content) > 1_000_000:
            raise ValueError(f'Template file is too large: {relative}')
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError as error:
            raise ValueError(f'Template file is not UTF-8 text: {relative}') from error
        lowered = text.lower()
        if any(marker in lowered for marker in PRIVATE_MARKERS):
            raise ValueError(f'Template contains a private marker: {relative}')
        if path.suffix == '.json':
            json.loads(text)
        files[str(relative)] = content
    missing = sorted(REQUIRED - files.keys())
    if missing:
        raise ValueError('Template is incomplete: ' + ', '.join(missing))
    return files


def reject_symlink_ancestors(path):
    current = Path(path.anchor)
    system_aliases = {Path('/etc'), Path('/tmp'), Path('/var')}
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            if current in system_aliases:
                current = current.resolve()
            else:
                raise ValueError(f'Refusing a path with a symlink component: {current}')


def destination_path(value):
    raw = Path(value).expanduser()
    if '..' in raw.parts:
        raise ValueError('Destination must not contain parent traversal')
    path = Path(os.path.abspath(raw))
    home = Path.home().resolve()
    if path == Path('/') or path == home:
        raise ValueError('Choose a new vault directory below your home or project folder')
    reject_symlink_ancestors(path)
    if path.exists() or path.is_symlink():
        raise ValueError(f'Destination already exists; no files were changed: {path}')
    return path


def create_vault(template, destination):
    files = template_files(template)
    destination = destination_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    reject_symlink_ancestors(destination.parent)
    staging = Path(tempfile.mkdtemp(prefix=f'.{destination.name}.1bite-', dir=destination.parent))
    try:
        for relative, content in files.items():
            target = staging / relative
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            target.write_bytes(content)
            target.chmod(0o644)
        for directory in sorted((path for path in staging.rglob('*') if path.is_dir()), reverse=True):
            directory.chmod(0o755)
        staging.chmod(0o755)
        if destination.exists() or destination.is_symlink():
            raise ValueError(f'Destination appeared during creation; no files were changed: {destination}')
        os.replace(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return destination


def existing_vault(value=None):
    if value is None:
        return None
    path = Path(os.path.abspath(Path(value).expanduser()))
    reject_symlink_ancestors(path)
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f'Vault directory does not exist or is unsafe: {path}')
    return path


def open_vault(value=None):
    vault = existing_vault(value)
    command = ['open', '-a', 'Obsidian']
    if vault is not None:
        command.append(str(vault))
    subprocess.run(command, check=True)
    return vault


def create_main(argv):
    parser = argparse.ArgumentParser(description='Create a new Obsidian vault from the One Bite starter.')
    parser.add_argument('directory', type=Path, help='new vault directory; it must not already exist')
    parser.add_argument('--template-dir', type=Path, default=DEFAULT_TEMPLATE,
                        help=argparse.SUPPRESS)
    parser.add_argument('--open', action='store_true', help='open the new vault in Obsidian')
    args = parser.parse_args(argv)
    vault = create_vault(args.template_dir.expanduser(), args.directory)
    print(f'Created Obsidian vault: {vault}')
    if args.open:
        subprocess.run(['open', '-a', 'Obsidian', str(vault)], check=True)
    else:
        print(f'Open it with: open -a Obsidian {shlex_quote(str(vault))}')
    return 0


def open_main(argv):
    parser = argparse.ArgumentParser(
        description='Open Obsidian, optionally selecting an existing vault directory.')
    parser.add_argument('directory', nargs='?', type=Path,
                        help='existing vault directory; omit it to open Obsidian normally')
    args = parser.parse_args(argv)
    vault = open_vault(args.directory)
    if vault is None:
        print('Opened Obsidian.')
    else:
        print(f'Opened Obsidian vault: {vault}')
    return 0


def main(argv=None, command_name=None):
    command_name = command_name or Path(sys.argv[0]).name
    if command_name == 'ob':
        return open_main(argv)
    if command_name in {'obn', 'ob.py'}:
        return create_main(argv)
    raise ValueError(f'Unsupported Obsidian command name: {command_name}')


def shlex_quote(value):
    import shlex
    return shlex.quote(value)


if __name__ == '__main__':
    raise SystemExit(main())
