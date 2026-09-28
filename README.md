<p align="center">
  <img src="assets/logo.png" width="224" alt="One Bite logo">
</p>

<h1 align="center">One Bite</h1>

<p align="center">The first bite for a ready-to-use Apple Silicon Mac running macOS 26 or later.</p>

One Bite turns a new Mac into a ready-to-use development environment while preserving personal configuration and unmanaged software. The name means the **First Bite**: the first repeatable step that prepares a Mac for work, reflected by the bite in the Apple logo.

## Install

```bash
gh repo clone 1set/1bite
cd 1bite
./1bite --plan
./1bite
```

Run the installer as your normal administrator account, without `sudo`. If `gh` is unavailable, use **Code → Download ZIP**, extract the archive, and run `bash 1bite` from that directory. Complete the Apple Command Line Tools prompt if macOS opens it, then rerun the same command.

## What it sets up

| Area | Default behavior |
| --- | --- |
| Developer tools | Installs Git, Git LFS, GitHub CLI (`gh`), Go, Node.js with npm/npx, Python, uv, `rg`, duf, fd, bat, fzf, AutoJump, zoxide, jq, yq, tmux, LazyGit, shellcheck, ffmpeg, ImageMagick, and related tools with Homebrew. |
| Terminal and editor | Installs iTerm2, VS Code and extensions; configures Zsh, Vim, Git defaults, a global ignore file, and modular aliases/functions. |
| Notes | Installs Obsidian and a reusable vault starter with Tokyo Night, the `wide` CSS snippet, portable vault settings, and empty attachment/template folders. |
| Prompt and fonts | Installs Oh My Zsh, Powerlevel10k, MesloLGS Nerd Font, and JetBrains Mono Nerd Font while preserving personal themes and configuration. |
| Input method | Prepares the checksum-verified official Doubao Input Method ZIP for manual installation, microphone permission, and activation. Sogou remains opt-in. |
| AI command-line tools | Installs Codex CLI and Kiro CLI from their official installers. Claude Code is opt-in. |
| Desktop applications | Downloads official DMGs for Chrome, ChatGPT, and Kiro IDE when the apps are missing. Docker Desktop is opt-in. |
| Optional Docker apps | Provides separate, opt-in launchers for useful local services. These apps never start as part of the main installer. |

Docker Desktop is disabled by default because its terms may not fit every workplace. Review the current vendor terms, then add `--with-docker` whenever you install, update, or verify it. Claude Desktop and Claude Code are also disabled by default and use `--with-claude`.

## Finish downloaded application and input-method installations

`prepared` means an installer package was downloaded and checked. It does **not** mean the application or input method is installed.

At the end of a run, the installer prints a numbered guide for every package prepared in that run. Each desktop item includes the exact package path, a shell-safe `open` command, application-specific first-launch tasks, and these required steps:

1. Open the DMG with the printed command.
2. Drag the `.app` into **Applications** and wait for the copy to finish.
3. Eject the mounted installer disk.
4. Start the app from **Applications**, sign in, and approve required macOS permissions.
5. If Docker Desktop was selected, wait for the engine to start. Complete Kiro IDE and Kiro CLI onboarding separately.

The same guide is saved as `manual-steps.txt` in the run directory printed by the installer. After all manual work is complete, run the exact `--verify` command shown in that guide. A Docker-selected run also prints a separate `--docker-smoke` command for use after the engine is running.

The default run checks Doubao Input Method independently after the managed Python runtime is available. A healthy installed copy is preserved; otherwise its ZIP is prepared before the remaining tools and final verification. If a later stage fails, the failure summary still gives the exact package path and manual steps for the completed download. Follow its numbered steps to extract and run the vendor installer, log out and back in when requested, add Doubao under **System Settings > Keyboard > Text Input**, grant microphone access for voice input, and test both typing and speech. Sogou is selected only with `--with-sogou` and has its own independent installed/prepared decision at the same early boundary.

## Common commands

