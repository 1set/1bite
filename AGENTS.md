# Working on One Bite

Read `README.md` and `docs/automation.md` first. This directory is an independent repository; never stage, copy, search for credentials in, or publish its parent directory.

## Invariants

- Target Apple Silicon and macOS Tahoe 26+. Do not assume Mac mini-specific hardware.
- Bash 3.2 bootstrap must work before Homebrew or Python is installed.
- Default execution skips healthy tools. Only `--update` upgrades them. Broken managed installations are repaired; unmanaged applications and personal AI configuration are preserved.
- Export the effective Go workspace without setting GOROOT: respect shell or persisted Go GOPATH/GOBIN values, and keep the selected bin directory in login and interactive PATH.
- Git configuration may fill only missing public defaults. Preserve user.name/email, credentials, signing, URL rewrites, includes, existing aliases and an existing core.excludesFile. Public templates must contain no personal identity, private host, proxy or organization-specific value; verify Git LFS, delta, tig, gh and VS Code against declared packages rather than importing a workstation config wholesale.
- Vim defaults live in a managed external vimrc. Preserve the user's ~/.vimrc around one exact source line, back up both changed entry and managed files, reject symlinks, and keep personal overrides after the source line.
- Install Powerlevel10k only after a healthy Oh My Zsh is present. Use the official shallow Git checkout under the effective ZSH_CUSTOM, make it the default only when the user has not selected a theme, preserve personal themes and ~/.p10k.zsh, and update only a clean official checkout under explicit --update.
- Keep managed Zsh behavior in the modules under `~/.config/1bite/zsh/`; update exact managed bytes with backups and keep `.zshrc` as a one-line loader plus untouched personal content. Install the declared Nerd Font casks and verify their regular faces without changing a user's terminal font choice.
- Print the Zsh ownership boundary and restart command after configuration. A non-empty entry gets an explicit review notice; an unchanged rerun reports no change. Unknown loader syntax and dotfile-manager symlinks stop before any configuration write and give the canonical loader for manual merging; never recommend replacing a complete entry file.
- Install Obsidian through its official cask. Keep the reviewed starter under `~/.config/1bite/obsidian-vault`, create only new vault directories through `obn`, use `ob` only to open Obsidian or an existing vault, and never read or update created vaults. Bundle only licensed theme assets and portable vault settings; exclude notes, workspace state, identity, account data, and community plugin data.
- Recognize only the documented One Bite loader variants. Canonicalize them in place, preserve all surrounding content, and stop before writes when a managed-path loader has unknown syntax.
- Default desktop policy prepares official DMGs for manual installation; iTerm2/VS Code remain casks. AI CLIs use official scripts; default Kiro keeps vendor onboarding/integration. --managed-desktop explicitly enables automatic app placement and Kiro shell management. Never label prepared downloads as installed apps. Preserve healthy unmanaged copies and personal configuration; test both policies on disposable machines.
- Prepare the checksum-verified official Doubao Input Method ZIP by default and keep Sogou behind `--with-sogou`. Installation, logout/login, input-source activation, microphone access, and typing/voice checks remain manual; receipts never claim the input method is installed or enabled.
- Keep the One Bite iTerm2 Dynamic Profile on its release-stable unique GUID and the declared MesloLGS Nerd Font PostScript name. Replace only the managed profile, preserve all unrelated profiles, and tell users to open a new One Bite profile window before running the Powerlevel10k wizard.
- Manage the iTerm2 global default GUID separately because Dynamic Profiles ignore the deprecated `Default Bookmark` field. Record ownership, update a still-managed legacy GUID, preserve a later user-selected default, and verify both states without modifying unrelated preferences.
- Load fzf widgets only in an interactive terminal. Support both current `fzf --zsh` output and the shell files shipped by older healthy Homebrew releases; verify Ctrl+R through a pseudo-terminal and preserve later personal bindings.
- Treat the Homebrew `node` formula as the complete baseline Node.js development/runtime environment. Require `node`, `npm`, and `npx`, and exercise an offline local npm build/start lifecycle during disposable-machine verification.
- Give a fresh shell the reviewed built-in Oh My Zsh plugins `git`, `macos`, `vscode`, `web-search`, `extract`, `docker`, and `tmux`. Preserve any existing `plugins` array exactly. Keep fzf, AutoJump, and zoxide on their separately verified native integrations so they are not initialized twice by Oh My Zsh plugins.
- At the end of an install, explain every remaining DMG task with the current session's exact package path, a safely quoted `open` command, numbered copy/eject/launch steps, application-specific first-launch work, and the matching strict verification command. Save the same guide in the run directory. Derive it only from current-session receipts; do not surface stale downloads or unselected applications. If a later stage fails, still explain packages successfully prepared in that run.
- Claude Desktop and Claude Code CLI are disabled by default. Only --with-claude selects their installation, configuration, verification and maintenance; --managed-desktop does not imply selection. Preserve unselected software/configuration.
- Resume by checking actual state. Never trust a completion marker as proof of installation.
- Keep package-list input separate from subprocess stdin. Do not put mutating shell functions in `if`, `!`, `&&` or `||` contexts that disable Bash `errexit`.
- Record only whitelisted environment metadata. Never dump `env`, credentials, user configuration contents, serial numbers, hostnames, proxy URLs or public IPs.
- Keep the bootstrap-safe welcome UI outside session logs. Its full system card may show only the whitelisted system and tool summary, and must respect terminal/color controls.
- `config/sources.tsv` is the installer URL authority; `config/repository-files.txt` is the complete publication boundary.
- Keep `scripts/quality.sh` as the single local/CI quality entry. `make check` and the read-only repository workflow must call it. It may run isolated checks only; real installs and GUI/Docker acceptance stay on disposable external runners.
- Do not execute the full installer on a contributor's Mac to test a change. Use isolated unit tests and disposable test machines.

## Validation and publication

1. Use a patch version bump in `VERSION`.
2. Update the complete config golden fixture deliberately when templates or public manifests change.
3. Stage specific reviewed files. Update `config/repository-files.txt` for additions/removals.
4. Run `./scripts/quality.sh` or its `make check` alias (build → tests → format); inspect the archive and diff. Require the repository `Repository quality gate` status before merging.
5. Commit using conventional commits on `master`, publish only reviewed source files, and create an annotated `v<VERSION>` tag on the tested release commit. Verify the remote tag; never move a published tag.
6. Keep the automated-test-vs-physical-hardware distinction in the README accurate. A green CLI test is not a GUI/login/Docker-on-M4 acceptance test.
