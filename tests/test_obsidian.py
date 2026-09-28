import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('obsidian_vault', ROOT / 'scripts/ob.py')
obsidian_vault = importlib.util.module_from_spec(spec)
spec.loader.exec_module(obsidian_vault)


class ObsidianVaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='obsidian-vault-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.template = ROOT / 'config/obsidian-vault'

    def test_reviewed_template_contains_selected_portable_settings(self):
        files = obsidian_vault.template_files(self.template)
        self.assertEqual(set(files), {str(path.relative_to(self.template)) for path in self.template.rglob('*')
                                     if path.is_file()})
        app = json.loads(files['.obsidian/app.json'])
        appearance = json.loads(files['.obsidian/appearance.json'])
        plugins = json.loads(files['.obsidian/core-plugins.json'])
        self.assertEqual(app['newFileLocation'], 'current')
        self.assertEqual(app['attachmentFolderPath'], '_attachments')
        self.assertTrue(app['alwaysUpdateLinks'])
        self.assertEqual(appearance['cssTheme'], 'Tokyo Night')
        self.assertEqual(appearance['enabledCssSnippets'], ['wide'])
        self.assertTrue(plugins['sync'])
        self.assertNotIn('.obsidian/workspace.json', files)
        self.assertNotIn('.obsidian/workspaces.json', files)

    def test_create_is_exact_and_refuses_to_overwrite_a_vault(self):
        destination = self.root / 'Notes' / 'Project Alpha'
        result = obsidian_vault.create_vault(self.template, destination)
        self.assertEqual(result, destination)
        source = obsidian_vault.template_files(self.template)
        actual = {str(path.relative_to(destination)): path.read_bytes()
                  for path in destination.rglob('*') if path.is_file()}
        self.assertEqual(actual, source)
        self.assertTrue(all(path.stat().st_mode & 0o777 == 0o644
                            for path in destination.rglob('*') if path.is_file()))
        changed = destination / '.obsidian/app.json'
        changed.write_text('{"personal": true}\n')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            obsidian_vault.create_vault(self.template, destination)
        self.assertEqual(changed.read_text(), '{"personal": true}\n')

    def test_symlinks_and_private_template_state_are_rejected(self):
        linked_parent = self.root / 'linked'
        linked_parent.symlink_to(self.root / 'real', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink component'):
            obsidian_vault.create_vault(self.template, linked_parent / 'vault')

        copied = self.root / 'template'
        copied.mkdir()
        (copied / 'workspace.json').write_text('{}\n')
        with self.assertRaisesRegex(ValueError, 'unsupported entry'):
            obsidian_vault.template_files(copied)
        (copied / 'workspace.json').unlink()
        (copied / 'private.md').write_text('/Users/example/private note\n')
        with self.assertRaisesRegex(ValueError, 'private marker'):
            obsidian_vault.template_files(copied)

    def test_failed_copy_leaves_no_destination_or_staging_directory(self):
        destination = self.root / 'vault'
        original = Path.write_bytes
        calls = 0

        def fail_second(path, content):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('simulated write failure')
            return original(path, content)

        with mock.patch.object(Path, 'write_bytes', fail_second), self.assertRaises(OSError):
            obsidian_vault.create_vault(self.template, destination)
        self.assertFalse(destination.exists())
        self.assertEqual(list(self.root.glob('.vault.1bite-*')), [])

    def test_open_uses_an_argument_list_after_creation(self):
        destination = self.root / 'vault with spaces'
        with mock.patch.object(obsidian_vault.subprocess, 'run') as run:
            self.assertEqual(obsidian_vault.main([
                '--template-dir', str(self.template), '--open', str(destination)]), 0)
        run.assert_called_once_with(['open', '-a', 'Obsidian', str(destination)], check=True)


if __name__ == '__main__':
    unittest.main()