```bash
./1bite --plan                       # Show the selected work
./1bite                              # Install or repair the default selection
./1bite --update                     # Update managed tools and refresh DMGs
./1bite --welcome                    # Show the colorful One Bite system card
./1bite --verify                     # Strictly verify actual installations
./1bite --check-updates              # Report available updates without changing them
./1bite --configure-only             # Apply managed configuration templates only
./1bite --managed-desktop            # Place supported desktop apps automatically
./1bite --with-docker                # Include Docker Desktop after reviewing its terms
./1bite --with-claude                # Include Claude Desktop and Claude Code
./1bite --with-sogou                  # Prepare the Sogou installer for manual setup
./1bite --docker-smoke                # Check Docker after the engine is running
ob                                      # Open Obsidian and its remembered vault
ob ~/Documents/Notes/Work              # Open an existing vault
obn ~/Documents/Notes/Work --open      # Create and open a new starter vault
```

Repeat the same selection flags when rerunning or verifying. `--managed-desktop` does not enable Docker or Claude.

## Configuration ownership

- `.zshrc`, `.zprofile`, and `.vimrc` remain user-owned. The installer updates one recognized loader line in place and preserves the content before and after it.
- Managed Zsh files live in `~/.config/1bite/zsh/`. Upgrades back up and atomically replace those modules; put personal overrides after the loader in `.zshrc`.
- After configuration, the terminal prints the exact ownership boundary, the `exec zsh` command for non-iTerm shells, and the iTerm2 reopen step. A non-empty entry gets a backup and review notice; an unchanged rerun reports no change. Unknown One Bite loader syntax and dotfile-manager symlinks stop before configuration writes and print the canonical line for manual merging.
- Go exports the effective `GOPATH` and adds an explicit `GOBIN`, or each `GOPATH/bin`, to `PATH`. Existing overrides take precedence.
- Git receives missing shared defaults and a conservative global ignore file. User identity, credentials, signing, URL rewrites, includes, aliases, and an existing custom ignore file are preserved.
- Powerlevel10k preserves explicit themes and `~/.p10k.zsh`. The managed One Bite iTerm2 profile selects the installed MesloLGS Nerd Font. Open a new iTerm2 window with that profile before running `p10k configure`; existing windows keep their previous profile and font.
- After iTerm2 is reopened, One Bite is the default profile. If you later choose another default, reruns preserve your selection. Other profiles and their settings are never rewritten.
- In an interactive terminal, fzf provides Ctrl+R history search, Ctrl+T file search, and Option+C directory search across current and older supported Homebrew releases.
- A fresh shell enables the built-in Oh My Zsh plugins for Git, macOS, VS Code, web search, archive extraction, Docker-compatible CLIs, and tmux. Existing plugin selections remain untouched. The plugin and shell aliases do not install Docker Desktop and also work with compatible engines. fzf, AutoJump, and zoxide use their native integrations to avoid duplicate hooks.
- `ob` opens Obsidian or an existing vault. `obn` copies the managed starter only into a new directory. Existing vaults remain user-owned and later One Bite updates affect only future vaults.

## Terminal welcome and fetch tools

Interactive runs open with a compact, true-color One Bite mark. `./1bite --welcome` renders a larger neofetch-style card with non-sensitive system details; it does not create logs or change the machine. Set `ONE_BITE_BANNER=never` to hide the startup mark, or `ONE_BITE_BANNER=always` to show it when output is redirected. `NO_COLOR` and `ONE_BITE_COLOR=never` keep output plain.

One Bite installs both `neofetch` and `fastfetch`. Because Neofetch was archived upstream and removed from current Homebrew, the installer fetches the official 7.1.0 script from its version tag and requires the published SHA-256 stored in `sources.tsv`. Fastfetch comes from the maintained Homebrew formula. Existing healthy Neofetch commands are preserved.

## Documentation

- [Installation policy](docs/installation.md)
- [Shell, editor, Git, aliases, and terminal configuration](docs/shell-editor.md)
- [Obsidian installation and vault starter](docs/obsidian.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Updates and maintenance](docs/maintenance.md)
- [Official software sources](docs/sources.md)
- [Automation and result files](docs/automation.md)
- [Developer guide](docs/development.md)
- [Optional Docker apps](apps/README.md)

The current installer version is recorded in [`VERSION`](VERSION). Formal releases use a matching `v<VERSION>` tag.
