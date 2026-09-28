#!/usr/bin/env python3
"""Prepare official desktop installers without replacing apps or starting onboarding."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import official_ai as vendor

APPS = {
    'docker-desktop': 'Docker.app',
    'google-chrome': 'Google Chrome.app',
    'chatgpt': 'ChatGPT.app',
    'kiro': 'Kiro.app',
    'claude-desktop': 'Claude.app',
}


def directory():
    path = Path.home().resolve() / 'Downloads/1bite'
    vendor.no_symlinks(path)
    return path


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepared(name):
    root = directory()
    receipt = root / (name + '.json')
    vendor.no_symlinks(receipt)
    if not receipt.is_file():
        return None
    try:
        data = json.loads(receipt.read_text())
        filename = data['filename']
        if (data['schema_version'] != 1 or data['component'] != name or
                Path(filename).name != filename or not filename.startswith(name + '-') or
                not filename.endswith('.dmg')):
            return None
        path = root / filename
        vendor.no_symlinks(path)
        if path.is_file() and digest(path) == data['sha256']:
            return data
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return None


def prepare(name, update=False):
    root = directory()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = None if update else prepared(name)
    if data is None:
        catalog = vendor.sources()
        metadata = (dict(url=catalog[name + '-download'], version='latest')
                    if name in ('docker-desktop', 'google-chrome', 'claude-desktop') else vendor.release(name, catalog))
        version = metadata['version']
        if version != 'latest':
            vendor.version_key(version)
        filename = name + '-' + version + '.dmg'
        destination = root / filename
        receipt = root / (name + '.json')
        vendor.no_symlinks(destination)
        vendor.no_symlinks(receipt)
        # Staging stays in a private user download directory; nothing is copied to Applications.
        with tempfile.TemporaryDirectory(prefix='.desktop-', dir=root) as temporary:
            image = Path(temporary) / filename
            try:
                vendor.download(name, metadata['url'], image, metadata.get('sha256'))
            except subprocess.CalledProcessError:
                if name != 'claude-desktop':
                    raise
                # The vendor's browser download endpoint can reject curl. Both
                # routes are official; never switch to an untrusted mirror.
                print('Official Claude DMG redirect unavailable; trying its official release feed.', file=sys.stderr)
                metadata = vendor.release(name, catalog)
                vendor.download(name, metadata['url'], image, metadata.get('sha256'))
            subprocess.run(['hdiutil', 'verify', str(image)], check=True, stdout=sys.stderr)
            data = dict(schema_version=1, component=name, filename=filename, version=metadata['version'],
                        source=metadata['url'], sha256=digest(image), manual_install_required=True)
            pending = Path(temporary) / 'receipt.json'
            pending.write_text(json.dumps(data, indent=2) + '\n')
            pending.chmod(0o600)
            image.replace(destination)
            pending.replace(receipt)
    print('Install ' + APPS[name] + ' from: ' + str(root / data['filename']), file=sys.stderr)
    print('Open the DMG and follow the vendor installation and first-launch instructions.', file=sys.stderr)
    if os.environ.get('RUN_DIR'):
        report = Path(os.environ['RUN_DIR']) / 'desktop-installers.json'
        rows = json.loads(report.read_text()) if report.exists() else []
        rows = [row for row in rows if row['component'] != name]
        rows.append(data)
        report.write_text(json.dumps(rows, indent=2) + '\n')
    return 'prepared'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name', choices=APPS)
    parser.add_argument('--update', action='store_true')
    parser.add_argument('--verify-prepared', action='store_true')
    args = parser.parse_args()
    if args.verify_prepared:
        if not prepared(args.name):
            raise SystemExit('Official desktop installer missing or damaged: ' + args.name)
        return
    if sys.platform != 'darwin' or os.geteuid() == 0:
        raise SystemExit('Desktop preparation requires macOS and a normal user')
    # The shell captures only the action; download and image-verification output stream live.
    result_fd = os.dup(1)
    os.dup2(2, 1)
    try:
        action = prepare(args.name, args.update)
        sys.stdout.flush()
        os.write(result_fd, (action + '\n').encode())
    except (OSError, ValueError, KeyError, vendor.ET.ParseError, subprocess.SubprocessError) as error:
        print('Desktop download failed: ' + str(error), file=sys.stderr)
        raise SystemExit(1) from None
    finally:
        os.close(result_fd)


if __name__ == '__main__':
    main()
