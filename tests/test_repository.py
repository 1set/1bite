import os
from pathlib import Path
import importlib.util
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
QUALITY_SPEC = importlib.util.spec_from_file_location('check_change', ROOT / 'scripts/check-change.py')
check_change = importlib.util.module_from_spec(QUALITY_SPEC)
QUALITY_SPEC.loader.exec_module(check_change)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='setup-publication-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        self.env.update(HOME=str(self.root), GIT_CONFIG_SYSTEM=os.devnull, GIT_CONFIG_GLOBAL=os.devnull)
        names = ['config/repository-files.txt', 'scripts/check-repository.py', 'scripts/check-format.py']
        for name in names:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if name.startswith('scripts/'):
                shutil.copy2(ROOT / name, path)
        (self.root / names[0]).write_text('\n'.join(names) + '\n')
        self.git('init', '-q')
        self.git('add', '--', *names)

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root, env=self.env,
                              capture_output=True, text=True, check=True)

    def run_script(self, name, *args):
        return subprocess.run([sys.executable, str(self.root / 'scripts' / name), *args],
                              cwd=self.root, env=self.env, capture_output=True, text=True)

    def test_finder_metadata_is_ignored_but_never_published(self):
        (self.root / 'config/.DS_Store').write_bytes(b'\x80finder metadata')
        result = self.run_script('check-format.py')
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_script('check-repository.py', '--archive', 'dist/setup.tar.gz')
        self.assertEqual(result.returncode, 0, result.stderr)
        with tarfile.open(self.root / 'dist/setup.tar.gz') as archive:
            expected = (self.root / 'config/repository-files.txt').read_text().splitlines()
            self.assertEqual(set(archive.getnames()), set(expected))
            for item in archive.getmembers():
                self.assertTrue(item.isfile())
                self.assertEqual((item.uid, item.gid, item.mtime), (0, 0, 0))
                self.assertFalse(item.pax_headers)
        # Even ignored Finder metadata is rejected if it was tracked by mistake.
        self.git('add', '--', 'config/.DS_Store')
        result = self.run_script('check-repository.py')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Publication boundary drift', result.stderr)

    def test_unknown_files_missing_files_and_symlinks_still_fail(self):
        extra = self.root / 'config/private.txt'
        extra.write_text('must never publish\n')
        result = self.run_script('check-repository.py')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unreviewed publication files', result.stderr)
        extra.unlink()
        target = self.root / 'scripts/check-format.py'
        target.unlink()
        result = self.run_script('check-repository.py')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Missing or symlinked publication files', result.stderr)
        self.assertIn('scripts/check-format.py', result.stderr)
        target.symlink_to(ROOT / 'scripts/check-format.py')
        result = self.run_script('check-repository.py')
        self.assertNotEqual(result.returncode, 0)

    def test_shared_copy_requires_independent_git_boundary(self):
        shutil.rmtree(self.root / '.git')
        result = self.run_script('check-repository.py')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('independent Git checkout', result.stderr)

    def test_make_and_ci_use_the_same_non_installing_quality_harness(self):
        workflow = (ROOT / '.github/workflows/quality.yml').read_text()
        makefile = (ROOT / 'Makefile').read_text()
        harness = ROOT / 'scripts/quality.sh'
        self.assertTrue(harness.stat().st_mode & 0o111)
        self.assertIn('quality check:\n\t./scripts/quality.sh\n', makefile)
        self.assertIn('permissions:\n  contents: read\n', workflow)
        self.assertIn('pull_request:', workflow)
        self.assertIn('push:', workflow)
        self.assertIn('workflow_dispatch:', workflow)
        self.assertEqual(workflow.count('run: ./scripts/quality.sh'), 1)
        self.assertIn('uses: actions/checkout@v5', workflow)
        self.assertIn('run: brew install actionlint ripgrep shellcheck shfmt', workflow)
        self.assertNotIn('run: ./1bite', workflow)
        result = subprocess.run([str(harness), '--unknown'], cwd=ROOT,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Usage:', result.stderr)

    def test_change_set_policy_requires_release_evidence(self):
        files = {'VERSION', '1bite', 'scripts/desktop.py', 'tests/test_setup.py',
                 'docs/installation.md', 'config/repository-files.txt',
                 'tests/fixtures/config-golden.json'}
        errors = check_change.policy_errors({'scripts/desktop.py'}, files, files, '1.4.2', '1.4.2')
        self.assertTrue(any('patch bump' in error for error in errors))
        self.assertTrue(any('regression' in error for error in errors))
        self.assertTrue(any('documentation' in error for error in errors))
        changed = {'scripts/desktop.py', 'VERSION', 'tests/test_setup.py', 'docs/installation.md'}
        self.assertEqual(check_change.policy_errors(changed, files, files, '1.4.2', '1.4.3'), [])
        initial = {'scripts/desktop.py', 'tests/test_setup.py', 'docs/installation.md'}
        self.assertEqual(check_change.policy_errors(initial, files, files, '0.0.1', '0.0.1',
                                                    allow_unreleased_initial=True), [])
        self.assertTrue(any('patch bump' in error for error in
                            check_change.policy_errors(initial, files, files, '0.0.1', '0.0.1')))

        errors = check_change.policy_errors({'config/sources.tsv'}, files, files,
                                            '1.4.2', '1.4.3')
        self.assertTrue(any('config-golden.json' in error for error in errors))
        errors = check_change.policy_errors({'scripts/quality.sh'}, files, files | {'new-file'},
                                            '1.4.2', '1.4.2')
        self.assertTrue(any('repository-files.txt' in error for error in errors))
        self.assertEqual(check_change.initial_errors('0.0.1\n'), [])
        self.assertTrue(check_change.initial_errors('0.0.2\n'))

    def test_initial_release_accepts_a_repository_bootstrap_commit(self):
        repo = self.root / 'bootstrap'
        repo.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'master'], cwd=repo, env=self.env, check=True)
        (repo / 'README.md').write_text('# One Bite\n')
        subprocess.run(['git', 'add', 'README.md'], cwd=repo, env=self.env, check=True)
        subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                        'commit', '-qm', 'Initial commit'], cwd=repo, env=self.env, check=True)
        base = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo,
                                       env=self.env, text=True).strip()
        (repo / 'scripts').mkdir()
        shutil.copy2(ROOT / 'scripts/check-change.py', repo / 'scripts/check-change.py')
        (repo / 'VERSION').write_text('0.0.1\n')
        (repo / '1bite').write_text('#!/bin/bash\n')
        subprocess.run(['git', 'add', 'VERSION', '1bite', 'scripts/check-change.py'],
                       cwd=repo, env=self.env, check=True)
        env = {**self.env, 'QUALITY_BASE_SHA': base}
        result = subprocess.run([sys.executable, 'scripts/check-change.py'], cwd=repo,
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('bootstrap base', result.stdout)


if __name__ == '__main__':
    unittest.main()
