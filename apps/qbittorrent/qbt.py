#!/usr/bin/env python3
"""Standalone local Docker lifecycle; credentials and data stay outside the checkout."""
import argparse
import base64
import fcntl
import getpass
import hashlib
import json
import ipaddress
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

APP = Path(__file__).resolve().parent
IMAGE = 'lscr.io/linuxserver/qbittorrent'
PIN = IMAGE + '@sha256:8d48fa8c619caadfb103f04efea8747e2a2762d6c7551690919cffb987e61cee'
DEFAULT_STATE = Path.home() / 'Library/Application Support/1bite/qbittorrent'


def run(command, capture=False, env=None):
    return subprocess.run(command, check=True, text=True, env=env,
                          stdout=subprocess.PIPE if capture else None, timeout=900).stdout


def checked_path(value):
    path = Path(value).expanduser().absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        # /tmp is a system symlink on macOS; resolve the selected root beforehand.
        raise ValueError('Paths must not contain symlinks; use a physical path: ' + str(path))
    if any(c in str(path) for c in '\n\r\0'):
        raise ValueError('Paths must not contain control characters.')
    if path == Path('/') or path == Path.home():
        raise ValueError('Choose a dedicated subdirectory.')
    if str(path).startswith('/Volumes/'):
        volume = Path('/Volumes') / path.parts[2]
        if not volume.is_mount():
            raise ValueError('External volume is not mounted: ' + str(volume))
    return path


