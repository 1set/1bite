import contextlib
import importlib.util
import hashlib
import io
import os
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from test_setup import ROOT, configure


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='editor test ')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.env = {**os.environ, 'HOME': str(self.home), 'ZSH': str(self.home / '.oh-my-zsh')}
        # Keep ordinary shell tests independent of the host's autojump installation.
        binary = self.home / '.local/bin/autojump'
        binary.parent.mkdir(parents=True)
        binary.write_text('#!/bin/sh\nexit 0\n')
        binary.chmod(0o755)

    def shell(self, script):
        return subprocess.run(['bash', '-c', 'source "$1"; ' + script, 'test', str(ROOT / '1bite')],
                              env=self.env, input='', text=True, capture_output=True)

    def zsh(self, script, interactive=True):
        return subprocess.run(['zsh', '-fic' if interactive else '-fc', script, 'test', str(ROOT / 'config/shell.zsh')],
                              env=self.env, input='', text=True, capture_output=True)

    def test_complete_alias_expansion_repeat_and_interactive_boundary(self):
        expected = {
            'll': ['ls', '-lah'], 'g': ['git'], 'lg': ['lazygit'],
            'cl': ['claude'], 'clc': ['claude', '--continue'],
            'cld': ['claude', '--dangerously-skip-permissions'],
            'cldc': ['claude', '--dangerously-skip-permissions', '--continue'],
            'cx': ['codex'], 'cxc': ['codex', 'resume', '--last'],
            'cxd': ['codex', '--dangerously-bypass-approvals-and-sandbox'],
            'cxdc': ['codex', 'resume', '--last', '--dangerously-bypass-approvals-and-sandbox'],
            'dc': ['docker', 'compose'],
        }
        expected.update({
            'm': ['make'],
            'mb': ['make', 'build'],
            'mi': ['make', 'install'],
            'mr': ['make', 'run'],
            'mt': ['make', 'test'],
            'mp': ['make', 'preview'],
            'ga': ['git', 'add'],
            'gaa': ['git', 'add', '--all'],
            'gcmsg': ['git', 'commit', '--message'],
            'dif': ['git', 'diff', '--no-index'],
            'gs': ['git', 'status', '-s'],
            'gst': ['git', 'status'],
            'gss': ['git', 'status', '--short'],
            'gd': ['git', 'diff', '--no-index'],
            'gdiff': ['git', 'diff'],
            'gds': ['git', 'diff', '--staged'],
            'gdca': ['git', 'diff', '--cached'],
            'gb': ['git', 'branch'],
            'gba': ['git', 'branch', '--all'],
            'gco': ['git', 'checkout'],
            'gcb': ['git', 'checkout', '-b'],
            'gsw': ['git', 'switch'],
            'gswc': ['git', 'switch', '--create'],
            'gl': ['git', 'pull'],
            'gp': ['git', 'push'],
            'glo': ['git', 'log', '--oneline', '--decorate'],
            'glog': ['git', 'log', '--oneline', '--decorate', '--graph'],
            'glg': ['git', 'log', '--stat'],
            'gstl': ['git', 'stash', 'list'],
            'gstp': ['git', 'stash', 'pop'],
            'grs': ['git', 'restore'],
            'grst': ['git', 'restore', '--staged'],
            'git_undo_last': ['git', 'reset', '--soft', 'HEAD~1'],
            'gdoc': ['go', 'doc', '-all', '.'],
            'glist': ['go', 'list', '-m', '-u', 'all'],
            'glistj': ['go', 'list', '-m', '-json', 'all'],
            'grun': ['go', 'run', '-v', '.'],
            'gbuild': ['go', 'build', '-ldflags', '-s -w', '-trimpath', '-v', '.'],
            'gtest': ['go', 'test', '-v', '-race', '-cover', '-covermode=atomic', '-count', '1', './...'],
            'gbench': ['go', 'test', '-parallel=4', '-run=none', '-benchtime=2s', '-benchmem', '-bench=.'],
            'gm': ['go', 'mod'],
            'gmi': ['go', 'mod', 'init'],
            'gmt': ['go', 'mod', 'tidy'],
            'gmg': ['go', 'mod', 'graph'],
            'gmc': ['go', 'clean', '--modcache'],
            'dk': ['docker'],
            'dkc': ['docker', 'container'],
            'dkcm': ['docker', 'compose'],
            'dexec': ['docker', 'exec', '-it'],
            'di': ['docker', 'images'],
            'dimg': ['docker', 'images'],
            'dkimg': ['docker', 'image', 'ls'],
            'dklg': ['docker', 'logs', '-f'],
            'dkls': ['docker', 'ps', '-a'],
            'dkps': ['docker', 'ps', '-a'],
            'dkrm': ['docker', 'rm', '-f'],
            'dps': ['docker', 'ps'],
            'dpsa': ['docker', 'ps', '-a'],
            'drmi': ['docker', 'rmi'],
            'dks': ['docker', 'service'],
            'dksm': ['docker', 'swarm'],
            'dkst': ['docker', 'stack'],
            'dkstat': ['docker', 'system', 'df'],
            'df': ['df', '-h'],
            't': ['tmux'],
            'ts': ['tmux', 'ls'],
            'ta': ['tmux', 'attach', '-t'],
            'tk': ['tmux', 'kill-session', '-t'],
            'tl': ['tmux', 'list-sessions'],
            'tksv': ['tmux', 'kill-server'],
            'cdiff': ['code', '-n', '--diff'],
            'rp': ['realpath'],
            'ccat': ['bat', '--paging=never'],
            'mcat': ['glow'],
            'readme': ['glow', 'README.md'],
            'pc': ['pbcopy'],
            'pp': ['pbpaste'],
            'b64e': ['base64'],
            'b64d': ['base64', '-d'],
            'ns': ['nslookup'],
            'cls': ['clear'],
            'weather': ['curl', 'wttr.in'],
            'webserver': ['python3', '-m', 'http.server'],
        })
        expected.update({f'ta{index}': ['tmux', 'attach', '-t', str(index)] for index in range(17)})
        # Stub every target: exercise real Zsh alias expansion without running agents or Docker.
        stubs = '\n'.join(name + '() { printf "%s\\n" ' + name + ' "$@"; }'
                          for name in ('ls', 'git', 'lazygit', 'claude', 'codex', 'docker', 'make', 'go', 'df',
                                       'tmux', 'bat', 'glow', 'pbcopy', 'pbpaste', 'base64',
                                       'nslookup', 'clear', 'curl', 'python3', 'code', 'realpath'))
        for name, command in expected.items():
            with self.subTest(alias=name):
                # Parse the invocation after aliases load, as a new prompt would.
                script = stubs + '\nsource "$1"\nsource "$1"\neval ' + shlex.quote(name + " 'two words' --help")
                result = self.zsh(script)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), command + ['two words', '--help'])
        result = self.zsh('source "$1"; alias ' + ' '.join(expected), interactive=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        result = self.zsh('source "$1"; alias cld="personal-command"; alias cld')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('personal-command', result.stdout)

    def test_git_shortcut_collisions_arguments_and_failure_propagation(self):
        # Existing local/OMZ aliases must not break function definitions on reload.
        prefix = "alias gd='git diff'; alias gm='git merge'; alias gpre='echo WRONG'; alias gps1='echo WRONG'\n"
        prefix += 'source "$1"\nsource "$1"\n'
        for failed, expected in [('none', 0), ('status', 22), ('add', 22), ('diff', 22)]:
            script = prefix + f'FAILED={failed}\n' + """
git() { printf '%s\\n' "$@"; [[ "$1" != "$FAILED" ]] || return 22; }
gpre 'two words'
"""
            result = self.zsh(script)
            self.assertEqual(result.returncode, expected, result.stderr)
            steps = ['status']
            if failed != 'status': steps += ['add', '--all']
            if failed not in ('status', 'add'): steps += ['diff', '--staged', '-w', 'two words']
            self.assertEqual(result.stdout.splitlines(), steps)
        for detached, push_failure, expected in [('false', 'false', 0), ('true', 'false', 1), ('false', 'true', 23)]:
            script = prefix + f'DETACHED={detached}; PUSH_FAILURE={push_failure}\n' + """
git() {
  if [[ "$1" == symbolic-ref ]]; then
    [[ "$DETACHED" == false ]] || return 1
    printf '%s\\n' feature/example
  else
    printf '%s\\n' "$@"
    [[ "$PUSH_FAILURE" == false ]] || return 23
  fi
}
gps1 --dry-run
"""
            result = self.zsh(script)
            self.assertEqual(result.returncode, expected, result.stderr)
            self.assertEqual(result.stdout.splitlines(), [] if detached == 'true' else
                             ['push', '--set-upstream', 'origin', 'feature/example', '--dry-run'])
        result = self.zsh(prefix + 'alias gd gm')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["gd='git diff --no-index'", "gm='go mod'"])
        result = self.zsh('source "$1"; whence -w gpre gps1', interactive=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('function', result.stdout)
        result = self.zsh('source "$1"; make() { return 23; }; eval mt')
        self.assertEqual(result.returncode, 23)

    def test_composite_alias_definitions_are_exact(self):
        # Pipelines and quoted arguments cannot be expanded against stubs; pin raw values instead.
        composite = {
            'ppwd': 'pwd | pbcopy ; pbpaste',
            'pd': 'basename "$PWD" | pbcopy ; pbpaste',
            'l2l': 'pbpaste | paste -sd " " - | pbcopy',
            'now': 'date "+%Y-%m-%d %H:%M:%S %Z" | pbcopy ; pbpaste',
            'utcnow': 'TZ=UTC date "+%Y-%m-%d %H:%M:%S %Z" | pbcopy ; pbpaste',
            'trim': "awk '{$1=$1;print}'",
            'lsp': "find . -type f -not -path '*/\\.git/*' | sed 's/^\\.\\///g' | sort",
            'lsmax': "find . -type f -not -path '*/\\.git/*' -print0 | xargs -0r stat -f '%z %N' | sort -nr | head -10",
            'lslast': "find . -type f -not -path '*/\\.git/*' -print0 | xargs -0r stat -f '%Sm %N' -t '%Y-%m-%d %T' | sort -nr | head -10",
            'gmd': 'git checkout master && git pull && git remote prune origin',
            'gmtag': 'TZ=UTC git --no-pager show --quiet --abbrev=12 --date="format-local:%Y%m%d%H%M%S" --format="v0.0.0-%cd-%h"',
            'reload': '. ~/.zshrc',
            'e': 'exit',
        }
        script = ('source "$1"\nfor name in ' + ' '.join(composite) +
                  '; do print -r -- "$name=$aliases[$name]"; done')
        result = self.zsh(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(dict(line.split('=', 1) for line in result.stdout.splitlines()), composite)
        result = self.zsh('source "$1"; alias ppwd trim', interactive=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')

    def test_directory_stack_and_validated_functions(self):
        # d mirrors the Oh My Zsh directory stack even when OMZ is absent.
        result = self.zsh('source "$1"\ndirs() { printf "DIRS %s\\n" "$@"; }\nd -v\nd')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['DIRS -v', 'DIRS -v'])
        # Existing OMZ-style gci/gcia aliases must not shadow the validated functions.
        result = self.zsh("""
alias gci='echo WRONG'; alias gcia='echo WRONG'
source "$1"
git() { printf '%s\\n' "$@"; }
gci fix stuff || exit 9
gcia amend this || exit 9
""")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(),
                         ['commit', '-a', '-m', 'fix stuff', 'commit', '--amend', '-a', '-m', 'amend this'])
        self.assertNotIn('WRONG', result.stdout)
        for name in ('gci', 'gcia', 'git_corb', 'mktgz', 'fingerprint'):
            result = self.zsh(f'source "$1"\n{name}')
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn('missing', result.stderr)
        result = self.zsh('source "$1"\ndl')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('usage', result.stderr)
        # cd helpers and tmux/docker wrappers dispatch to the real commands.
        result = self.zsh("""
source "$1"
cd "$HOME"
mcd x/y && pwd
cd "$HOME"
mkdir -p p/q && touch p/q/file
cdf p/q/file && pwd
cd "$HOME"
cdf p && pwd
tmux() { printf '%s\\n' "$@"; }
tn session
tn
curl() { printf '%s\\n' "$@"; }
dl https://example/file
dl https://example/file out.bin
""")
        self.assertEqual(result.returncode, 0, result.stderr)
        home = str(self.home)
        self.assertEqual(result.stdout.splitlines(),
                         [home + '/x/y', home + '/p/q', home + '/p',
                          'new-session', '-s', 'session', 'new-session',
                          '--fail', '--location', '--remote-name', '--', 'https://example/file',
                          '--fail', '--location', '--output', 'out.bin', '--', 'https://example/file'])
        result = self.zsh('source "$1"; whence -w d mcd cdf gci tn dkclear tfind', interactive=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('function', result.stdout)

    def test_all_helper_function_alias_collisions_and_reload(self):
        names = ('gpre gps1 mkcd mcd d cdf o dl mktgz mkzip tfind ff jv jp jsonview pcat '
                 'sha1 sha224 sha256 sha384 sha512 sha512224 sha512256 gci gcia git_corb '
                 'git_ignore git_readme tn tad to tkss tmuxconf tds cn gcv dkclear fingerprint '
                 'ffmpeg2wav ffmpeg2pcm video2wav pcm2wav heic2jpg png2jpg webp2png svg2png '
                 'transpng img_trans img_pure_jpg img_pure_png new_bash').split()
        prefix = '\n'.join(f"alias {name}='print WRONG'" for name in names)
        result = self.zsh(prefix + '\nsource "$1"\nsource "$1"\nwhence -w ' + ' '.join(names))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [name + ': function' for name in names])

    def test_imported_helpers_failure_codes_literal_search_and_json(self):
        for code in (0, 23):
            result = self.zsh('source "$1"\ndocker() { print -r -- "$*"; return ' + str(code) + '; }\ndkclear')
            self.assertEqual(result.returncode, code, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ['system prune -f'])
        result = self.zsh('source "$1"\ncurl() { return 22; }\ndl https://example.invalid/file')
        self.assertEqual(result.returncode, 22)
        result = self.zsh('source "$1"\nssh-keygen() { print called; return 9; }\nfingerprint fake')
        self.assertEqual(result.returncode, 9)
        self.assertEqual(result.stdout, 'called\n')
        for value in ({'message': 'literal\\n and actual\nnewline'}, {'message': 'two  spaces'}):
            result = self.zsh('source "$1"\njsonview ' + shlex.quote(json.dumps(value)))
            self.assertEqual(result.returncode, 0, result.stderr)
            # jq -C emits ANSI sequences; jq -M parses the same serialized JSON without color.
            import re
            output = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout)
            self.assertEqual(json.loads(output), value)
        (self.home / 'two words.md').write_text('literal -a.*needle\n')
        (self.home / 'other.txt').write_text('regex -abbbbbneedle should not match\n')
        (self.home / 'excluded.bin').write_text('literal -a.*needle\n')
        result = self.zsh('source "$1"\ncd "$HOME"\ntfind "-a.*needle"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('two words.md', result.stdout)
        self.assertNotIn('other.txt', result.stdout)
        self.assertNotIn('excluded.bin', result.stdout)

    def test_directory_jump_autojump_initialization_and_preservation(self):
        integration = self.home / '.local/share/autojump/autojump.zsh'
        integration.parent.mkdir(parents=True)
        integration.write_text("""
(( AUTOJUMP_TEST_LOADS += 1 ))
autojump_test_hook() { :; }
chpwd_functions+=(autojump_test_hook)
j() { printf 'autojump\n'; printf '%s\n' "$@"; }
jc() { print vendor-child; }
""")
        # Match the installed zoxide contract: its interactive completion block
        # can end with a false feature check when compdef is unavailable.
        zoxide = ("zoxide() { print -r -- 'function z { printf \"zoxide\\n\"; "
                  "printf \"%s\\n\" \"$@\"; }; [[ \"${+functions[compdef]}\" -ne 0 ]] "
                  "&& compdef _zoxide_z z'; }\n")
        result = self.zsh(zoxide + """
alias jc='print custom-child'
source "$1"
source "$1"
j 'two words' --flag
print -r -- "loads=$AUTOJUMP_TEST_LOADS"
print -r -- "hooks=${(j:,:)chpwd_functions}"
eval jc
""")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['autojump', 'two words', '--flag',
                         'loads=1', 'hooks=autojump_test_hook', 'custom-child'])
        for definition in ("function j { print custom-j; }", "alias j='print custom-j'"):
            result = self.zsh(zoxide + definition + '\nsource "$1"\nsource "$1"\neval j\nprint -r -- "${AUTOJUMP_TEST_LOADS:-0}"')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ['custom-j', '0'])
        external = self.home / '.local/bin/j'
        external.write_text('#!/bin/sh\necho external-j\n')
        external.chmod(0o755)
        result = self.zsh(zoxide + 'source "$1"\nj\nprint -r -- "${AUTOJUMP_TEST_LOADS:-0}"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['external-j', '0'])
        external.unlink()
        # A personal wrapper remains personal.
        result = self.zsh(zoxide + 'function j { z "$@"; }\nsource "$1"\nj "two words"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['zoxide', 'two words'])
        integration.unlink()
        result = self.zsh(zoxide + 'source "$1"\nsource "$1"\nwhence -w j')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('function', result.stdout)
        result = self.zsh(zoxide + 'source "$1"\nz "two words" --flag')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['zoxide', 'two words', '--flag'])
        result = self.zsh(zoxide + 'source "$1"\nwhence -w j', interactive=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('function', result.stdout)
        result = self.zsh('zoxide() { return 23; }\nsource "$1"')
        self.assertEqual(result.returncode, 23)

    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('autojump') and shutil.which('zoxide'),
                         'macOS with Homebrew AutoJump and zoxide required for runtime smoke regression')
    def test_native_jump_smoke_from_fresh_and_initialized_parent_shells(self):
        spec = importlib.util.spec_from_file_location('runtime_smoke', ROOT / 'scripts/runtime-smoke.py')
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        private_error = self.home / 'personal-errors.log'
        private_error.write_text('preserve personal log\n')
        before = (private_error.read_bytes(), private_error.stat().st_mtime_ns)
        for inherited in (None, '0', '1'):
            with self.subTest(inherited=inherited):
                env = {'PATH': os.environ['PATH'], 'AUTOJUMP_ERROR_PATH': str(private_error)}
                if inherited is not None:
                    env['AUTOJUMP_SOURCED'] = inherited
                with tempfile.TemporaryDirectory(prefix='native jump smoke ') as directory:
                    with mock.patch.dict(os.environ, env, clear=True):
                        runtime.check_autojump(Path(directory).resolve())
                        self.assertEqual(dict(os.environ), env)
                self.assertEqual((private_error.read_bytes(), private_error.stat().st_mtime_ns), before)

    def test_tmux_shortcuts_forward_arguments_and_errors(self):
        for name, command, target in [('tad', ['attach', '-d'], '-t'),
                                       ('to', ['new-session', '-A'], '-s'),
                                       ('tkss', ['kill-session'], '-t')]:
            for args in ([], ['two words'], ['-t', 'two words'], ['two words', '-d']):
                with self.subTest(name=name, args=args):
                    script = 'source "$1"\nsource "$1"\ntmux() { printf "%s\\n" "$@"; return 23; }\n'
                    result = self.zsh(script + shlex.join([name, *args]))
                    self.assertEqual(result.returncode, 23, result.stderr)
                    expected = command + ([target] if args and not args[0].startswith('-') else []) + args
                    self.assertEqual(result.stdout.splitlines(), expected)
        # Follow the personal config precedence and preserve editor arguments/path quoting.
        xdg = self.home / 'xdg/tmux/tmux.conf'
        xdg.parent.mkdir(parents=True)
        xdg.write_text('# personal\n')
        prefix = 'source "$1"\neditor() { printf "%s\\n" "$@"; return 17; }\nexport EDITOR="editor --wait" XDG_CONFIG_HOME="$HOME/xdg"\n'
        for override, expected in [('', str(xdg)),
                                    ('export ZSH_TMUX_CONFIG="$HOME/two words.conf"\n', str(self.home / 'two words.conf'))]:
            result = self.zsh(prefix + override + 'tmuxconf')
            self.assertEqual(result.returncode, 17, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ['--wait', expected])
        (self.home / '.tmux.conf').write_text('# personal home config\n')
        result = self.zsh(prefix + 'tmuxconf')
        self.assertEqual(result.stdout.splitlines(), ['--wait', str(self.home / '.tmux.conf')])

    def test_portable_editor_and_go_helpers(self):
        for args in ([], ['two words', 'another']):
            result = self.zsh('source "$1"\ncode() { printf "%s\\n" "$@"; return 21; }\n' + shlex.join(['cn', *args]))
            self.assertEqual(result.returncode, 21, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ['-n', *(args or ['.'])])
        for name, system, arch in [('gbuildmac', 'darwin', 'arm64'), ('gbuildmacintel', 'darwin', 'amd64'),
                                    ('gbuildlinux', 'linux', 'amd64'), ('gbuildwindows', 'windows', 'amd64')]:
            result = self.zsh('source "$1"\ngo() { print -r -- "$GOOS/$GOARCH"; printf "%s\\n" "$@"; }\neval ' + name)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), [system + '/' + arch, 'build', '-ldflags', '-s -w', '-trimpath', '-v', '.'])
        for failure in (0, 23):
            result = self.zsh('source "$1"\ngo() { print -r -- "$1"; [[ $1 != test ]] || return ' + str(failure) + '; }\ngcv')
            self.assertEqual(result.returncode, failure, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ['test', 'tool'] if failure == 0 else ['test'])

    @unittest.skipUnless(shutil.which('tmux'), 'Real tmux required')
    def test_tmux_helpers_on_private_server(self):
        with tempfile.TemporaryDirectory(prefix='setup-tmux-', dir='/tmp') as folder:
            socket = str(Path(folder) / 'socket')
            self.env['ONE_BITE_TEST_TMUX_SOCKET'] = socket
            self.env.pop('TMUX', None)
            directory = self.home / 'project.with:punctuation'
            directory.mkdir()
            prefix = 'source "$1"\ntmux() { command tmux -S "$ONE_BITE_TEST_TMUX_SOCKET" -f /dev/null "$@"; }\n'
            try:
                # Noninteractive pane commands cannot write shell history during HOME cleanup.
                result = self.zsh(prefix + 'cd "$HOME/project.with:punctuation"\ntds -d "exec sleep 60"\nto example -d "exec sleep 60"\n')
                self.assertEqual(result.returncode, 0, result.stderr)
                sessions = subprocess.check_output(['tmux', '-S', socket, 'list-sessions', '-F', '#{session_name}'], text=True).splitlines()
                expected = 'project_with_punctuation-' + hashlib.md5(str(directory).encode()).hexdigest()[:6]
                self.assertEqual(set(sessions), {expected, 'example'})
                result = self.zsh(prefix + 'tkss example\n')
                self.assertEqual(result.returncode, 0, result.stderr)
                sessions = subprocess.check_output(['tmux', '-S', socket, 'list-sessions', '-F', '#{session_name}'], text=True).splitlines()
                self.assertEqual(sessions, [expected])
            finally:
                subprocess.run(['tmux', '-S', socket, 'kill-server'], capture_output=True)

    def fake_omz(self):
        folder = Path(self.env['ZSH'])
        for name in ('oh-my-zsh.sh', 'lib/git.zsh', 'lib/cli.zsh', 'themes/robbyrussell.zsh-theme',
                     'plugins/git/git.plugin.zsh', 'custom/themes/powerlevel10k/powerlevel10k.zsh-theme'):
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# fixture\n')
        (folder / 'oh-my-zsh.sh').write_text('omz() { :; }; (( LOADS += 1 )); true\n')
        return folder

    def test_omz_preserves_zshrc_and_uses_official_unattended_flags(self):
        (self.home / '.zshrc').write_text('# personal\n')
        result = self.shell('''
download_installer() {
  test "$1" = ohmyzsh
  cat > "$2" <<'SH'
set -eu
test "$KEEP_ZSHRC" = yes
test "$CHSH" = no
test "$RUNZSH" = no
test "$1" = --unattended
mkdir -p "$ZSH/lib" "$ZSH/themes" "$ZSH/plugins/git"
for file in oh-my-zsh.sh lib/git.zsh lib/cli.zsh themes/robbyrussell.zsh-theme plugins/git/git.plugin.zsh; do
  echo '# installed' > "$ZSH/$file"
done
SH
}
ensure_ohmyzsh
echo "ACTION $STEP_ACTION"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ACTION installed', result.stdout)
        self.assertEqual((self.home / '.zshrc').read_text(), '# personal\n')
        result = self.shell('download_installer() { echo WRONG; return 22; }; ensure_ohmyzsh; echo "$STEP_ACTION"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'skipped')

    def test_custom_omz_and_shell_repeat_preserve_bytes_mtimes_and_single_load(self):
        self.env['ZSH'] = str(self.home / 'custom omz')
        folder = self.fake_omz()
        custom = folder / 'custom/themes/private.zsh-theme'
        custom.parent.mkdir(parents=True, exist_ok=True)
        custom.write_text('# personal theme\n')
        rc = self.home / '.zshrc'
        rc.write_text('export ZSH="' + str(folder) + '"\nZSH_THEME=private\nplugins=(git python)\nsource "$ZSH/oh-my-zsh.sh"\n')
        with contextlib.redirect_stdout(io.StringIO()):
            configure.configure(self.home, ROOT / 'config')
        def snapshot():
            return {str(p.relative_to(self.home)): (p.read_bytes(), p.stat().st_mtime_ns)
                    for p in self.home.rglob('*') if p.is_file()}
        before = snapshot()
        for _ in range(2):
            result = self.shell('download_installer() { echo WRONG; return 99; }; '
                                'git() { echo WRONG; return 98; }; ensure_ohmyzsh; echo "$STEP_ACTION"')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'skipped')
            with contextlib.redirect_stdout(io.StringIO()):
                configure.configure(self.home, ROOT / 'config')
                configure.verify(self.home)
            self.assertEqual(snapshot(), before)
        result = self.zsh('LOADS=0; source "$HOME/.zshrc"; source "$1"; print -r -- "$ZSH_THEME:${plugins[*]}:$LOADS"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'private:git python:1')
        self.assertFalse((self.home / '.oh-my-zsh').exists())
        self.assertEqual(rc.read_text().splitlines().count(configure.SOURCE_LINE), 1)

    def test_omz_update_requires_clean_official_checkout(self):
        self.fake_omz()
        for remote, dirty, accepted in [('https://github.com/ohmyzsh/ohmyzsh.git', '', True),
                                         ('https://example.invalid/fork.git', '', False),
                                         ('https://github.com/ohmyzsh/ohmyzsh.git', ' M theme', False)]:
            result = self.shell(f'UPDATE=true; REMOTE={shlex.quote(remote)}; DIRTY={shlex.quote(dirty)}; ' + '''
git() {
  case "$3" in
    remote) echo "$REMOTE";;
    status) echo "$DIRTY";;
    pull) echo "MUTATE $*";;
  esac
}
ensure_ohmyzsh
''')
            self.assertEqual(result.returncode == 0, accepted, result.stderr)
            self.assertEqual('MUTATE' in result.stdout, accepted)

    def test_omz_partial_install_and_download_failure_stop(self):
        result = self.shell('download_installer() { return 22; }; ensure_ohmyzsh; echo WRONG')
        self.assertEqual(result.returncode, 22)
        self.assertNotIn('WRONG', result.stdout)
        folder = Path(self.env['ZSH'])
        folder.mkdir()
        (folder / 'private-theme').write_text('preserve')
        result = self.shell('download_installer() { echo WRONG; }; ensure_ohmyzsh; echo WRONG')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('WRONG', result.stdout)
        self.assertEqual((folder / 'private-theme').read_text(), 'preserve')

    def test_powerlevel10k_atomic_install_repeat_and_manual_configuration(self):
        self.fake_omz()
        shutil.rmtree(self.home / '.oh-my-zsh/custom/themes/powerlevel10k')
        result = self.shell('''
