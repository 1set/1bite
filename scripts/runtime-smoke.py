#!/usr/bin/env python3
"""Exercise installed runtimes without credentials or external API calls."""

from pathlib import Path
import os
import pty
import select
import subprocess
import tempfile
import time


def check_autojump(root):
    """Initialize native shell integration before exercising an isolated jump database."""
    home = root / 'home'
    home.mkdir()
    light = root / 'jump-smoke light'
    heavy = root / 'jump-smoke heavy'
    light.mkdir()
    heavy.mkdir()
    env = {**os.environ, 'HOME': str(home), 'ZDOTDIR': str(home),
           'ZSH': str(home / '.oh-my-zsh'), 'XDG_DATA_HOME': str(home / '.local/share'),
           '_ZO_DATA_DIR': str(home / '.zoxide')}
    # A preinitialized contributor shell must not hide first-install failures.
    for name in ('AUTOJUMP_SOURCED', 'AUTOJUMP_ERROR_PATH'):
        env.pop(name, None)
    script = r'''set -e
source "$1"
source "$1"
[[ $AUTOJUMP_SOURCED == 1 && ${functions[j]} == *autojump* ]]
[[ ${(M)#chpwd_functions:#autojump_chpwd} == 1 ]]
(( $+functions[z] && $+functions[zi] ))
# Registration checked above; prevent asynchronous history writes during this probe.
chpwd_functions=()
# Both writes and queries need the initialization performed in this same process.
autojump --add "$2"
for visit in 1 2 3; do autojump --add "$3"; done
cd "$3"
before=$(j --stat)
cd "$4"
j jump-smoke >/dev/null
[[ $PWD == "$3" ]]
[[ $(j --stat) == "$before" ]]
'''
    subprocess.run(['zsh', '-fic', script, 'smoke',
                    str(Path(__file__).resolve().parents[1] / 'config/shell.zsh'),
                    str(light), str(heavy), str(root)], env=env, cwd=root,
                   stdin=subprocess.DEVNULL, check=True, timeout=30)


def check_fzf(root, shell_path=None):
    """Load the real fzf widget in a pseudo-terminal, including legacy Homebrew releases."""
    home = root / 'fzf-home'
    home.mkdir()
    env = {**os.environ, 'HOME': str(home), 'ZDOTDIR': str(home),
           'ZSH': str(home / '.oh-my-zsh')}
    script = r'''source "$1"
(( $+functions[fzf-history-widget] ))
[[ $(bindkey '^R') == *fzf-history-widget* ]]
'''
    master, slave = pty.openpty()
    shell_path = shell_path or Path(__file__).resolve().parents[1] / 'config/shell.zsh'
    process = subprocess.Popen(['zsh', '-fic', script, 'smoke', str(shell_path)],
                               env=env, cwd=root, stdin=slave, stdout=slave, stderr=slave)
    os.close(slave)
    output = bytearray()
    deadline = time.monotonic() + 30
    try:
        while process.poll() is None:
            if time.monotonic() >= deadline:
                process.kill()
                raise subprocess.TimeoutExpired(process.args, 30, bytes(output))
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        while True:
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break
            if not chunk:
                break
            output.extend(chunk)
    finally:
        os.close(master)
    code = process.wait(timeout=1)
    if code:
        raise subprocess.CalledProcessError(code, process.args, output=bytes(output))


def main():
    with tempfile.TemporaryDirectory(prefix='1bite-smoke-') as directory:
        root = Path(directory).resolve()
        check_autojump(root)
        check_fzf(root)
        (root / 'main.go').write_text('package main\nimport "fmt"\nfunc main() { fmt.Print("go-ok") }\n')
        subprocess.run(['go', 'build', '-o', str(root / 'hello'), str(root / 'main.go')], check=True)
        assert subprocess.check_output([str(root / 'hello')], text=True) == 'go-ok'
        javascript = root / 'javascript'
        javascript.mkdir()
        (javascript / 'package.json').write_text(
            '{"private":true,"scripts":{"build":"node build.mjs","start":"node dist/app.mjs"}}\n')
        (javascript / 'build.mjs').write_text(
            "import { mkdir, writeFile } from 'node:fs/promises';\n"
            "await mkdir('dist', { recursive: true });\n"
            "await writeFile('dist/app.mjs', \"console.log('node-ok')\\n\");\n")
        (root / 'npm-home').mkdir()
        npm_env = {**os.environ, 'HOME': str(root / 'npm-home'),
                   'npm_config_cache': str(root / 'npm-cache'),
                   'npm_config_audit': 'false', 'npm_config_fund': 'false',
                   'NO_UPDATE_NOTIFIER': '1'}
        subprocess.run(['npm', 'run', 'build', '--silent'], cwd=javascript, env=npm_env,
                       stdin=subprocess.DEVNULL, check=True, timeout=30)
        assert subprocess.check_output(['npm', 'start', '--silent'], cwd=javascript, env=npm_env,
                                       stdin=subprocess.DEVNULL, text=True, timeout=30).strip() == 'node-ok'
        assert subprocess.check_output(['npx', '--version'], env=npm_env,
                                       stdin=subprocess.DEVNULL, text=True, timeout=15).strip()
        subprocess.run(['uv', 'venv', '--python', 'python3', str(root / 'venv')], check=True)
        assert subprocess.check_output([str(root / 'venv/bin/python'), '-c', 'print(6 * 7)'], text=True).strip() == '42'
        markdown = root / 'sample.md'
        markdown.write_text('# Smoke\n\ncharm-smoke-ok\n')
        # Glow prioritizes piped stdin over file arguments; keep the installer input separate.
        assert 'charm-smoke-ok' in subprocess.check_output(['glow', '-s', 'ascii', str(markdown)],
                                                          stdin=subprocess.DEVNULL, text=True, timeout=15)
        assert 'charm-smoke-ok' in subprocess.check_output(['gum', 'style', 'charm-smoke-ok'],
                                                          stdin=subprocess.DEVNULL, text=True, timeout=15)
        # Version probes avoid Pop mail delivery and Crush provider login/API calls.
        for name in ('glow', 'pop', 'gum', 'crush'):
            assert subprocess.check_output([name, '--version'], cwd=root, stdin=subprocess.DEVNULL, text=True, timeout=15).strip()
    print('Native AutoJump ranking/reload, fzf search, Go build/run, Node npm build/run, uv Python and Charm CLI smoke checks passed.')


if __name__ == '__main__':
    main()
