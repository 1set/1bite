import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WelcomeTests(unittest.TestCase):
    def run_welcome(self, **extra):
        env = dict(os.environ)
        env.pop('NO_COLOR', None)
        env.update(TERM='xterm-256color', ONE_BITE_COLOR='always')
        env.update(extra)
        return subprocess.run([str(ROOT / '1bite'), '--welcome'], env=env,
                              capture_output=True, text=True, timeout=10)

    def test_full_card_is_colored_private_and_side_effect_free(self):
        with tempfile.TemporaryDirectory(prefix='welcome-') as directory:
            logs = Path(directory) / 'logs'
            private_hostname = 'private-hostname-that-must-not-appear'
            tools = Path(directory) / 'bin'
            tools.mkdir()
            hostname = tools / 'hostname'
            hostname.write_text('#!/bin/sh\nprintf "%s\\n" "' + private_hostname + '"\n')
            hostname.chmod(0o755)
            env = dict(HOME=directory, ONE_BITE_COLOR='always', TERM='xterm-256color',
                       PATH=str(tools) + os.pathsep + os.environ.get('PATH', ''))
            result = self.run_welcome(**env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('\x1b[38;2;', result.stdout)
            self.assertIn('One Bite', result.stdout)
            self.assertIn('First bite for a ready Mac', result.stdout)
            self.assertIn('macOS:', result.stdout)
            self.assertIn('Fetch tools:', result.stdout)
            self.assertNotIn(directory, result.stdout)
            self.assertNotIn(private_hostname, result.stdout)
            self.assertFalse(logs.exists())

    def test_no_color_and_invalid_banner_setting(self):
        plain = self.run_welcome(NO_COLOR='1')
        self.assertEqual(plain.returncode, 0, plain.stderr)
        self.assertNotIn('\x1b[', plain.stdout)
        self.assertIn('One Bite', plain.stdout)
        invalid = self.run_welcome(ONE_BITE_BANNER='sometimes')
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn('ONE_BITE_BANNER must be auto, always or never', invalid.stderr)


if __name__ == '__main__':
    unittest.main()
