# Sources and update procedure

Source baseline reviewed 2026-09-28. [`config/sources.tsv`](../config/sources.tsv) is the only executable allowlist for native installers, distributions, metadata endpoints, and the Powerlevel10k repository. Editing a link in this document does not change installer behavior. Any source change must also update the manifest fixture and pass the repository checks.

Homebrew formulae and casks use the source declared by their official definitions. The default Doubao flow reads current cask metadata from Homebrew's official JSON API, while optional `--with-sogou` reads the local cask metadata. Both additionally restrict the resolved URL to its official distribution prefix in `sources.tsv` and download the fixed-checksum ZIP without installing it.

## Installer and configuration sources

| Component | Executed source | Official reference or update entry point |
| --- | --- | --- |
| Apple Command Line Tools | Local `xcode-select --install` system installer | [Apple Xcode resources](https://developer.apple.com/xcode/resources/) and macOS Software Update |
| Homebrew | `HEAD/install.sh` from `Homebrew/install` | [brew.sh](https://brew.sh/), [installer repository](https://github.com/Homebrew/install), [support tiers](https://docs.brew.sh/Support-Tiers) |
| Claude Code, optional | `https://claude.ai/install.sh` with `--with-claude` | [Setup and version management](https://code.claude.com/docs/en/setup), [settings](https://code.claude.com/docs/en/settings) |
| Codex CLI | `https://chatgpt.com/codex/install.sh` | [CLI installation](https://learn.chatgpt.com/docs/codex/cli), [configuration](https://learn.chatgpt.com/docs/config-file/config-basic) |
| ChatGPT / Codex desktop | OpenAI desktop DMG under `persistent.oaistatic.com/codex-app-prod/` | [Desktop app](https://learn.chatgpt.com/docs/app), [current ChatGPT cask](https://github.com/Homebrew/homebrew-cask/blob/master/Casks/c/chatgpt.rb) |
| Kiro CLI and Zsh | Official installer and onboarding; managed mode uses the official manifest and integration commands | [CLI commands](https://kiro.dev/docs/reference/cli-commands/), [autocomplete](https://kiro.dev/docs/cli/autocomplete/), [2.x trust rules](https://kiro.dev/docs/cli/2x-reference/) |
| Kiro IDE | Architecture-specific DMG from `prod.download.desktop.kiro.dev` | [Downloads](https://kiro.dev/downloads/), [installation](https://kiro.dev/docs/getting-started/installation/), [permissions](https://kiro.dev/docs/permissions/), [data protection](https://kiro.dev/docs/privacy-and-security/data-protection/) |
| Oh My Zsh | Official unattended installer with `KEEP_ZSHRC=yes`, `CHSH=no`, and `RUNZSH=no` | [Unattended installation](https://github.com/ohmyzsh/ohmyzsh#unattended-install) |
| Powerlevel10k | Shallow clone of the official repository into Oh My Zsh custom themes | [Oh My Zsh setup](https://github.com/romkatv/powerlevel10k#oh-my-zsh), [wizard](https://github.com/romkatv/powerlevel10k#configuration-wizard), [fonts](https://github.com/romkatv/powerlevel10k#fonts) |
| Docker Desktop, optional | Official arm64 DMG with `--with-docker`; official cask in managed mode | [Mac installation](https://docs.docker.com/desktop/setup/install/mac-install/), [cask](https://formulae.brew.sh/cask/docker-desktop) |
| iTerm2 | Official Homebrew cask | [Website](https://iterm2.com/), [Dynamic Profiles](https://iterm2.com/documentation-dynamic-profiles.html), [key mappings](https://iterm2.com/documentation-preferences-profiles-keys.html) |
| VS Code | Official Homebrew cask | [Website](https://code.visualstudio.com/), [cask](https://formulae.brew.sh/cask/visual-studio-code) |
| Obsidian | Official Homebrew cask plus a reviewed vault starter | [Install guide](https://help.obsidian.md/install), [cask](https://formulae.brew.sh/cask/obsidian), [configuration folders](https://help.obsidian.md/configuration-folder) |
| Google Chrome | Official Universal DMG; official cask in managed mode | [Website](https://www.google.com/chrome/), [cask definition](https://github.com/Homebrew/homebrew-cask/blob/master/Casks/g/google-chrome.rb) |
| Doubao Input Method, default | Official ZIP prepared from fixed-checksum cask metadata through the official Homebrew JSON API | [Website](https://shurufa.doubao.com/pc), [API](https://formulae.brew.sh/api/cask/doubaoime.json), [cask](https://github.com/Homebrew/homebrew-cask/blob/master/Casks/d/doubaoime.rb) |
| Sogou Input Method, optional | Official ZIP prepared from cask metadata | [Website](https://pinyin.sogou.com/mac/), [release notes](https://pinyin.sogou.com/mac/update_log.php), [cask](https://github.com/Homebrew/homebrew-cask/blob/master/Casks/s/sogouinput.rb) |
| Go | Unversioned official Homebrew formula; managed Zsh adds effective `GOBIN` or every `GOPATH/bin` | [macOS installation and PATH](https://go.dev/doc/install), [releases](https://go.dev/dl/), [formula](https://formulae.brew.sh/formula/go) |
| Node.js | Homebrew `node` formula, including npm and npx | [Downloads](https://nodejs.org/en/download), [formula](https://formulae.brew.sh/formula/node) |
| LazyGit | Homebrew formula with the `lg` alias | [Repository](https://github.com/jesseduffield/lazygit), [formula](https://formulae.brew.sh/formula/lazygit) |
| Fetch tools | Fastfetch through its maintained Homebrew formula; Neofetch 7.1.0 from the archived official repository with a fixed SHA-256 | [Fastfetch formula](https://formulae.brew.sh/formula/fastfetch), [Neofetch 7.1.0](https://github.com/dylanaraps/neofetch/releases/tag/7.1.0) |
| Developer fonts | `font-meslo-lg-nerd-font` and `font-jetbrains-mono-nerd-font` casks | [MesloLGS](https://formulae.brew.sh/cask/font-meslo-lg-nerd-font), [JetBrains Mono](https://formulae.brew.sh/cask/font-jetbrains-mono-nerd-font) |
| Other command-line tools | Official Homebrew formulae listed in [`formulae.txt`](../config/formulae.txt) | `https://formulae.brew.sh/formula/<token>` |

Default mode checks each selected desktop app and downloads an official DMG when it is absent. Docker Desktop requires `--with-docker` after the user reviews the current vendor terms. iTerm2 and VS Code use casks. AI CLIs prefer official scripts. `--managed-desktop` enables app placement and managed Kiro hooks without selecting Docker.

ChatGPT uses the fixed official DMG path and its appcast. Kiro selects the stable arm64 DMG from the official download page. Claude Desktop is accessed only with `--with-claude`, first through the vendor's latest-DMG redirect and then through the official release feed as a fallback. Chrome and selected Docker Desktop use official rolling DMG addresses. A normal rerun reuses selected packages whose digests still match; `--update` refreshes them.

Claude Code and Codex use their own native installers and metadata. Default Kiro CLI runs the vendor installer and preserves its replacement prompt and onboarding. Managed Kiro resolves a digest from the official stable manifest. Recorded hashes support caching and audit; they do not represent an independent vendor signature.

Homebrew checks hashes declared by formulae and casks. Some rolling casks, including Chrome, intentionally use `no_check`; managed app tests therefore also validate signature, bundle ID, arm64 architecture, and launch behavior. Doubao and Sogou have fixed digests and are saved only after their official URL, checksum, and archive integrity are checked; Doubao also requires the expected vendor-installer layout and confines framework symbolic links to that application tree. Community-maintained casks are packaging metadata, not a claim that every cask is maintained by its software vendor.

Native installer scripts are fetched over HTTPS, hashed for the run record, and then executed. That digest is an audit clue rather than an independent signature or long-term version pin. Never replace allowlisted addresses with an arbitrary mirror, private proxy, or unknown script.

Neofetch is the exception to the rolling-script rule: its upstream repository is archived and current Homebrew no longer provides the formula. One Bite installs the official 7.1.0 script only when no healthy `neofetch` command exists and rejects any bytes that do not match the SHA-256 in `sources.tsv`. It never overwrites an unknown broken command. Fastfetch is installed alongside it as the maintained Homebrew-backed alternative.

Input-method installers are kept manual because extracting private components, guessing unattended flags, or writing macOS input-source preferences would bypass the vendor and Apple flows. Package receipts never claim Doubao or Sogou is installed or enabled. Doubao voice input additionally requires the user's microphone decision and an actual speech test.

Chrome automation uses an isolated temporary profile, software rendering, and a test keychain. The test-only `--use-mock-keychain` flag follows [Chrome Launcher's test flags](https://github.com/GoogleChrome/chrome-launcher/blob/main/src/flags.ts) and is never written into the user's browser configuration. See [Chrome Headless mode](https://developer.chrome.com/docs/automation-and-testing/headless).

## Shell, editor, and terminal sources

- VS Code extensions are installed through the [official CLI](https://code.visualstudio.com/docs/configure/command-line) from Marketplace. The declared list contains Go, Python, Ruff, ESLint, Prettier, YAML, ShellCheck, and Microsoft's Sublime Text keymap. Publishers vary; the list is not entirely Microsoft-maintained.
- iTerm2 configuration uses official [Dynamic Profiles](https://iterm2.com/documentation-dynamic-profiles.html) and [profile color fields](https://iterm2.com/documentation-preferences-profiles-colors.html). The One Bite profile has its own stable GUID and selects the installed MesloLGS Nerd Font by PostScript name. iTerm2 deliberately removes the deprecated `Default Bookmark` field from dynamic profiles, so One Bite manages the documented global default GUID separately and preserves a later user override.
- [CODEX_HOME](https://learn.chatgpt.com/docs/config-file/environment-variables) and [CLAUDE_CONFIG_DIR](https://code.claude.com/docs/en/env-vars) choose their configuration directories. One Bite accepts existing absolute paths. Finder-launched apps cannot be assumed to inherit terminal environment variables.
- Powerlevel10k is installed after Oh My Zsh and does not replace an explicit theme. Run `p10k configure` in a newly opened One Bite profile; it creates the user-owned `~/.p10k.zsh`. Existing terminal windows and unrelated profiles keep their font selection.
- The Obsidian starter uses portable vault-local settings documented by Obsidian. Its bundled [Tokyo Night theme](https://github.com/tcmmichaelb139/obsidian-tokyonight) is version 1.1.7 from the official community-theme repository and retains its MIT license. The `wide` snippet is a small One Bite setting. Workspace state, private notes, account data, and community plugin data are excluded.
- `env.zsh` sets `DOCKER_DEFAULT_PLATFORM` to `linux/amd64` when it was not already set. This engine-neutral client setting remains useful with Docker Desktop, another compatible local engine, or a remote Docker context; a project or one-off command can set a different architecture. Services such as the qBittorrent launcher pass their runtime platform explicitly.

## Homebrew trust and network policy

Homebrew 6 loads official definitions and explicitly trusted third-party formulae under its [tap trust policy](https://docs.brew.sh/Tap-Trust). Warnings from a user's Bun, Turso, or other tap do not affect the official Go formula. One Bite never trusts an entire unrelated tap or removes user sources just to hide a warning.

The documented [`HOMEBREW_CURLRC`](https://docs.brew.sh/Manpage#environment) interface accepts an absolute curl configuration. One Bite selects public `config/download.curlrc` only when the variable is unset, preserving private proxy, certificate, and trust settings. The default forces HTTP/1.1 to avoid observed HTTP/2 protocol failures while retaining HTTPS and certificate validation. Direct curl downloads and diagnostics use the same timeout and retry policy based on the [curl options](https://curl.se/docs/manpage.html). It exits predictably on failure and never changes mirrors or disables TLS.

Diagnostics query only `connectivity` entries in `sources.tsv`: Homebrew API, GitHub, GHCR, npm, and selected AI installer endpoints. Requests have connection and total timeouts, send no API key, do not print proxy addresses, and use no IP-discovery service. HTTP 401, 403, or 429 proves reachability but not authorization or quota. TLS, DNS, connection, and server failures are reported. Install mode warns and proceeds to the concrete operation; `--diagnose` returns nonzero for failed probes. A failed final download or verification always fails the install.

## Update metadata

`--check-updates` reads only `maintenance-*` entries from `sources.tsv`. Package queries use the [public Homebrew API](https://formulae.brew.sh/docs/api/); Homebrew itself uses official release metadata. The check does not run `brew update`, and an installed version ahead of the catalog is preserved.

VS Code querying follows Microsoft's [extension gallery implementation](https://github.com/microsoft/vscode/blob/main/src/vs/platform/extensionManagement/common/extensionGalleryService.ts): request public IDs, reject prereleases, and filter for arm64 or universal artifacts. The report exposes engine requirements while the VS Code CLI decides actual compatibility. Git sources use `ls-remote` without fetching or changing the worktree.

## Maintainer checklist

1. Read the vendor's current installation, configuration, platform, and release documentation.
2. Update `sources.tsv`, package manifests, or templates without adding credentials.
3. Bump only the patch version. Update `repository-files.txt` for file-set changes and deliberately regenerate the complete configuration golden fixture.
4. Stage reviewed paths and run `make check` for build, regression tests, format checks, and archive validation.
5. Test fresh and existing installs, skip behavior, preservation, and recovery on a disposable runner; never perform a destructive full install test on a daily-use Mac.
6. Create and push an annotated `v<VERSION>` tag for the verified commit; never move an existing release tag.
7. Compare inventory and download reports and trust actual logged versions rather than historical examples in documentation.
8. Claim Docker engine and GUI keyboard behavior only after testing them on the target physical Mac.

A pinned One Bite commit fixes its process, templates, package set, and verification rules. Upstream `stable` and `latest` channels still move. Reports make changes traceable but cannot guarantee byte-identical third-party software at every future date. Long-term binary reproducibility requires separately archiving vendor artifacts and hashes after reviewing redistribution rights; One Bite does not secretly cache or republish them.

The default Charm tools Glow, Pop, Gum, and Crush come from the [official Charm tap](https://github.com/charmbracelet/homebrew-tap). One Bite trusts those formulae individually rather than the whole tap, and update checks parse generated version/revision declarations without executing remote Ruby.
