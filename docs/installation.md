# Installation policy and manual steps

The default mode keeps vendor installation and first-launch flows for desktop applications. `--managed-desktop` retains automated placement and managed Kiro shell integration for users who explicitly choose it. GUI sign-in and macOS permission prompts remain manual in both modes.

| Software | Default mode | `--managed-desktop` | Source and update notes |
| --- | --- | --- | --- |
| Google Chrome | Official Universal DMG | Official cask | Chrome retains its updater, existing profiles, and existing installations. |
| ChatGPT / Codex desktop app | Official DMG | Validate signature, architecture, and version, then place the app | Uses the current OpenAI desktop distribution and update feed; checked independently from Codex CLI and recognizes the older Codex.app name. |
| Kiro IDE | Official stable arm64 DMG | Validate and place the official app | Default mode leaves first launch and IDE onboarding to the user. |
| Claude Desktop | Disabled; `--with-claude` prepares the official DMG | Still requires `--with-claude`; validates and places Claude.app | The desktop app and Claude Code CLI have separate sign-in flows. `--update` refreshes the package. |
| Docker Desktop | Official arm64 DMG | Official cask | First launch, privileged components, and engine initialization use the official GUI. Check the engine separately with `--docker-smoke`. |
| iTerm2 | Official cask | Same | The vendor distributes a ZIP; the cask places the app. Existing settings are preserved. |
| VS Code | Official cask | Same | The cask provides the architecture-specific app and the `code` command required for extension setup. |
| Obsidian | Official cask | Same | Installs Obsidian.app. One Bite adds `ob` to open existing vaults and `obn` to create an independent starter; existing vaults are never changed. |
| Codex CLI | Official shell installer | Same | Resolves the current official release and preserves a healthy installation from another source. |
| Claude Code CLI | Disabled; `--with-claude` uses the official Bash installer | Same and still opt-in | Uses the vendor-native installer instead of npm or Homebrew. |
| Kiro CLI | Official Bash installer and native onboarding | Official manifest DMG plus managed Zsh integration | Default mode preserves vendor prompts and onboarding; managed mode validates the app, CLI links, and native dotfile integration. |
| Powerlevel10k | Shallow official checkout in the Oh My Zsh custom theme directory | Same | Selected only when the user has no explicit theme. The user owns `p10k configure`, font selection, and `~/.p10k.zsh`. |
| MesloLGS and JetBrains Mono Nerd Font | Homebrew font casks | Same | Verifies each regular font face. Existing terminal profiles are not changed automatically. |
| LazyGit | Homebrew formula | Same | Provides `lazygit` and the `lg` alias. Normal reruns skip it; `--update` uses Homebrew. |
| Fastfetch | Maintained Homebrew formula | Same | Provides a current, fast system-information view. |
| Neofetch | Official 7.1.0 script pinned by SHA-256 | Same fixed release | Upstream is archived and absent from current Homebrew. A healthy existing command is preserved; an unknown broken command is never overwritten. |
| Sogou Input Method | `--with-sogou` prepares the official ZIP | Same | Installation, input-source activation, and typing verification remain manual. |

## What a successful run means

Default mode installs command-line tools, iTerm2, VS Code, the selected AI CLIs, and prepares desktop DMGs that require human action. Each receipt records the filename, source, version metadata, and SHA-256. A cached package is reused only after its digest is checked. The installer never opens a DMG or replaces the matching app in default mode.

`prepared` means the package is complete; it does not mean the application is installed. `result.json` records `desktop_mode`, `with_claude`, and `manual_steps`. `desktop-installers.json` records packages prepared during that run. A successful default run means automated work and package preparation succeeded. Missing applications remain `null` in inventory and appear under `pending_applications`.

Claude Desktop and Claude Code are enabled together with `--with-claude`. Without that flag they are not downloaded, configured, checked, updated, or removed. Repeat the same flag with rerun, verify, configure, update, and update-check commands. `--managed-desktop` never enables Claude implicitly.

`./1bite --verify` checks the actual selected installations and never treats a receipt as an installed app. Default verification accepts the vendor's own Kiro Zsh integration. `--managed-desktop --verify` additionally enforces the managed Kiro hook contract.

At the end of an install, the generated `manual-steps.txt` gives the exact package path, shell-safe `open` command, drag-to-Applications steps, first-launch tasks, and a strict verification command for that run.

## Ownership and updates

- Normal reruns preserve healthy applications and CLIs and reuse verified packages.
- `--update` updates managed development tools and official CLIs and refreshes current desktop DMGs. The user still runs desktop installers or vendor updaters in default mode.
- `--managed-desktop --update` automatically updates AI apps recorded as managed. Chrome, Docker, iTerm2, and VS Code keep their cask lifecycle. Healthy apps from another source keep their original updater.
- Default Kiro CLI relies on the vendor app for integration and updates. A damaged installation returns to the official installer instead of being silently removed.
- Powerlevel10k updates only on `--update`, only for a clean official checkout. Custom origins, symlinks, and personal `~/.p10k.zsh` stay under their existing owner.
- Managed fonts update through Homebrew. External font files stay with their original source.
- Private settings, authentication, and sign-in are never taken over. Ownership receipts cannot replace a health check.

## Source verification

Executable addresses are defined in [`sources.tsv`](../config/sources.tsv). Desktop DMGs are downloaded into a private temporary directory, checked for image integrity, and only then moved into Downloads. Managed mode also checks the code signature, bundle ID, and arm64 architecture before app replacement; a failed replacement retains a recovery path.

Official references: [Chrome](https://www.google.com/chrome/), [ChatGPT desktop](https://learn.chatgpt.com/docs/app), [Kiro installation](https://kiro.dev/docs/getting-started/installation/), [Claude download](https://claude.com/download), [Docker Desktop for Mac](https://docs.docker.com/desktop/setup/install/mac-install/), [iTerm2](https://iterm2.com/downloads.html), [VS Code for Mac](https://code.visualstudio.com/docs/setup/mac), [Obsidian installation](https://help.obsidian.md/install), [Claude Code setup](https://code.claude.com/docs/en/setup), and [Codex CLI](https://learn.chatgpt.com/docs/codex/cli).
