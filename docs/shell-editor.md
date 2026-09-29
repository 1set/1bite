# Shell, editor, Git, and terminal configuration

## Managed files

| Template | Installed location and behavior |
| --- | --- |
| `claude-settings.json` | `${CLAUDE_CONFIG_DIR:-~/.claude}/settings.json`; created only when absent |
| `kiro-permissions.json` | `~/.kiro/settings/permissions.yaml`; asks before tools on a new setup and preserves existing YAML |
| `codex-config.toml` | `${CODEX_HOME:-~/.codex}/config.toml`; workspace-write and on-request approval on a new setup |
| `env.zsh` | `~/.config/1bite/env.zsh`; Homebrew, AI CLI, Docker, Go, and VS Code environment and PATH |
| `shell.zsh` | `~/.config/1bite/shell.zsh`; interactive loader for the eight modules below |
| `zsh/framework.zsh` | Oh My Zsh and Powerlevel10k selection |
| `zsh/options.zsh` | Zsh key bindings, history, and shell options |
| `zsh/tools.zsh` | AutoJump, zoxide, and fzf initialization |
| `zsh/development.zsh` | Make, Git, Go, Docker, AI CLI, and LazyGit shortcuts |
| `zsh/utilities.zsh` | Directory, file, display, clipboard, hash, and encoding helpers |
| `zsh/media.zsh` | Audio, video, image conversion, and script-template helpers |
| `zsh/git-functions.zsh` | Git functions with argument checks and failure propagation |
| `zsh/terminal.zsh` | Editor, tmux, Docker cleanup, and terminal helpers |
| `vimrc` | `~/.config/1bite/vimrc`; UTF-8, syntax highlighting, line numbers, four-space indentation, visible whitespace, and command correction |
| `git-defaults.json` | Adds only missing shared behavior and aliases to global Git configuration |
| `gitignore-global` | Used at `~/.config/1bite/gitignore-global` only when no global ignore is already configured |
| `vscode-settings.json` | `~/Library/Application Support/Code/User/settings.json`; created only when no user file exists |
| `iterm2-profile.json` | `~/Library/Application Support/iTerm2/DynamicProfiles/1bite.json` |

Templates never contain API keys, proxy settings, account identities, or third-party model credentials. Existing private AI and editor configuration is preserved.

```bash
cp -R config local-config
# Review and edit all templates, including the eight files under zsh/.
./1bite --config-dir ./local-config
# Apply configuration only; requires Python 3.11 or later.
./1bite --configure-only --config-dir ./local-config
```

An external configuration directory must be updated when a release introduces a new template. Missing required files cause a clear configuration error. It controls templates only; package manifests and executable download sources still come from the repository.

Before replacing managed env, shell, Zsh, Vim, or iTerm2 files, One Bite writes a `.backup-*` copy. It also backs up `.zshrc`, `.zprofile`, and `.vimrc` before changing their loader line. Writes use a same-directory temporary file and atomic replacement; identical content is skipped. Recognized loader variants are replaced in place by one canonical line, preserving all personal lines before and after it in their original order. Similar-looking personal commands are not removed. New modules are published before the loader is changed, and `--verify` checks exact managed bytes.

After configuration, One Bite prints the two user-owned entry paths, the separate managed directory, `exec zsh` for non-iTerm shells, and the iTerm2 reopen step. You can inspect the only One Bite entry lines with:

```bash
grep -nF ".config/1bite" ~/.zshrc ~/.zprofile
```

Keep aliases or overrides after the guarded loader in `.zshrc`. Do not replace the whole file. If `.zshrc` or `.zprofile` is a dotfile-manager symlink, One Bite stops before changing anything and prints the exact `source` line to add to the manager-owned source file. Rerun `./1bite --configure-only` after making that edit.

For a regular non-empty entry file with no loader, One Bite writes an adjacent backup, appends the guarded line, and prints a review notice. A recognized loader variant is canonicalized in place. If the current loader is already exact, a rerun prints that the entry is unchanged and does not rewrite it. A source command that mentions a One Bite managed path but does not match a recognized form stops all configuration before any writes; merge that line manually into the canonical form printed by the error, then rerun.

A symlinked target or managed module directory causes configuration to stop so an existing dotfiles manager is not edited through the link. To restore a backup, close the affected application, inspect the selected `.backup-*`, and copy it back to its original name. One Bite does not bulk-delete backups or private settings.

## Vim

