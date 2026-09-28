# Maintenance: check, update, verify

Claude Desktop and Claude Code are outside the default maintenance selection. Include them explicitly with `./1bite --with-claude --check-updates` or `./1bite --with-claude --update`. An existing installation never enables them implicitly.

A successful installation is a baseline, not proof that every component stays current. Maintenance separates version discovery, actual health checks, installer changes, and configuration drift. Keep the report from each run instead of using an older successful log as evidence for the current machine.

## Routine commands

```bash
./1bite --check-updates             # Query versions and template differences without changing the machine
./1bite --verify                    # Check that selected tools and configuration still work
# Review updates.md and updates.json in the printed run directory
./1bite --update                    # Perform the selected updates, repairs, and final verification
./1bite --check-updates             # Save a post-update report
```

Use the same `--config-dir DIR` for every check, install, update, and configuration run. Update checks write private reports and may use normal vendor caches, but do not run `brew update`, install or upgrade software, execute installers, fetch Git objects, or write managed configuration. Queries have timeouts, and a failed query never triggers an update.

Exit status 0 from `--check-updates` means the check completed; it does not mean that no updates exist. Read `summary` and each row's `status`. Partial query failure produces `complete: false` and exit status 1. Treat `unknown` as unresolved. The JSON contract is [`updates.schema.json`](updates.schema.json). Use `--verify` for health: a package receipt may show the current version even if its executable was deleted.

## Coverage

| Object | Check | Update path |
| --- | --- | --- |
| Homebrew | Installed command version versus the official GitHub release | `brew update` refreshes Homebrew and metadata; it does not upgrade installed packages by itself |
| Declared formulae | Installed versions versus the live Homebrew stable API, including revisions, aliases, and pins | `./1bite --update`; pinned, disabled, or deprecated packages require review |
| Nerd Font casks | Installed cask versions plus declared regular-face files | Update managed casks; keep externally installed font files |
| Non-AI desktop apps | Actual app bundle version versus the current cask | Default mode refreshes Chrome and Docker DMGs; managed casks update only in managed mode; external apps keep their updater |
| AI apps and CLIs | Actual versions versus official stable metadata | Desktop DMGs in default mode, official CLI scripts, and managed app replacement only with `--managed-desktop --update` |
| Eight VS Code extensions | Marketplace stable releases compatible with arm64 or universal packages | Official VS Code CLI chooses the release compatible with the installed editor |
| Oh My Zsh and Powerlevel10k | Official origin SHA, local SHA, origin identity, and worktree cleanliness | Fast-forward only a clean official checkout; preserve personal files |
| One Bite checkout | Confirmed origin/master SHA versus local SHA and worktree state | Review, then `git pull --ff-only` manually |
| Managed templates | Exact bytes at all managed locations, including shell modules and the Obsidian starter | Review and use `--configure-only`; private AI, VS Code, and created vault files remain preserved |
| Git defaults and global ignore | Verification checks that shared keys and a valid ignore file exist without printing values | `--configure-only` adds missing defaults only; identity, credentials, aliases, URLs, includes, and custom ignore files stay intact |
| macOS and firmware | Manual reminder | System Settings > General > Software Update |

Homebrew is the distribution baseline and can lag a vendor-native channel. An installed newer version is `ahead` and is not downgraded. Prereleases or unusual versions that cannot be compared safely are `manual`. Extension reports expose the candidate and its engine requirement; update VS Code first and let its CLI resolve compatibility. Queries send public extension IDs only, never workspace data or the private extension list.

## Status meanings

| Status | Action |
| --- | --- |
| `current` | Matches this run's reference; still requires health verification |
| `update_available` | Review release notes and schedule the update |
| `ahead` | Keep the newer local version |
| `missing` / `repair_needed` | Repair managed tools with normal setup; use official installers for external apps |
| `different` | Review template or Git differences before changing anything |
| `preserved` | A private AI/editor configuration differs and is intentionally retained |
| `manual` | Review a pin, disabled package, custom origin, unusual version, or system update |
| `unknown` | Repair connectivity or tooling and rerun; do not claim the item is current |

`next_action` is a category, never shell text to execute. `setup` means install or repair, `update` means an explicit upgrade, `original_updater` delegates to its owner, `review` requires inspection, and `none` requires no version operation. `attention_required` includes manual checks; use `summary.update_available` for the actual update count.

## Updating One Bite

```bash
git status --short
git diff
git pull --ff-only
git fetch --tags
git describe --tags --exact-match
./1bite --plan
./1bite --check-updates
```

The checker uses `ls-remote` and does not fetch commits, so it reports a difference without guessing whether it can fast-forward. Resolve divergence and local changes deliberately. Never automate `reset --hard`, forced replacement, or a force push. ZIP copies, forks, and checkouts without an origin require manual maintenance.

Read the new README and [`sources.md`](sources.md). Add newly required files to any external configuration directory and review changes instead of replacing that directory wholesale. Managed env, shell, Zsh, Vim, iTerm2, and Obsidian starter files can be reapplied after review; merge private Claude, Codex, Kiro, VS Code, and existing vault changes manually.

Kiro CLI hooks are managed by their dedicated installer and verifier, not by overwriting private CLI JSON. When the vendor changes initialization or permissions, update the implementation and contract tests together and verify the actual loaded CLI.

## Suggested schedule

| Time | Work |
| --- | --- |
| Weekly, before a new project, or after a failure | Run `--check-updates`; add `--diagnose` and `--verify` when behavior is abnormal |
| Monthly or for a needed security fix | Save work, close affected apps, keep a pre-update report, run `--update`, and keep the post-update report |
| After a major macOS, Docker, Kiro, or terminal change | Test Docker engine startup, terminal keys and completion, AI sign-in, and permission prompts on the Mac |
| After changing the installer or sources | Bump the patch version, update manifest and configuration fixtures, run build/test/format, then validate the same candidate in isolation |

One Bite does not install a background auto-updater, grant permissions, remove pins, clear caches, or bulk-uninstall rollback versions. A failed update preserves completed work; fix the logged problem and rerun the same command. Reverting the One Bite Git checkout does not revert already installed software.
