#!/usr/bin/env python3
"""Prepare the vendor installer for a human; never install or enable an input method."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def metadata():
    sources = {name: url for name, kind, url in
               (line.split('\t') for line in (ROOT / 'config/sources.tsv').read_text().splitlines())}
    metadata_url = sources['doubao-input-metadata']
    data = subprocess.check_output(
        ['curl', '--config', str(ROOT / 'config/download.curlrc'), '--fail', '--silent',
         '--show-error', '--location', '--retry', '3', '--proto', '=https',
         '--proto-redir', '=https', '--connect-timeout', '15', '--max-time', '60', metadata_url],
        text=True, timeout=75)
    item = json.loads(data)
    prefix = sources['doubao-input-download']
    match = re.fullmatch(
        r'https://lf-wave\.doubaocdn\.com/obj/doubao-ime/app/macos/'
        r'DoubaoImeInstaller_v([0-9]+)_release\.zip', item['url'])
    versions = item['version'].split(',')
    if (item['token'] != 'doubaoime' or not item['url'].startswith(prefix) or not match
            or len(versions) != 2 or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)+', versions[0])
            or not re.fullmatch(r'[0-9]+', versions[1]) or match.group(1) != versions[1]
            or not re.fullmatch(r'[a-f0-9]{64}', item['sha256'])):
        raise ValueError('Doubao source/checksum format changed; review the official cask before updating.')
    return item, versions[0], versions[1]


def download(url, path):
    subprocess.run(['curl', '--config', str(ROOT / 'config/download.curlrc'),
                    '--fail', '--show-error', '--location', '--retry', '3',
                    '--proto', '=https', '--proto-redir', '=https',
                    '--connect-timeout', '15', '--max-time', '1800',
                    '--output', str(path), url], check=True)


def validate_archive(path, build):
    expected_root = f'DoubaoImeInstaller_v{build}.app'
    expected_payload = f'{expected_root}/Contents/Resources/DoubaoIme.zip'
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if not members or archive.testzip() is not None:
            raise ValueError('Doubao installer ZIP integrity check failed.')
        names = {member.filename.rstrip('/') for member in members}
        if expected_payload not in names:
            raise ValueError('Doubao installer layout changed; expected the official installer application.')
        for member in members:
            relative = PurePosixPath(member.filename)
            top = relative.parts[0].rstrip('/') if relative.parts else ''
            if (not relative.parts or relative.is_absolute() or '..' in relative.parts
                    or top not in (expected_root, '__MACOSX')):
                raise ValueError('Doubao installer ZIP contains an unsafe member.')
            if stat.S_ISLNK(member.external_attr >> 16):
                if top != expected_root or member.file_size > 4096:
                    raise ValueError('Doubao installer ZIP contains an unsafe symbolic link.')
                try:
                    raw_target = archive.read(member)
                    if not raw_target or b'\0' in raw_target:
                        raise ValueError('Doubao installer ZIP contains an unsafe symbolic link.')
                    target = PurePosixPath(raw_target.decode())
                except UnicodeDecodeError as error:
                    raise ValueError('Doubao installer ZIP contains an unsafe symbolic link.') from error
                if target.is_absolute():
                    raise ValueError('Doubao installer ZIP contains an unsafe symbolic link.')
                resolved = list(relative.parent.parts)
                for part in target.parts:
                    if part in ('', '.'):
                        continue
                    if part == '..':
                        if len(resolved) <= 1:
                            raise ValueError('Doubao installer ZIP contains an unsafe symbolic link.')
                        resolved.pop()
                    else:
                        resolved.append(part)
                if not resolved or resolved[0] != expected_root:
                    raise ValueError('Doubao installer ZIP contains an unsafe symbolic link.')


def prepare(directory):
    item, version, build = metadata()
    if directory.is_symlink():
        raise ValueError('Installer directory must not be a symlink.')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / f"DoubaoInput-{version}-{build}-{item['sha256'][:12]}.zip"
    if target.is_symlink() or target.exists() and not target.is_file():
        raise ValueError('Installer package must be a regular file.')
    action = 'reused'
    if not target.is_file() or checksum(target) != item['sha256']:
        action = 'downloaded'
        descriptor, name = tempfile.mkstemp(prefix='.doubao-', suffix='.part', dir=directory)
        os.close(descriptor)
        temporary = Path(name)
        try:
            download(item['url'], temporary)
            if checksum(temporary) != item['sha256']:
                raise ValueError('Doubao installer SHA-256 mismatch; package was not published.')
            validate_archive(temporary, build)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    else:
        validate_archive(target, build)
    report = {'schema_version': 1, 'status': 'prepared', 'action': action,
              'manual_install_required': True, 'version': version, 'build': build,
              'source': item['url'], 'sha256': item['sha256'], 'filename': target.name}
    return target, report


if __name__ == '__main__':
    package, result = prepare(Path.home() / 'Downloads/1bite')
    if os.environ.get('RUN_DIR'):
        report_path = Path(os.environ['RUN_DIR']) / 'doubao-input-installer.json'
        temporary_report = report_path.with_suffix('.tmp')
        temporary_report.write_text(json.dumps(result, indent=2) + '\n')
        temporary_report.replace(report_path)
    print(f"\nOfficial Doubao Input Method installer prepared ({result['action']}): {package}", flush=True)
    print('Double-click the ZIP to extract it, then open the included installer application.', flush=True)
    print('Log out and back in when the installer asks, then enable Doubao in Keyboard settings.', flush=True)
    print('Only the package was prepared; installation and input-source activation remain manual.', flush=True)