The shared Vim configuration lives at `~/.config/1bite/vimrc`; the user's `~/.vimrc` contains one guarded source line. Existing content before and after that line is preserved. Repeated runs do not duplicate the loader or touch unchanged files.

Defaults include UTF-8, disabled modelines, syntax highlighting, absolute line numbers, ruler display, four-space expanded tabs, visible tabs and trailing whitespace, and corrections for accidental `:W`, `:Q`, and `:Wq`. It installs no Vim plugins or theme and contains no project or private path. Swap, undo, and backup files are disabled by default, matching the imported local convention; save important edits or override these choices after the managed source line.

```vim
" The One Bite source line is above this block.
set nolist
set undofile
```

## Zsh, Oh My Zsh, Powerlevel10k, and environment

- `.zprofile` loads `env.zsh`; interactive `.zshrc` loads `shell.zsh`, which loads the eight modules in a fixed order. Existing beginning and ending content stays in place. Put personal overrides after the managed source line. An absolute `ZDOTDIR` is honored.
- Missing Oh My Zsh is installed with the official unattended installer while preserving `.zshrc`, without `chsh` or automatically starting Zsh. iTerm2 and new VS Code terminals use `/bin/zsh -l`.
- A healthy Oh My Zsh installation receives a shallow Powerlevel10k checkout under `${ZSH_CUSTOM:-$ZSH/custom}/themes/powerlevel10k`. It is selected only if `ZSH_THEME` was not explicitly set. Configuration-only mode safely uses `robbyrussell` when Powerlevel10k is absent.
- Existing Oh My Zsh directories, explicit themes including an empty theme, plugin lists, and `~/.p10k.zsh` are preserved. Normal reruns skip healthy checkouts. `--update` fast-forwards only a clean official checkout; custom origins, forks, symlinks, and incomplete directories remain with their existing owner.
- PATH is deduplicated and includes `~/.local/bin`, available Docker.app and VS Code CLI directories, and Go tools. An application directory is added only when its client executable exists. Existing `GOPATH` and `GOBIN` win; otherwise One Bite reads persisted `go env` values and falls back to `~/go`. It exports the effective workspace and adds explicit `GOBIN`, or every `GOPATH/bin`, without setting `GOROOT`.
- `DOCKER_DEFAULT_PLATFORM` defaults to `linux/amd64`, including on Apple Silicon, so ordinary Docker-compatible builds and runs target a portable x86-64 Linux platform. An already set value is preserved. This client setting does not install Docker Desktop and works with another compatible local engine or remote context. Override it before loading the environment or for one command when a project needs `linux/arm64` or a multi-platform builder.
- Existing absolute `CODEX_HOME` and `CLAUDE_CONFIG_DIR` are honored. Finder-launched applications cannot be assumed to inherit terminal environment variables.

After Powerlevel10k is enabled, reopen iTerm2 and start a new window with **Profiles > One Bite** before running the wizard. That managed profile selects the installed `MesloLGSNF-Regular` face; an already-open window keeps its previous font. The wizard normally opens automatically in the new shell; otherwise run `p10k configure`. If it still offers to download Meslo, cancel, reopen iTerm2, and confirm **Settings > Profiles > One Bite > Text** shows MesloLGS Nerd Font. The user owns the generated `~/.p10k.zsh`.

The tools module enables fzf's Ctrl+R history search, Ctrl+T file picker, and Option+C directory picker only in an interactive terminal. Current fzf releases use `fzf --zsh`; older healthy Homebrew releases fall back to their installed `shell/completion.zsh` and `shell/key-bindings.zsh`. Personal bindings after the One Bite loader still take precedence.

On a fresh machine, `.zshrc` contains only the managed loader and the default plugin array is declared inside `~/.config/1bite/zsh/framework.zsh`. The framework enables the built-in Oh My Zsh plugins `git`, `macos`, `vscode`, `web-search`, `extract`, and `tmux`, inserting `docker` only when the shell can resolve a Docker client. If `.zshrc` or another earlier file already defines `plugins=(...)`, that array remains user-owned and takes precedence byte-for-byte. fzf, AutoJump, and zoxide deliberately stay out of the managed OMZ list because the tools module loads their native integrations once and verifies their actual widgets/functions.

