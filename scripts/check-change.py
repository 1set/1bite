#!/usr/bin/env python3
"""Enforce the reviewable change-set contract against a Git base revision."""
from pathlib import Path
import os
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VERSION = re.compile(r'^(\d+)\.(\d+)\.(\d+)$')
INFRA_SCRIPTS = {
    'scripts/check-change.py',
    'scripts/check-format.py',
    'scripts/check-repository.py',
    'scripts/quality.sh',
}


def git(*args, check=True):
    return subprocess.run(['git', '-C', str(ROOT), *args], text=True,
                          capture_output=True, check=check)


def is_product(path):
    if path == '1bite' or path.startswith('assets/'):
        return True
    if path.startswith('config/') and path != 'config/repository-files.txt':
        return True
    if path.startswith('scripts/'):
        return path not in INFRA_SCRIPTS
    if path.startswith('apps/'):
        return not path.endswith('.md')
    return False


def policy_errors(changed, base_files, current_files, base_version, current_version):
    changed = set(changed)
    errors = []
    product_changed = any(is_product(path) for path in changed)
    tests_changed = any(path.startswith('tests/test_') and path.endswith('.py') for path in changed)
    docs_changed = ('README.md' in changed or any(path.startswith('docs/') for path in changed)
                    or any(path.startswith('apps/') and path.endswith('.md') for path in changed))

    if product_changed:
        before = VERSION.fullmatch(base_version.strip())
        after = VERSION.fullmatch(current_version.strip())
        if not before or not after:
            errors.append('product changes require numeric MAJOR.MINOR.PATCH VERSION values')
        elif ((int(after[1]), int(after[2]), int(after[3])) !=
              (int(before[1]), int(before[2]), int(before[3]) + 1)):
            errors.append(f'product changes require one patch bump: {base_version.strip()} -> '
                          f'{int(before[1])}.{int(before[2])}.{int(before[3]) + 1}')
        if not tests_changed:
            errors.append('product changes require a changed tests/test_*.py regression file')
        if not docs_changed:
            errors.append('product changes require a user-documentation change in README.md, docs/, '
                          'or an app README')

    if base_files != current_files and 'config/repository-files.txt' not in changed:
        errors.append('published file additions/removals require config/repository-files.txt')
    if any(path.startswith('config/') for path in changed) and \
            'tests/fixtures/config-golden.json' not in changed:
        errors.append('config changes require the complete tests/fixtures/config-golden.json')
    return errors


def initial_errors(current_version):
    if current_version.strip() != '0.0.1':
        return ['the initial public release must use VERSION 0.0.1']
    return []


def main():
    requested_base = os.environ.get('QUALITY_BASE_SHA', '').strip()
    initial = bool(requested_base and set(requested_base) == {'0'})
    base = '' if initial else requested_base
    if not base and not initial:
        base = 'HEAD'
    current_version = (ROOT / 'VERSION').read_text()
    if initial:
        errors = initial_errors(current_version)
        if errors:
            for error in errors:
                print(f'- {error}', file=sys.stderr)
            return 1
        print('Initial public release policy passed.')
        return 0
    resolved = git('rev-parse', '--verify', f'{base}^{{commit}}', check=False)
    if resolved.returncode:
        if base == 'HEAD':
            errors = initial_errors(current_version)
            if errors:
                for error in errors:
                    print(f'- {error}', file=sys.stderr)
                return 1
            print('Initial public release policy passed in an unborn repository.')
            return 0
        print(f'Quality base is unavailable: {base}', file=sys.stderr)
        return 2
    base = resolved.stdout.strip()

    changed = set(git('diff', '--name-only', '-z', base, '--').stdout.rstrip('\0').split('\0'))
    changed.discard('')
    base_files = set(git('ls-tree', '-r', '--name-only', '-z', base).stdout.rstrip('\0').split('\0'))
    current_files = set(git('ls-files', '-z').stdout.rstrip('\0').split('\0'))
    base_version = git('show', f'{base}:VERSION', check=False)
    if base_version.returncode:
        print(f'Quality base has no VERSION file: {base}', file=sys.stderr)
        return 2
    errors = policy_errors(changed, base_files, current_files, base_version.stdout, current_version)
    if errors:
        print(f'Change-set policy failed against {base}:', file=sys.stderr)
        for error in errors:
            print(f'- {error}', file=sys.stderr)
        return 1
    print(f'Change-set policy passed against {base} ({len(changed)} changed paths).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