def save_settings(state, settings):
    temp = checked_path(state / 'settings.json.tmp')
    checked_path(state / 'settings.json')
    with temp.open('w') as stream:
        json.dump(settings, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    temp.replace(state / 'settings.json')


def seed_config(state, password):
    target = state / 'config/qBittorrent/qBittorrent.conf'
    if target.exists() or target.is_symlink():
        raise ValueError('A qBittorrent configuration already exists; refusing to overwrite it.')
    if len(password) < 12 or any(c in password for c in '\r\n\0'):
        raise ValueError('The initial password must contain at least 12 characters and no newline or NUL.')
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac('sha512', password.encode(), salt, 100000, 64)
    encoded = ':'.join(base64.b64encode(item).decode() for item in (salt, key))
    content = r'''[LegalNotice]
Accepted=true

[BitTorrent]
Session\DefaultSavePath=/downloads/complete
Session\TempPath=/downloads/incomplete
Session\TempPathEnabled=true

[Preferences]
Connection\UPnP=false
Downloads\SavePath=/downloads/complete
Downloads\TempPath=/downloads/incomplete
Downloads\TempPathEnabled=true
WebUI\Address=*
WebUI\ServerDomains=*
WebUI\Username=admin
WebUI\LocalHostAuth=true
WebUI\AuthSubnetWhitelistEnabled=false
WebUI\CSRFProtection=true
WebUI\HostHeaderValidation=true
WebUI\Password_PBKDF2="@ByteArray(%s)"
''' % encoded
    checked_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x') as stream:
        stream.write(content)
    target.chmod(0o600)


def docker(settings, *args, capture=False):
    env = os.environ.copy()
    for name in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        env.pop(name, None)
    return run(['docker', '--context', settings['context'], *args], capture, env)


def check_engine(settings):
    context = json.loads(docker(settings, 'context', 'inspect', capture=True))[0]
    if not context['Endpoints']['docker']['Host'].startswith('unix://'):
        raise ValueError('Only a local Docker context is supported; Mac paths must not be mapped to a remote host.')
    docker(settings, 'info', '--format', '{{.OSType}}', capture=True)
    docker(settings, 'compose', 'version', capture=True)


def compose(state, settings, *args, capture=False):
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith(('COMPOSE_', 'QBT_', 'DOCKER_')):
            env.pop(key)
    values = dict(settings, config=str(state / 'config'))
    env.update({'QBT_' + key.upper(): str(value) for key, value in values.items()})
    return run(['docker', '--context', settings['context'], 'compose',
                '--env-file', '/dev/null', '-p', settings['project'],
                '-f', str(APP / 'compose.yaml'), *args], capture, env)


def load_settings(state):
    settings = json.loads(checked_path(state / 'settings.json').read_text())
    expected = {'image', 'platform', 'uid', 'gid', 'timezone', 'web_port', 'bt_port',
                'bind', 'downloads', 'context', 'project'}
    if set(settings) != expected:
        raise ValueError('settings.json has missing or unknown fields.')
    if not re.fullmatch(re.escape(IMAGE) + r'@sha256:[0-9a-f]{64}', settings['image']):
        raise ValueError('image must be a pinned digest of the official LinuxServer image.')
    if settings['platform'] not in ('linux/arm64', 'linux/amd64'):
        raise ValueError('The configured platform is not supported.')
    for key in ('web_port', 'bt_port'):
        if type(settings[key]) is not int or not 1 <= settings[key] <= 65535:
            raise ValueError('Ports must be between 1 and 65535.')
    if settings['web_port'] == settings['bt_port']:
        raise ValueError('The Web UI and BitTorrent ports must differ.')
    ipaddress.IPv4Address(settings['bind'])
    downloads = checked_path(settings['downloads'])
    if downloads == state or state in downloads.parents or downloads in state.parents:
        raise ValueError('The state and download directories must be separate.')
    return settings


def initialize(state, args):
    settings_file = state / 'settings.json'
    if settings_file.exists():
        settings = load_settings(state)
        for field, value in (('downloads', args.downloads), ('web_port', args.port),
                             ('bt_port', args.bt_port), ('bind', args.bind)):
            if value is not None and str(value) != str(settings[field]):
                raise ValueError('Settings already exist; startup options cannot silently migrate paths or ports. Read the README.')
    else:
        downloads = checked_path(args.downloads or Path.home() / 'Downloads/qBittorrent')
        if downloads == state or state in downloads.parents or downloads in state.parents:
            raise ValueError('The state and download directories must be separate.')
        context = run(['docker', 'context', 'show'], capture=True).strip()
        settings = dict(image=PIN, platform='linux/arm64', uid=os.getuid(), gid=os.getgid(),
                        timezone='Asia/Shanghai', web_port=args.port if args.port is not None else 1024,
                        bt_port=args.bt_port if args.bt_port is not None else 6881,
                        bind=args.bind or '0.0.0.0', downloads=str(downloads),
                        context=context, project='qbt-' + hashlib.sha256(str(state).encode()).hexdigest()[:12])
        ipaddress.IPv4Address(settings['bind'])
        check_engine(settings)
        architecture = docker(settings, 'info', '--format', '{{.Architecture}}', capture=True).strip()
        if architecture in ('x86_64', 'amd64'):
            settings['platform'] = 'linux/amd64'
        elif architecture not in ('aarch64', 'arm64'):
            raise ValueError('Docker must support ARM64 or x86-64.')
        if not 1 <= settings['web_port'] <= 65535 or not 1 <= settings['bt_port'] <= 65535:
            raise ValueError('Ports must be between 1 and 65535.')
        if settings['web_port'] == settings['bt_port']:
            raise ValueError('The Web UI and BitTorrent ports must differ.')
        save_settings(state, settings)
    target = state / 'config/qBittorrent/qBittorrent.conf'
    if not target.exists():
        # A lost config on an existing container must not silently reset credentials.
        if compose(state, settings, 'ps', '-aq', capture=True).strip():
            raise ValueError('A container exists but its configuration is missing. Restore a configuration backup first.')
        if args.password_stdin:
            password = sys.stdin.readline().rstrip('\r\n')
        elif sys.stdin.isatty():
            password = getpass.getpass('First-time setup: admin password (at least 12 characters): ')
            if password != getpass.getpass('Enter the password again: '):
                raise ValueError('The passwords do not match.')
        else:
            raise ValueError('First startup requires an interactive password or a protected value supplied through --password-stdin.')
        seed_config(state, password)
        downloads = checked_path(settings['downloads'])
        for name in ('complete', 'incomplete'):
            (downloads / name).mkdir(parents=True, exist_ok=True)
        print('[OK] Initialized admin; only a salted password hash was stored.')
    else:
        print('[KEEP] Preserved the existing account and download settings.')
    return settings


def ready(state, settings):
    host = '127.0.0.1' if settings['bind'] == '0.0.0.0' else settings['bind']
    url = 'http://' + host + ':' + str(settings['web_port'])
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        ids = compose(state, settings, 'ps', '-q', capture=True).strip()
        if not ids:
            raise ValueError('The container is not running; use logs to inspect the failure.')
        try:
            with opener.open(url + '/', timeout=3) as response:
                if response.status == 200 and b'qBittorrent' in response.read():
                    print('[OK] qBittorrent Web UI is ready: ' + url)
                    if settings['bind'] == '0.0.0.0':
                        print('[INFO] LAN access: http://<this Mac LAN IP>:' + str(settings['web_port']))
                    print('[INFO] Completed downloads: ' + settings['downloads'] + '/complete')
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(1)
    raise ValueError('The service was not ready within 90 seconds. Inspect logs, fix the problem, and run start again.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs='?', default='start',
                        choices=('init', 'start', 'stop', 'restart', 'status', 'logs', 'update', 'check'))
    parser.add_argument('--state-dir', type=Path, default=DEFAULT_STATE)
    parser.add_argument('--downloads', type=Path, help='Set the Mac download directory on first run')
    parser.add_argument('--port', type=int, help='Set the Web UI port on first run; default: 1024')
    parser.add_argument('--bind', help='Set the Web UI IPv4 bind address on first run; default: 0.0.0.0 (LAN access)')
    parser.add_argument('--bt-port', type=int, help='Set the BitTorrent TCP/UDP port on first run; default: 6881')
    parser.add_argument('--password-stdin', action='store_true', help='Read the first password as one line from stdin without storing plaintext')
    args = parser.parse_args()
    os.umask(0o077)
    state = checked_path(args.state_dir)
    if args.command not in ('init', 'start') and not (state / 'settings.json').is_file():
        raise ValueError('The service is not initialized; run start first.')
    state.mkdir(parents=True, exist_ok=True)
    with checked_path(state / 'operation.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('Another lifecycle operation is running; try again later.') from error
        settings = initialize(state, args) if args.command in ('init', 'start') else load_settings(state)
        if args.command == 'init':
            return
        check_engine(settings)
        if args.command in ('start', 'restart', 'update'):
            for path in (state / 'config/qBittorrent/qBittorrent.conf', Path(settings['downloads'])):
                checked_path(path)
                if not path.exists():
                    raise ValueError('Persistent data or configuration is missing. Restore or mount it before retrying: ' + str(path))
            if args.command == 'update':
                docker(settings, 'pull', '--platform', settings['platform'], IMAGE + ':latest')
                digests = json.loads(docker(settings, 'image', 'inspect', IMAGE + ':latest',
                                            '--format', '{{json .RepoDigests}}', capture=True))
                selected = next(item for item in digests if item.startswith(IMAGE + '@sha256:'))
                if selected != settings['image']:
                    # Stop first so the config/fastresume backup is consistent.
                    compose(state, settings, 'stop')
                    backup = state / 'backups' / time.strftime('%Y%m%dT%H%M%S')
                    checked_path(backup)
                    backup.mkdir(parents=True)
                    shutil.copytree(state / 'config', backup / 'config', symlinks=True)
                    with (backup / 'settings.json').open('x') as stream:
                        json.dump(settings, stream, indent=2)
                        stream.write('\n')
                    settings['image'] = selected
                    save_settings(state, settings)
            if args.command == 'restart':
                compose(state, settings, 'stop')
            compose(state, settings, 'up', '-d', '--pull', 'missing')
            ready(state, settings)
        elif args.command == 'stop':
            compose(state, settings, 'stop')
            print('[OK] Stopped; configuration, jobs, and downloaded files were preserved.')
        elif args.command == 'status':
            compose(state, settings, 'ps', '-a')
            print('[INFO] State: ' + str(state))
            print('[INFO] Downloads: ' + settings['downloads'])
            print('[INFO] Image: ' + settings['image'])
            print('[INFO] Web UI bind: ' + settings['bind'] + ':' + str(settings['web_port']))
        elif args.command == 'logs':
            compose(state, settings, 'logs', '--tail', '100')
        elif args.command == 'check':
            ready(state, settings)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, KeyError, StopIteration) as exc:
        print('[FAILED] ' + str(exc), file=sys.stderr)
        sys.exit(1)