git() {
  if [[ "$1" == clone ]]; then
    [[ "$2" == --depth=1 && "$3" == https://github.com/romkatv/powerlevel10k.git ]] || return 31
    mkdir -p "$4/internal"
    echo '# theme' > "$4/powerlevel10k.zsh-theme"
    echo '# implementation' > "$4/internal/p10k.zsh"
  else
    echo WRONG
    return 32
  fi
}
ensure_powerlevel10k
echo "ACTION $STEP_ACTION"
echo "MANUAL$MANUAL_STEPS"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ACTION installed', result.stdout)
        self.assertIn('MANUAL powerlevel10k-configure', result.stdout)
        directory = self.home / '.oh-my-zsh/custom/themes/powerlevel10k'
        self.assertTrue((directory / 'powerlevel10k.zsh-theme').is_file())
        self.assertFalse(list(directory.parent.glob('.1bite-p10k-*')))
        result = self.shell('git() { echo WRONG; return 33; }; ensure_powerlevel10k; echo "$STEP_ACTION"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().splitlines()[-1], 'skipped')
        self.assertNotIn('WRONG', result.stdout)

    def test_powerlevel10k_update_and_preservation_boundaries(self):
        self.fake_omz()
        directory = self.home / '.oh-my-zsh/custom/themes/powerlevel10k'
        (directory / 'internal').mkdir()
        (directory / 'internal/p10k.zsh').write_text('# implementation\n')
        for remote, dirty, accepted in [('https://github.com/romkatv/powerlevel10k.git', '', True),
                                         ('https://example.invalid/fork.git', '', False),
                                         ('https://github.com/romkatv/powerlevel10k.git', ' M config', False)]:
            result = self.shell(f'UPDATE=true; REMOTE={shlex.quote(remote)}; DIRTY={shlex.quote(dirty)}; ' + '''
git() {
  case "$3" in
    remote) echo "$REMOTE";;
    status) echo "$DIRTY";;
    pull) echo "MUTATE $*";;
  esac
}
ensure_powerlevel10k
''')
            self.assertEqual(result.returncode == 0, accepted, result.stderr)
            self.assertEqual('MUTATE' in result.stdout, accepted)
        shutil.rmtree(directory)
        directory.write_text('personal placeholder\n')
        result = self.shell('git() { echo WRONG; }; ensure_powerlevel10k; echo WRONG')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(directory.read_text(), 'personal placeholder\n')

    def test_extension_skip_install_update_and_verification(self):
        for installed, update, action in [('true', 'false', 'skipped'), ('false', 'false', 'installed'),
                                           ('true', 'true', 'update-checked')]:
            result = self.shell(f'INSTALLED={installed}; UPDATE={update}; ' + '''
code_cli() {
  if [[ "$1" == --list-extensions ]]; then
    if [[ "$INSTALLED" == true ]]; then echo Golang.Go; fi
  else
    echo "MUTATE $*"; INSTALLED=true
  fi
}
ensure_extension golang.go
echo "ACTION $STEP_ACTION"
''')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('ACTION ' + action, result.stdout)
            self.assertEqual('MUTATE' in result.stdout, action != 'skipped')
            self.assertEqual('--force' in result.stdout, update == 'true')

    def test_extension_errors_never_report_success_or_install_after_list_failure(self):
        for body in ['return 9',
                     'if [[ "$1" == --list-extensions ]]; then return 0; else return 8; fi',
                     'return 0']:
            result = self.shell('code_cli() { ' + body + '; }; ensure_extension golang.go; echo WRONG')
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('WRONG', result.stdout)

    def test_entire_extension_iteration_survives_stdin_consumers(self):
        result = self.shell('ensure_extension() { cat >/dev/null; echo "CHECK $1"; }; install_extensions')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([line[6:] for line in result.stdout.splitlines() if line.startswith('CHECK ')],
                         (ROOT / 'config/vscode-extensions.txt').read_text().splitlines())

    def test_real_zsh_default_existing_and_empty_themes_and_noninteractive(self):
        self.fake_omz()
        defaults = 'git macos vscode web-search extract docker tmux'
        for before, expected in [('', f'powerlevel10k/powerlevel10k:{defaults}:1'),
                                 ('ZSH_THEME=custom; plugins=(git python);', 'custom:git python:1'),
                                 ('ZSH_THEME="";', f':{defaults}:1'),
                                 ('omz() { :; }; ZSH_THEME=existing; plugins=(git); LOADS=0;', 'existing:git:0')]:
            result = self.zsh(before + 'source "$1"; source "$1"; print -r -- "$ZSH_THEME:${plugins[*]}:$LOADS"')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), expected)
        result = self.zsh('source "$1"; (( ! $+functions[omz] )); print OK', interactive=False)
        self.assertEqual(result.stdout.strip(), 'OK')
        self.assertEqual(result.returncode, 0, result.stderr)
        (Path(self.env['ZSH']) / 'custom/themes/powerlevel10k/powerlevel10k.zsh-theme').unlink()
        result = self.zsh('source "$1"; print -r -- "$ZSH_THEME"')
        self.assertEqual(result.stdout.strip(), 'robbyrussell')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_zsh_environment_paths_deduplicate_and_keep_overrides(self):
        for assignments, expected in [('GOBIN="$HOME/custom bin"; GOPATH="$HOME/work";', [self.home / 'custom bin']),
                                      ('unset GOBIN; GOPATH="$HOME/a:$HOME/b";', [self.home / 'a/bin', self.home / 'b/bin']),
                                      ('unset GOBIN GOPATH;', [self.home / 'go/bin'])]:
            result = self.zsh(assignments + '''
CODEX_HOME="$HOME/custom-codex"; CLAUDE_CONFIG_DIR="$HOME/custom-claude"; GOROOT=sentinel
source "$1"; source "$1"
[[ "$CODEX_HOME" == "$HOME/custom-codex" && "$CLAUDE_CONFIG_DIR" == "$HOME/custom-claude" && "$GOROOT" == sentinel ]] || exit 9
print -rl -- $path
''', interactive=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            entries = result.stdout.splitlines()
            self.assertEqual(len(entries), len(set(entries)))
            for path in [self.home / '.local/bin', *expected]:
                self.assertIn(str(path), entries)
            for path in expected:
                self.assertGreater(entries.index(str(path)), entries.index(str(self.home / '.local/bin')))

    def test_docker_default_platform_is_global_and_can_be_overridden(self):
        result = self.zsh('unset DOCKER_DEFAULT_PLATFORM; source "$1"; print -r -- "$DOCKER_DEFAULT_PLATFORM"',
                          interactive=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'linux/amd64')
        result = self.zsh('DOCKER_DEFAULT_PLATFORM=linux/arm64; source "$1"; '
                          'print -r -- "$DOCKER_DEFAULT_PLATFORM"', interactive=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'linux/arm64')

    def test_go_environment_uses_persisted_workspace_and_binary_directory(self):
        go = self.home / '.local/bin/go'
        goenv = self.home / 'persisted-go-env'
        goenv.write_text(f'GOBIN={self.home / "custom go bin"}\n')
        go.write_text('#!/bin/sh\ncase "$*" in\n  "env GOPATH") echo "$HOME/persisted go";;\n'
                      '  "env GOENV") echo "$HOME/persisted-go-env";;\n'
                      '  "env GOBIN") echo "$HOME/derived bin must not be used";;\nesac\n')
        go.chmod(0o755)
        result = self.zsh('unset GOPATH GOBIN; source "$1"; '
                          'print -rl -- "$GOPATH" "$GOBIN" "${path[(Ie)$GOBIN]}"', interactive=False)
        expected = [str(self.home / 'persisted go'), str(self.home / 'custom go bin')]
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[:2], expected)
        self.assertGreater(int(lines[2]), 0)

    def test_go_derived_gobin_does_not_hide_secondary_gopath(self):
        go = self.home / '.local/bin/go'
        go.write_text('#!/bin/sh\ncase "$*" in\n  "env GOENV") echo "$HOME/missing-go-env";;\n'
                      '  "env GOBIN") echo "$HOME/a/bin";;\nesac\n')
        go.chmod(0o755)
        result = self.zsh('unset GOBIN; GOPATH="$HOME/a:$HOME/b"; source "$1"; '
                          'print -rl -- "${GOBIN-unset}" "${path[(Ie)$HOME/a/bin]}" '
                          '"${path[(Ie)$HOME/b/bin]}"', interactive=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], 'unset')
        self.assertGreater(int(lines[1]), 0)
        self.assertGreater(int(lines[2]), 0)

    def test_portable_file_media_and_script_helpers(self):
        target = self.home / 'two words.mp4'
        target.write_bytes(b'fixture')
        calls = self.home / 'calls'
        self.env['ONE_BITE_CALLS'] = str(calls)
        for name in ('ffmpeg', 'magick', 'sips'):
            executable = self.home / '.local/bin' / name
            executable.write_text('#!/bin/sh\nprintf "%s" "${0##*/}" >>"$ONE_BITE_CALLS"\n'
                                  'for arg in "$@"; do printf " <%s>" "$arg" >>"$ONE_BITE_CALLS"; done\n'
                                  'printf "\\n" >>"$ONE_BITE_CALLS"\n')
            executable.chmod(0o755)
        result = self.zsh('source "$1"; ffmpeg2wav "$HOME/two words.mp4"; '
                          'transpng "$HOME/two words.mp4"; new_bash "$HOME/new script.sh"')
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = calls.read_text().splitlines()
        self.assertEqual(len(rows), 2)
        self.assertIn('two words.mp4>', rows[0])
        self.assertIn('two words-trans.png>', rows[1])
        script = self.home / 'new script.sh'
        self.assertTrue(script.stat().st_mode & 0o100)
        self.assertIn('set -euo pipefail', script.read_text())
        result = self.zsh('source "$1"; new_bash "$HOME/new script.sh"')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('refusing to overwrite', result.stderr)

    def test_codex_desktop_all_locations_identity_and_independent_cli(self):
        paths = ['/Applications/ChatGPT.app', str(self.home / 'Applications/ChatGPT.app'),
                 '/Applications/Codex.app', str(self.home / 'Applications/Codex.app')]
        for selected in paths:
            result = self.shell('SELECTED=' + shlex.quote(selected) + '; ' + '''
bundle_healthy() { [[ "$1" == "$SELECTED" ]]; }
bundle_identifier() { echo com.openai.codex; }
brew() { if [[ "$1" == list ]]; then return 1; else echo WRONG; return 8; fi; }
app_path ChatGPT.app
ensure_cask chatgpt ChatGPT.app
agent_healthy() { return 0; }
codex() { echo CLI-VERIFIED; }
check_agent codex
''')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines()[0], selected)
            self.assertIn('CLI-VERIFIED', result.stdout)
            self.assertNotIn('WRONG', result.stdout)
        result = self.shell('bundle_healthy() { return 0; }; bundle_identifier() { echo com.openai.chat; }; app_healthy ChatGPT.app')
        self.assertNotEqual(result.returncode, 0)

    def test_configuration_preserves_vscode_jsonc_migrates_login_and_respects_custom_homes(self):
        vscode = self.home / configure.VSCODE_PATH
        vscode.parent.mkdir(parents=True)
        personal = '// personal\n{"workbench.colorTheme": "Light+",}\n'
        vscode.write_text(personal)
        shell_home = self.home / 'zsh'
        shell_home.mkdir()
        (shell_home / '.zprofile').write_text('# user\n' + configure.SOURCE_LINE + '\n' + configure.ENV_SOURCE_LINE + '\n')
        options = {'with_claude': True, 'codex_home': self.home / 'codex', 'claude_home': self.home / 'claude', 'shell_home': shell_home}
        with contextlib.redirect_stdout(io.StringIO()):
            configure.configure(self.home, ROOT / 'config', **options)
            configure.configure(self.home, ROOT / 'config', **options)
            configure.verify(self.home, **options)
        self.assertEqual(vscode.read_text(), personal)
        self.assertFalse((self.home / '.codex').exists())
        self.assertFalse((self.home / '.claude').exists())
        self.assertFalse((self.home / '.zshrc').exists())
        self.assertEqual((shell_home / '.zprofile').read_text(), '# user\n' + configure.ENV_SOURCE_LINE + '\n')
        self.assertEqual(len(list(shell_home.glob('.zprofile.backup-*'))), 1)


if __name__ == '__main__':
    unittest.main()