For a maintained cross-shell prompt, consider [Starship](https://starship.rs/). [Oh My Posh](https://ohmyposh.dev/) provides a broader segment/template model, and [Spaceship](https://spaceship-prompt.sh/) stays native to Zsh. Initialize only one prompt engine. One Bite currently manages Powerlevel10k and leaves other prompt configuration untouched.

## Shortcuts

The templates use lowercase local conventions: `m` for Make, `g` for Git, and `dk` for Docker. `d` is a directory-stack function compatible with Oh My Zsh. Modules load after Oh My Zsh, so these explicit mappings win; place further personal overrides after the One Bite loader.

| Group | Shortcut -> command or behavior |
| --- | --- |
| Core | `g` -> `git`; `lg` -> `lazygit`; `ll` -> `ls -lah`; `d` -> directory stack; `dk` -> `docker` and `dc` -> `docker compose` when Docker is available |
| Make | `m`, `mb`, `mi`, `mr`, `mt`, `mp` -> `make`, `make build/install/run/test/preview` |
| Git stage/commit | `ga` -> `git add`; `gaa` -> `git add --all`; `gci` / `gcia` commit or amend with a required message; `gcmsg` -> `git commit --message` |
| Git status/diff | `gs`, `gst`, `gss`; `gd` -> `git diff --no-index`; `gdiff`; `gds`; `gdca` |
| Git branch/sync | `gb`, `gba`, `gco`, `gcb`, `gsw`, `gswc`, `gl`, `gp` |
| Git history/stash | `glo`, `glog`, `glg`, `gstl`, `gstp`; `grs`, `grst`; `git_undo_last` -> soft reset of the latest commit |
| Git version | `gmtag` prints a Go pseudo-version style string using UTC commit time and a 12-character SHA |
| Go inspect/run | `gdoc`, `glist`, `glistj`, `grun` |
| Go build/test | `gbuild`; `gbuildmac`; `gbuildmacintel`; `gbuildlinux`; `gbuildwindows`; `gtest`; `gbench`; `gcv` creates `coverage.html` after successful race/coverage tests |
| Go modules | `gm`, `gmi`, `gmt`, `gmg`, `gmc` -> `go mod`, init, tidy, graph, and module-cache cleanup |
| Docker | `dexec`, `di`, `dimg`, `dps`, `dpsa`, `drmi`, `dkc`, `dkcm`, `dkimg`, `dklg`, `dkls`, `dkps`, `dkrm`, `dks`, `dksm`, `dkst`, `dkstat` |
| Disk | `df` -> `df -h`; `ff [directory]` shows one level ordered by size with readable units |
| Paths/files | `mcd` / `mkcd`; `cdf`; `o`; `dl`; `mktgz`; `mkzip`; `tfind`; `lsp`; `lsmax`; `lslast`; `trim` |
| Display | `jv`, `jp`, `jsonview`; `ccat` through bat; `mcat` / `readme` through Glow |
| Clipboard/time | `pc`, `pp`, `ppwd`, `pd`, `pcat`, `l2l`; `now`, `utcnow` copy and print timestamps |
| Hash/encoding | `sha1`, `sha224`, `sha256`, `sha384`, `sha512`, `sha512224`, `sha512256`; `b64e`, `b64d` |
| Media | `ffmpeg2wav`, `video2wav`, `ffmpeg2pcm`, `pcm2wav` create 16 kHz mono output without overwriting an existing target |
| Images/scripts | `heic2jpg`, `png2jpg`, `webp2png`, `svg2png`, `transpng`; `img_trans`, `img_pure_jpg`, `img_pure_png`; `new_bash` creates a strict script and refuses overwrite |
| Additional Git | `dif`; `gmd` for master-based repositories; `git_corb`; `git_ignore`; `git_readme` |
| tmux | `t`, `ts`, `ta`, `tk`, `tn`, and `ta0` through `ta16` |
| SSH | `sshkey [path]` prints a public key; `pubkey [path]` copies it; `fingerprint` prints MD5 and SHA-256 fingerprints |
| Miscellaneous | `reload`, `cls`, `e`, `ns`, `weather`, `webserver` |

`gpre` shows status, stages all changes, and shows the staged diff. `gps1` pushes the current branch to origin with upstream tracking and rejects detached HEAD. Each function stops at its first failure. When Docker is available, `dkclear` runs `docker system prune -f`, removing stopped containers, unused networks, dangling images, and build cache but not volumes.

Without a path, `sshkey` selects an existing `~/.ssh/id_ed25519`, `id_ecdsa`, or `id_rsa` key in that order and prints its public half. If the private key exists but its `.pub` file is missing, the public key is derived without changing the private key. If no default exists, the command creates a passphrase-free Ed25519 key at `~/.ssh/id_ed25519`; creation happens only when the user enters the command. Pass a private-key or `.pub` path to select another key. `pubkey` uses the same selection and copies the public key to the macOS clipboard. Neither command overwrites an existing key or inspects SSH config, agents, known hosts, or account settings.

```bash
mb                         # run this project's make build target
mt                         # run this project's make test target
gs                         # short Git status
gdiff                      # unstaged repository diff
gd old.txt new.txt         # compare two files; Git returns 1 when they differ
gci "fix: explain change"  # commit tracked modifications with a message
dps                        # running containers
dexec container-name sh    # enter a container
gtest                      # Go race and coverage tests
```

`gd` intentionally means no-index file comparison; use `gdiff` for repository changes. `gm` means `go mod`; use `git merge` for a merge. `gci` and `gcia` reject a missing message. Commands that stage everything, amend, reset, restore, remove an image, prune Docker, or clear the Go module cache run only when explicitly entered.

Private helpers, fixed paths, company services, obsolete Go compatibility flags, insecure module downloads, and tools absent from the declared manifests were deliberately excluded.

## Git global defaults and privacy

`git-defaults.json` supplies aliases such as `git st`, `git lg`, `git ps1`, `git rb`, `git stat`, `git sts`, and `git tig`. It also supplies the `main` initial branch, pull rebase behavior, automatic push upstream, fetch pruning, rerere, delta paging, and VS Code diff/merge defaults. Git, Git LFS, GitHub CLI, delta, tig, LazyGit, and VS Code are all in the installation and strict verification manifests.

One Bite reads the full global configuration including includes and adds only completely missing keys. An existing value is preserved even when it differs. Before the first necessary write, a regular `~/.gitconfig` is copied to `~/.config/1bite/backups/gitconfig.backup-*` with mode 0600. A symlinked `~/.gitconfig` remains under its dotfiles manager. Verification checks presence without printing values.

One Bite never copies or generates `user.name`, `user.email`, credentials, signing keys, organization URL rewrites, proxies, includes, or custom LFS filters. Review identity yourself:

```bash
git config --global --get user.name
git config --global --get user.email
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

The default global ignore contains operating-system metadata, `*.log`, and Go coverage output. It deliberately does not ignore `.vscode/`, `.idea/`, `.cursor/`, `.claude/`, `task.json`, or business-file patterns because repositories may intend to commit them. Existing `core.excludesFile` and its file remain untouched.

## Claude and Codex aliases

Codex aliases are part of the default installation. Claude aliases appear only when the optional Claude command is actually available.

| Alias | Expansion |
| --- | --- |
| `cl` | `claude` |
| `clc` | `claude --continue` |
| `cld` | `claude --dangerously-skip-permissions` |
| `cldc` | `claude --dangerously-skip-permissions --continue` |
| `cx` | `codex` |
| `cxc` | `codex resume --last` |
| `cxd` | `codex --dangerously-bypass-approvals-and-sandbox` |
| `cxdc` | `codex resume --last --dangerously-bypass-approvals-and-sandbox` |

The four aliases containing `d` activate bypass modes only when the user explicitly enters them. Normal aliases use personal CLI configuration. Installation does not change global permission settings or automatically start a CLI. See the [Claude CLI reference](https://code.claude.com/docs/en/cli-reference) and [Codex CLI commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli).

## VS Code extensions

One Bite installs declared extensions through the [official VS Code CLI](https://code.visualstudio.com/docs/configure/command-line), checks existing IDs first, and requests updates only with `--update`.

| Purpose | Extension ID |
| --- | --- |
| Go | `golang.go` |
| Python | `ms-python.python` |
| Ruff | `charliermarsh.ruff` |
| ESLint | `dbaeumer.vscode-eslint` |
| Prettier | `esbenp.prettier-vscode` |
| YAML | `redhat.vscode-yaml` |
| ShellCheck | `timonwong.shellcheck` |
| Sublime Text keymap | `ms-vscode.sublime-keybindings` |

The keymap extension supplies familiar bindings but is not a full Sublime Text clone. One Bite does not modify `keybindings.json` or automatically import old Sublime settings. Ruff complements the Python extension rather than replacing interpreter, debugger, or type-analysis features. ESLint, Prettier, and Ruff follow each project's configuration; global save-time fixes are not forced.

Optional extensions remain user choices:

| Use | Extension | Command |
| --- | --- | --- |
| Docker images, containers, and Compose | [Container Tools](https://code.visualstudio.com/docs/containers/overview) | `code --install-extension ms-azuretools.vscode-containers` |
| TOML editing | [Even Better TOML](https://marketplace.visualstudio.com/items?itemName=tamasfe.even-better-toml) | `code --install-extension tamasfe.even-better-toml` |
| Remote development | [Remote SSH](https://code.visualstudio.com/docs/remote/ssh) | `code --install-extension ms-vscode-remote.remote-ssh` |
| Dev containers | [Dev Containers](https://code.visualstudio.com/docs/devcontainers/containers) | `code --install-extension ms-vscode-remote.remote-containers` |

Optional extensions are updated by VS Code and are absent from One Bite's required verification. Existing `settings.json`, including JSONC comments, is preserved. New environments use Default Dark Modern and a Zsh login terminal. Remote, container, SSH, and separate-profile extension sets require their own installation.

## iTerm2 and tmux

Reopen iTerm2 after configuration. **One Bite** becomes the default profile and uses a Clean Dark palette, MesloLGS Nerd Font 13, no transparency or blur, a Zsh login shell, unlimited scrollback, `xterm-256color`, and mouse reporting. One Bite changes only the global default-profile GUID and its own Dynamic Profile; other profiles remain untouched. If you later choose another default, normal reruns preserve that choice.

| Key | Behavior |
| --- | --- |
| Ctrl or Option + Left/Right | Move by word |
| Cmd + Left/Right, Home/End | Start or end of line |
| Ctrl + A/E | Start or end of line |
| Ctrl + W or Option + Backspace | Delete the previous word |
| Delete | Delete the next character |
| Ctrl + R | fzf history search in an interactive terminal |

Both Option keys send Escape. If Ctrl+Left/Right switches macOS spaces, disable those Mission Control shortcuts yourself; One Bite does not change global keyboard settings.

Recent iTerm2 releases can interpret Finder drops as file transfer in a session it identifies as remote. To paste a path reliably, select the item in Finder, press Option+Cmd+C, and paste the resulting text. Quote shell-special characters. One Bite does not alter shell integration or write undocumented file-transfer preference values.

Dynamic Profile backups and interrupted staging files live outside the watched directory at `~/Library/Application Support/iTerm2/1bite-backups/`. The profile uses a release-stable unique GUID; upgrading from the earlier conflicting GUID replaces only `1bite.json`. Default ownership is recorded privately under `~/.config/1bite/` so a later user-selected default is preserved. Run `./1bite --configure-only` to repair managed settings after reviewing backups, then reopen iTerm2.

| tmux command | Behavior |
| --- | --- |
| `t` | Start tmux |
| `ts` / `tl` | List sessions |
| `tn [name]` | Create a session |
| `ta name`, `ta0`...`ta16` | Attach to a session |
| `to name` | Attach if it exists or create it |
| `tad name` | Attach and detach other clients |
| `tk name` / `tkss name` | Kill a selected session |
| `tksv` | Kill the entire tmux server |
| `tds` | Attach/create by directory name plus six characters of a full-path MD5 |
| `tmuxconf` | Open the selected personal tmux configuration with `$EDITOR` |

One Bite never creates or edits personal tmux configuration or automatically attaches at login. iTerm2 scrollback does not change tmux pane history. Add `set -g history-limit 100000` to personal tmux configuration when longer history is required for new panes. See the [tmux getting-started guide](https://github.com/tmux/tmux/wiki/Getting-Started).

## AutoJump and zoxide

AutoJump provides `j` through its official Zsh integration and uses its own local ranking database. zoxide separately provides `z` and `zi`. Their histories and scoring are unrelated. A function named `j` in an old setup does not prove AutoJump is installed.

```bash
./1bite
# Open a new terminal.
command -v autojump
autojump --version
j --stat
```

For a focused repair, install `homebrew/core/autojump`, run `./1bite --configure-only`, and open a new terminal. Configuration-only mode does not install missing software. History develops as directories are visited; One Bite never imports another Mac's AutoJump or zoxide history. Existing personal `j` commands stay under user control, and missing AutoJump is never disguised with a zoxide wrapper. Sources: [AutoJump](https://github.com/wting/autojump) and [zoxide](https://github.com/ajeetdsouza/zoxide).
