#!/usr/bin/env python3
"""An explicit publication boundary for commits and distributable archives."""
from pathlib import Path
import argparse
import gzip
import subprocess
import tarfile

root = Path(__file__).resolve().parents[1]
expected = set((root / 'config/repository-files.txt').read_text().splitlines())
assert all(path and not path.startswith('/') and '..' not in Path(path).parts for path in expected)
invalid = sorted(path for path in expected if not (root / path).is_file() or (root / path).is_symlink())
assert not invalid, f'Missing or symlinked publication files: {invalid}'
for directory in ('config', 'scripts', 'docs', 'tests', '.github', 'apps'):
    actual = {str(p.relative_to(root)) for p in (root / directory).rglob('*')
              if p.is_file() and '__pycache__' not in p.parts and p.name != '.DS_Store'}
    assert actual <= expected, f'Unreviewed publication files: {sorted(actual - expected)}'
checkout = subprocess.run(['git', '-C', str(root), 'rev-parse', '--show-toplevel'],
                          text=True, capture_output=True)
assert checkout.returncode == 0, 'Build from an independent Git checkout; a shared/ZIP copy has no tracked-file boundary'
checkout_root = checkout.stdout.strip()
assert Path(checkout_root).resolve() == root, 'Expected this project to have its own Git repository'
tracked = set(subprocess.check_output(['git', '-C', str(root), 'ls-files'], text=True).splitlines())
assert tracked == expected, f'Publication boundary drift: {sorted(tracked ^ expected)}'
print(f'Independent repository and all {len(expected)} published files verified.')

parser = argparse.ArgumentParser()
parser.add_argument('--archive', type=Path)
args = parser.parse_args()
if args.archive:
    args.archive.parent.mkdir(parents=True, exist_ok=True)
    with args.archive.open('wb') as destination:
        with gzip.GzipFile(fileobj=destination, mode='wb', filename='', mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as archive:
                for name in sorted(expected):
                    path = root / name
                    info = tarfile.TarInfo(name)
                    info.size = path.stat().st_size
                    info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
                    # TarInfo defaults normalize owner, timestamps and extended metadata.
                    with path.open('rb') as source:
                        archive.addfile(info, source)
    with tarfile.open(args.archive) as archive:
        members = archive.getmembers()
        assert {member.name for member in members} == expected and len(members) == len(expected)
        assert all(member.isfile() and member.uid == member.gid == member.mtime == 0
                   and not member.uname and not member.gname and not member.pax_headers for member in members)
    print('Archive verified: exact allowlist; no owner names, timestamps, symlinks or extended attributes.')
