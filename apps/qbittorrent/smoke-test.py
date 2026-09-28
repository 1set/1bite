#!/usr/bin/env python3
"""Run the real image in isolated directories, using a random disposable password."""
import hashlib
import http.cookiejar
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

APP = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('qbt', APP / 'qbt.py')
qbt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qbt)


def bencode(value):
    if isinstance(value, bytes):
        return str(len(value)).encode() + b':' + value
    if isinstance(value, int):
        return b'i' + str(value).encode() + b'e'
    if isinstance(value, list):
        return b'l' + b''.join(bencode(item) for item in value) + b'e'
    return b'd' + b''.join(bencode(key) + bencode(value[key]) for key in sorted(value)) + b'e'


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix='qbt smoke ') as temporary:
        root = Path(temporary).resolve()
        state = root / 'state'
        downloads = root / 'downloads with spaces'
        password = secrets.token_urlsafe(24)
        new_password = secrets.token_urlsafe(24)
        port, bt_port = free_port(), free_port()
        while bt_port == port:
            bt_port = free_port()
        command = [str(APP / 'qbt.sh'), '--state-dir', str(state)]

        def invoke(action, *args, secret=None):
            subprocess.run([*command, action, *args], input=secret, text=True, check=True)

        url = 'http://127.0.0.1:' + str(port)
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                            urllib.request.HTTPCookieProcessor(jar))

        def request(endpoint, fields=None, payload=None, content_type=None):
            headers = {'Referer': url + '/'}
            if fields is not None:
                payload = urllib.parse.urlencode(fields).encode()
            if content_type:
                headers['Content-Type'] = content_type
            req = urllib.request.Request(url + '/api/v2/' + endpoint, data=payload, headers=headers)
            with opener.open(req, timeout=10) as response:
                return response.read()

        def login(secret):
            jar.clear()
            request('auth/login', {'username': 'admin', 'password': secret})
            assert list(jar), 'No authenticated session cookie'
            return request('app/version').decode()

        settings = None
        try:
            # Bind all interfaces in this temporary service to exercise the requested LAN mode.
            invoke('start', '--downloads', str(downloads), '--port', str(port),
                   '--bt-port', str(bt_port), '--password-stdin', secret=password + '\n')
            settings = qbt.load_settings(state)
            assert settings['bind'] == '0.0.0.0'
            assert settings['platform'] in ('linux/arm64', 'linux/amd64')
            container = qbt.compose(state, settings, 'ps', '-q', capture=True).strip()
            inspection = json.loads(qbt.docker(settings, 'inspect', container, capture=True))[0]
            assert inspection['HostConfig']['RestartPolicy']['Name'] == 'unless-stopped'
            assert inspection['HostConfig']['PortBindings'][str(port) + '/tcp'][0]['HostIp'] == '0.0.0.0'
            assert set(inspection['HostConfig']['PortBindings']) == {
                str(port) + '/tcp', str(bt_port) + '/tcp', str(bt_port) + '/udp'}
            assert {m['Destination']: m['Source'] for m in inspection['Mounts']} == {
                '/config': str(state / 'config'), '/downloads': str(downloads)}
            anonymous = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                anonymous.open(url + '/api/v2/app/preferences', timeout=5)
                raise AssertionError('Anonymous API must be rejected')
            except urllib.error.HTTPError as error:
                assert error.code in (401, 403)
            lan = urllib.request.Request(url + '/', headers={'Host': '192.168.50.123:' + str(port)})
            with anonymous.open(lan, timeout=5) as response:
                assert response.status == 200 and b'qBittorrent' in response.read()
            version = login(password)
            prefs = json.loads(request('app/preferences'))
            assert prefs['save_path'].rstrip('/') == '/downloads/complete'
            assert prefs['temp_path'].rstrip('/') == '/downloads/incomplete'
            assert prefs['temp_path_enabled']
            assert prefs['web_ui_domain_list'] == '*'
            assert prefs['web_ui_csrf_protection_enabled']
            assert prefs['web_ui_host_header_validation_enabled']

            # Download our own 64 KiB torrent via a loopback HTTP web seed inside the container.
            # Only this disposable service permits loopback web seeds; production keeps mitigation on.
            payload = secrets.token_bytes(65536)
            source = '/tmp/qbt-smoke-source'
            qbt.docker(settings, 'exec', container, 'mkdir', '-p', source)
            subprocess.run(['docker', '--context', settings['context'], 'exec', '-i', container,
                            'sh', '-c', 'cat > /tmp/qbt-smoke-source/payload.bin'], input=payload, check=True)
            qbt.docker(settings, 'exec', '-d', container, 'python3', '-m', 'http.server',
                       '18765', '--bind', '127.0.0.1', '--directory', source)
            request('app/setPreferences', {'json': json.dumps({'ssrf_mitigation': False})})
            info = {b'name': b'payload.bin', b'length': len(payload), b'piece length': 65536,
                    b'pieces': hashlib.sha1(payload).digest()}
            torrent = bencode({b'info': info, b'url-list': [b'http://127.0.0.1:18765/']})
            torrent_hash = hashlib.sha1(bencode(info)).hexdigest()
            boundary = 'qbt-smoke-' + secrets.token_hex(12)
            body = ('--' + boundary + '\r\nContent-Disposition: form-data; name="torrents"; '
                    'filename="smoke.torrent"\r\nContent-Type: application/x-bittorrent\r\n\r\n').encode()
            body += torrent + ('\r\n--' + boundary + '--\r\n').encode()
            request('torrents/add', payload=body, content_type='multipart/form-data; boundary=' + boundary)
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                entries = json.loads(request('torrents/info?hashes=' + torrent_hash))
                if entries and entries[0]['progress'] == 1 and (downloads / 'complete/payload.bin').exists():
                    break
                time.sleep(1)
            else:
                raise AssertionError('Real torrent did not finish downloading')
            assert (downloads / 'complete/payload.bin').read_bytes() == payload
            request('app/setPreferences', {'json': json.dumps({'ssrf_mitigation': True,
                                                              'web_ui_password': new_password})})
            login(new_password)
            settings_before = (state / 'settings.json').read_bytes()
            invoke('start')
            assert qbt.compose(state, settings, 'ps', '-q', capture=True).strip() == container
            assert (state / 'settings.json').read_bytes() == settings_before
            login(new_password)
            def verify_resumed_task():
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    entries = json.loads(request('torrents/info?hashes=' + torrent_hash))
                    if entries and entries[0]['progress'] == 1:
                        assert (downloads / 'complete/payload.bin').read_bytes() == payload
                        return
                    time.sleep(1)
                raise AssertionError('Saved torrent did not finish resuming')

            invoke('stop')
            invoke('stop')
            assert (downloads / 'complete/payload.bin').read_bytes() == payload
            invoke('start')
            login(new_password)
            invoke('restart')
            login(new_password)
            verify_resumed_task()
            assert (downloads / 'complete/payload.bin').read_bytes() == payload
            invoke('stop')
            qbt.compose(state, settings, 'rm', '-f')
            invoke('start')
            assert qbt.compose(state, settings, 'ps', '-q', capture=True).strip() != container
            login(new_password)
            verify_resumed_task()
            invoke('update')
            login(new_password)
            assert (downloads / 'complete/payload.bin').read_bytes() == payload
            invoke('check')
            invoke('status')
            print(json.dumps({'passed': True, 'version': version, 'platform': settings['platform'],
                              'download_bytes': len(payload), 'password_change_preserved': True,
                              'repeat_start_same_container': True, 'recreation_preserves_tasks': True, 'stop_restart_update_preserve_data': True}))
        finally:
            # Remove only this test's Compose project, never other containers or user data.
            if settings is None and (state / 'settings.json').exists():
                settings = qbt.load_settings(state)
            if settings:
                qbt.compose(state, settings, 'down', '--timeout', '60')


if __name__ == '__main__':
    main()
