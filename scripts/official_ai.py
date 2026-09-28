#!/usr/bin/env python3
"""Install missing AI tools from vendor sources; update only recorded installations."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import quote, urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
APPS = {
    'claude-desktop': ('Claude.app', 'com.anthropic.claudefordesktop', ('Claude.app',)),
    'chatgpt': ('ChatGPT.app', 'com.openai.codex', ('ChatGPT.app', 'Codex.app')),
    'kiro': ('Kiro.app', 'dev.kiro.desktop', ('Kiro.app',)),
    'kiro-cli': ('Kiro CLI.app', 'com.amazon.codewhisperer', ('Kiro CLI.app',)),
}
SPARKLE = '{http://www.andymatuschak.org/xml-namespaces/sparkle}'
APPLICATIONS = Path('/Applications')


def sources(root=ROOT):
    return {name: url for name, kind, url in
            (line.split('\t') for line in (root / 'config/sources.tsv').read_text().splitlines())}


def version_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+(?:\.\d+)+', value):
        raise ValueError('Unsupported official version metadata')
    parts = tuple(map(int, value.split('.')))
    return parts + (0,) * max(0, 8 - len(parts))


def official_url(url, prefix):
    parsed = urlsplit(url)
    if (not url.startswith(prefix) or parsed.scheme != 'https' or parsed.username or parsed.password
            or parsed.query or parsed.fragment or '..' in parsed.path.split('/')):
        raise ValueError('Unexpected official download URL')
    return url


def fetch_text(url):
    return subprocess.check_output([
        'curl', '--disable', '--config', str(ROOT / 'config/download.curlrc'),
        '--proto', '=https', '--proto-redir', '=https', '--fail', '--silent', '--show-error',
        '--location', '--retry', '2', '--max-time', '30', '--max-filesize', '12000000', url,
    ], text=True, timeout=120)


def release(name, catalog=None, fetch=fetch_text):
    catalog = catalog or sources()
    if name == 'claude-desktop':
        data = json.loads(fetch(catalog['claude-desktop-releases']))
        version = data['currentRelease']
        version_key(version)
        entries = [item['updateTo'] for item in data['releases'] if item.get('version') == version]
        if len(entries) != 1:
            raise ValueError('Unexpected Claude Desktop release feed')
        url = official_url(entries[0]['url'], catalog['claude-desktop-distribution'])
        suffix = url[len(catalog['claude-desktop-distribution']):]
        if not re.fullmatch(re.escape(version) + r'/Claude-[a-f0-9]+\.zip', suffix):
            raise ValueError('Unexpected Claude Desktop release filename')
        # The vendor publishes its DMG beside the ZIP named by its update feed.
        return dict(version=version, url=url[:-4] + '.dmg')
    if name == 'chatgpt':
        entries = []
        for item in ET.fromstring(fetch(catalog['chatgpt-releases'])).findall('./channel/item'):
            if item.findtext(SPARKLE + 'hardwareRequirements') != 'arm64':
                continue
            version = item.findtext(SPARKLE + 'shortVersionString')
            build = item.findtext(SPARKLE + 'version')
            enclosure = item.find('enclosure')
            if enclosure is None or not build or not build.isdecimal():
                continue
            official_url(enclosure.get('url', ''), catalog['chatgpt-distribution'])
            entries.append((version_key(version), int(build), version, build))
        if not entries:
            raise ValueError('No stable Apple Silicon ChatGPT release in official feed')
        _, _, version, build = max(entries)
        return dict(version=version, build=build, url=catalog['chatgpt-download'])
    if name == 'kiro':
        entries = []
        prefix = catalog['kiro-distribution']
        for url in re.findall(r'https://[^\s"<>\\]+', fetch(catalog['kiro'])):
            if not url.startswith(prefix):
                continue
            match = re.fullmatch(r'releases/stable/darwin-arm64/signed/(\d+\.\d+\.\d+)/kiro-ide-\1-stable-darwin-arm64\.dmg', url[len(prefix):])
            if match:
                entries.append((version_key(match[1]), match[1], official_url(url, prefix)))
        if not entries:
            raise ValueError('No stable Apple Silicon Kiro DMG on official download page')
        _, version, url = max(entries)
        return dict(version=version, url=url)
    if name == 'kiro-cli':
        data = json.loads(fetch(catalog['kiro-cli-releases']))
        version = data['version']
        version_key(version)
        entries = [item for item in data['packages'] if item.get('os') == 'macos'
                   and item.get('architecture') in ('universal', 'aarch64', 'arm64')
                   and item.get('fileType') == 'dmg' and item.get('channel') == 'stable']
        if len(entries) != 1 or entries[0]['download'] != version + '/Kiro CLI.dmg':
            raise ValueError('Unexpected Kiro CLI stable manifest')
        digest = entries[0]['sha256']
        if not re.fullmatch('[a-f0-9]{64}', digest):
            raise ValueError('Missing official Kiro CLI SHA-256')
        url = catalog['kiro-cli-distribution'] + quote(entries[0]['download'])
        return dict(version=version, url=official_url(url, catalog['kiro-cli-distribution']), sha256=digest)
    if name == 'claude':
        version = fetch(catalog['claude-releases']).strip()
    elif name == 'codex':
        data = json.loads(fetch(catalog['codex-releases']))
        version = data['tag_name'].removeprefix('rust-v')
    else:
        raise ValueError('Unknown AI component')
    version_key(version)
    return dict(version=version, url=catalog[name])


def no_symlinks(path):
    # macOS /var and /tmp are system aliases; resolve the user's home once instead.
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError('Refusing a symlink in installation or receipt destination: ' + str(item))


def receipt_path(name, home=None):
    home = (home or Path.home()).resolve()
    root = Path(os.environ.get('XDG_STATE_HOME', home / '.local/state'))
    if not root.is_absolute():
        raise ValueError('XDG_STATE_HOME must be absolute')
    return root / '1bite/official-installs' / (name + '.json')


def pending_path(name, home=None):
    return receipt_path(name, home).with_suffix('.pending.json')


def read_record(path, name, destination):
    no_symlinks(path)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if (data.get('schema_version') != 1 or data.get('component') != name
            or data.get('path') != str(destination)):
        raise ValueError('Installation record does not match destination: ' + name)
    return data


def managed(name, destination, home=None):
    # A pending transaction establishes ownership, never installation health.
    path = receipt_path(name, home)
    no_symlinks(path)
    data = json.loads(path.read_text()) if path.exists() else {}
    return bool((data.get('schema_version') == 1 and data.get('component') == name
                 and data.get('path') == str(destination))
                or read_record(pending_path(name, home), name, destination))


def write_record(path, name, destination, version, **extra):
    no_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.' + name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(dict(schema_version=1, component=name, path=str(destination), version=version, **extra), stream)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def record(name, destination, version):
    write_record(receipt_path(name), name, destination, version)


def begin_install(name, destination, version, **extra):
    write_record(pending_path(name), name, destination, version, **extra)


def inherited_lock():
    # subprocess defaults close inherited descriptors. Keep the session lock
    # alive if only the shell/Python supervisor is killed during native work.
    return (9,) if os.environ.get('ONE_BITE_LOCKED') == '1' else ()


def finish_install(name, destination, version):
    record(name, destination, version)
    pending_path(name).unlink(missing_ok=True)


def download(name, url, destination, digest=None):
    subprocess.run([
        'curl', '--disable', '--config', str(ROOT / 'config/download.curlrc'),
        '--proto', '=https', '--proto-redir', '=https', '--fail', '--show-error', '--location',
        '--retry', '3', '--output', str(destination), url,
    ], check=True)
    with destination.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest is not None and actual != digest:
        raise ValueError('Official download SHA-256 mismatch: ' + name)
    if os.environ.get('RUN_DIR'):
        with (Path(os.environ['RUN_DIR']) / 'downloads.tsv').open('a') as stream:
            stream.write(name + '\t' + actual + '\n')


def bundle_info(app):
    return plistlib.loads((app / 'Contents/Info.plist').read_bytes())


def verify_signature(name, app):
    subprocess.run(['codesign', '--verify', '--deep', '--strict', '-R',
                    '=anchor apple generic and identifier "' + APPS[name][1] + '"', str(app)], check=True)


def verify_bundle(name, app):
    info = bundle_info(app)
    if app.is_symlink() or info.get('CFBundleIdentifier') != APPS[name][1]:
        raise ValueError('Unexpected vendor application identity')
    executable = info.get('CFBundleExecutable', '')
    if not executable or Path(executable).name != executable:
        raise ValueError('Invalid application executable')
    binary = app / 'Contents/MacOS' / executable
    if not os.access(binary, os.X_OK):
        raise ValueError('Missing application executable')
    version_key(info.get('CFBundleShortVersionString'))
    verify_signature(name, app)
    subprocess.run(['lipo', str(binary), '-verify_arch', 'arm64'], check=True)
    if name == 'kiro-cli':
        for binary_name in ('kiro-cli', 'kiro-cli-chat', 'kiro-cli-term'):
            subprocess.run([str(app / 'Contents/MacOS' / binary_name), '--version'], check=True,
                           stdout=subprocess.DEVNULL, timeout=30)
    return info


@contextmanager
def mounted(image, mount):
    subprocess.run(['hdiutil', 'attach', '-nobrowse', '-readonly', '-mountpoint', str(mount), str(image)], check=True)
    try:
        yield mount
    finally:
        subprocess.run(['hdiutil', 'detach', str(mount)], check=True)


def require_closed(destination):
    # Only query open files under this app, never inspect user process arguments or kill apps.
    result = subprocess.run(['/usr/sbin/lsof', '-t', '+D', str(destination)], capture_output=True, text=True)
    if result.stdout.strip():
        raise ValueError('Quit ' + destination.name + ' normally, then rerun setup to update it')
    if result.returncode not in (0, 1) or result.stderr.strip():
        raise ValueError('Cannot establish whether the application is closed: ' + destination.name)


def place_bundle(name, staged, destination):
    no_symlinks(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Fully download/extract/verify in the private system temporary directory first.
    # Only the final copy is staged beside its target, for same-volume rename.
    directory = Path(tempfile.mkdtemp(prefix='.1bite-', dir=destination.parent))
    backup = directory / 'previous.app'
    begin_install(name, destination, bundle_info(staged)['CFBundleShortVersionString'], staging=str(directory))
    completed = False
    try:
        pending = directory / destination.name
        subprocess.run(['ditto', str(staged), str(pending)], check=True, pass_fds=inherited_lock())
        verify_bundle(name, pending)
        existed = destination.exists()
        if existed:
            require_closed(destination)
            destination.rename(backup)
        try:
            pending.rename(destination)
            info = verify_bundle(name, destination)
            record(name, destination, info['CFBundleShortVersionString'])
            completed = True
        except BaseException:
            if destination.exists():
                shutil.rmtree(destination)
            if existed:
                backup.rename(destination)
            raise
    finally:
        if completed or not backup.exists():
            shutil.rmtree(directory)
            pending_path(name).unlink(missing_ok=True)
        else:
            print('Previous application preserved for recovery: ' + str(backup), file=sys.stderr)


def recover_app(name, destination):
    data = read_record(pending_path(name), name, destination)
    if not data:
        return False
    staging = data.get('staging')
    if not isinstance(staging, str):
        raise ValueError('Missing application transaction staging path')
    directory = Path(staging)
    no_symlinks(directory)
    no_symlinks(destination)
    if directory.parent != destination.parent or not directory.name.startswith('.1bite-'):
        raise ValueError('Invalid application transaction staging path')
    backup = directory / 'previous.app'
    no_symlinks(backup)
    healthy = False
    if destination.exists():
        try:
            info = verify_bundle(name, destination)
            healthy = True
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    if not healthy and backup.exists():
        # A crash between the two renames must never discard the previous app.
        if destination.exists():
            require_closed(destination)
            shutil.rmtree(destination)
        backup.rename(destination)
        try:
            info = verify_bundle(name, destination)
            healthy = True
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    if healthy:
        record(name, destination, info['CFBundleShortVersionString'])
    if directory.exists():
        shutil.rmtree(directory)
    if healthy:
        pending_path(name).unlink()
    # Otherwise keep pending ownership so an incomplete first install is repaired.
    return healthy


def install_app(name, destination, healthy=False, update=False):
    pending = pending_path(name)
    no_symlinks(pending)
    if pending.exists():
        interrupted = Path(json.loads(pending.read_text()).get('path', ''))
        if interrupted != destination:
            allowed = {parent / app for parent in (APPLICATIONS, Path.home().resolve() / 'Applications')
                       for app in APPS[name][2]}
            if interrupted not in allowed or destination.exists():
                raise ValueError('Interrupted installation conflicts with the selected application')
            destination = interrupted
            healthy = False
    recovered = recover_app(name, destination)
    healthy = healthy or recovered
    owned = managed(name, destination)
    if healthy and (not update or not owned):
        return 'skipped' if owned else 'preserved'
    no_symlinks(destination)
    if destination.exists() and not owned:
        raise ValueError('Existing unmanaged app is incomplete; preserve it and repair with its original installer: ' + destination.name)
    if not destination.exists() and not os.access(destination.parent, os.W_OK):
        destination = Path.home().resolve() / 'Applications' / APPS[name][0]
        no_symlinks(destination)
        if destination.exists():
            raise ValueError('An application already exists in the user Applications directory')
    if not destination.exists():
        for parent in (APPLICATIONS, Path.home().resolve() / 'Applications'):
            for app_name in APPS[name][2]:
                other = parent / app_name
                if other != destination and (other.exists() or other.is_symlink()):
                    raise ValueError('Preserving an existing incompatible application at ' + str(other))
    data = release(name)
    if healthy:
        current = bundle_info(destination)
        old, latest = version_key(current['CFBundleShortVersionString']), version_key(data['version'])
        if old > latest or (old == latest and (not data.get('build') or
                int(current.get('CFBundleVersion', '0')) >= int(data['build']))):
            return 'update-checked'
        require_closed(destination)
    with tempfile.TemporaryDirectory(prefix='1bite-ai-') as directory:
        work = Path(directory)
        image = work / (name + '.dmg')
        download(name, data['url'], image, data.get('sha256'))
        with mounted(image, work / 'mount') as mount:
            apps = [mount / item for item in APPS[name][2] if (mount / item).is_dir()]
            if len(apps) != 1:
                raise ValueError('Unexpected vendor DMG application layout')
            info = verify_bundle(name, apps[0])
            if version_key(info['CFBundleShortVersionString']) < version_key(data['version']):
                raise ValueError('Official DMG is older than the release feed; rerun after the vendor finishes publishing')
            if (data.get('build') and info['CFBundleShortVersionString'] == data['version']
                    and int(info.get('CFBundleVersion', '0')) < int(data['build'])):
                raise ValueError('Official DMG build is older than the release feed')
            if destination.exists() and not owned:
                raise ValueError('An application appeared while downloading; rerun to check its state')
            place_bundle(name, apps[0], destination)
    finish_install(name, destination, info['CFBundleShortVersionString'])
    print(name + ': official version ' + info['CFBundleShortVersionString'], file=sys.stderr)
    return 'installed-or-updated' if healthy else ('repaired' if owned else 'installed')


def install_cli(name, healthy=False, update=False):
    destination = Path.home().resolve() / '.local/bin' / name
    owned = managed(name, destination)
    selected = shutil.which(name)
    if healthy and owned and selected == str(destination) and pending_path(name).exists():
        output = subprocess.check_output([str(destination), '--version'], text=True, timeout=30)
        match = re.search(r'\d+(?:\.\d+)+', output)
        if not match:
            raise ValueError('Cannot verify interrupted CLI installation')
        finish_install(name, destination, match[0])
    if healthy and (not update or not owned or selected != str(destination)):
        return 'skipped' if owned and selected == str(destination) else 'preserved'
    no_symlinks(destination.parent)
    if not owned and (selected or destination.exists() or destination.is_symlink()):
        raise ValueError('Preserving an unknown broken CLI; repair it with its original installer: ' + name)
    data = release(name)
    if healthy:
        output = subprocess.check_output([str(destination), '--version'], text=True, timeout=30)
        match = re.search(r'\d+(?:\.\d+)+', output)
        if match and version_key(match[0]) >= version_key(data['version']):
            return 'update-checked'
    with tempfile.TemporaryDirectory(prefix='1bite-ai-') as directory:
        installer = Path(directory) / (name + '.sh')
        download(name, data['url'], installer)
        env = {**os.environ, 'CODEX_NON_INTERACTIVE': '1'}
        args = (['/bin/sh', str(installer), '--release', data['version']] if name == 'codex'
                else ['/bin/bash', str(installer), data['version']])
        begin_install(name, destination, data['version'])
        subprocess.run(args, env=env, check=True, umask=0o022, cwd=directory, pass_fds=inherited_lock())
    output = subprocess.check_output([str(destination), '--version'], text=True, timeout=30)
    match = re.search(r'\d+(?:\.\d+)+', output)
    if not match or version_key(match[0]) < version_key(data['version']):
        raise ValueError('Official CLI installer did not provide the requested version')
    finish_install(name, destination, match[0])
    print(output.strip(), file=sys.stderr)
    return 'installed-or-updated' if healthy else ('repaired' if owned else 'installed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name', choices=(*APPS, 'claude', 'codex'))
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--healthy', action='store_true')
    parser.add_argument('--update', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'darwin' or os.geteuid() == 0:
        raise SystemExit('Official AI installation requires macOS and a normal user')
    # Keep stdout solely for the shell's result action; stream vendor output to the log.
    result_fd = os.dup(1)
    os.dup2(2, 1)
    try:
        os.umask(0o022)
        action = (install_app(args.name, args.destination, args.healthy, args.update) if args.name in APPS
                  else install_cli(args.name, args.healthy, args.update))
        sys.stdout.flush()
        os.write(result_fd, (action + '\n').encode())
    except (OSError, ValueError, KeyError, ET.ParseError, subprocess.SubprocessError) as error:
        print('Official AI installation failed: ' + str(error), file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        os.close(result_fd)


if __name__ == '__main__':
    main()
