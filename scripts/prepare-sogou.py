#!/usr/bin/env python3
"""Prepare the vendor installer for a human; never install or enable an input method."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def metadata():
    data = json.loads(subprocess.check_output(
        ['brew', 'info', '--json=v2', '--cask', 'homebrew/cask/sogouinput'], text=True, timeout=60))
    item = data['casks'][0]
    prefix = next(line.split('\t')[2] for line in (ROOT / 'config/sources.tsv').read_text().splitlines()
                  if line.startswith('sogou-download\tdistribution\t'))
    # Refuse a changed source or a cask that stops publishing a fixed checksum.
    if (item['token'] != 'sogouinput' or not item['url'].startswith(prefix)
            or not re.fullmatch(r'https://ime\.gtimg\.com/pc/[A-Za-z0-9_.-]+\.zip', item['url'])
            or not re.fullmatch(r'[a-f0-9]{64}', item['sha256'])
            or not re.fullmatch(r'[A-Za-z0-9_.-]+', item['version'])):
        raise ValueError('Sogou source/checksum format changed; review the official cask before updating.')
    return item


def download(url, path):
    subprocess.run(['curl', '--config', str(ROOT / 'config/download.curlrc'),
                    '--fail', '--show-error', '--location', '--retry', '3',
                    '--proto', '=https', '--proto-redir', '=https',
                    '--connect-timeout', '15', '--max-time', '600',
                    '--output', str(path), url], check=True)


def prepare(directory):
    item = metadata()
    if directory.is_symlink():
        raise ValueError('Installer directory must not be a symlink.')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = directory / f"SogouInput-{item['version']}-{item['sha256'][:12]}.zip"
    if target.is_symlink():
        raise ValueError('Installer package must not be a symlink.')
    action = 'reused'
    if not target.is_file() or checksum(target) != item['sha256']:
        action = 'downloaded'
        descriptor, name = tempfile.mkstemp(prefix='.sogou-', suffix='.part', dir=directory)
        os.close(descriptor)
        temporary = Path(name)
        try:
            download(item['url'], temporary)
            if checksum(temporary) != item['sha256']:
                raise ValueError('Sogou installer SHA-256 mismatch; package was not published.')
            with zipfile.ZipFile(temporary) as archive:
                if archive.testzip() is not None:
                    raise ValueError('Sogou installer ZIP integrity check failed.')
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    report = {'schema_version': 1, 'status': 'prepared', 'action': action,
              'manual_install_required': True, 'version': item['version'],
              'source': item['url'], 'sha256': item['sha256'], 'filename': target.name}
    return target, report


if __name__ == '__main__':
    package, result = prepare(Path.home() / 'Downloads/1bite')
    if os.environ.get('RUN_DIR'):
        report_path = Path(os.environ['RUN_DIR']) / 'sogou-installer.json'
        temporary_report = report_path.with_suffix('.tmp')
        temporary_report.write_text(json.dumps(result, indent=2) + '\n')
        temporary_report.replace(report_path)
    print(f"\nOfficial Sogou installer prepared ({result['action']}): {package}", flush=True)
    print('Double-click the ZIP to extract it, then open the included installer.', flush=True)
    print('Then open System Settings > Keyboard > Text Input > Edit, add Sogou, and test text input.', flush=True)
    print('Only the package was prepared; installation and input-source activation remain manual.', flush=True)
