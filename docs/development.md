# Development guide

This document is the short entry point for contributors. Product behavior and command examples belong in the main README and topic documents; implementation contracts belong here or in [automation.md](automation.md).

## Runtime contract

- Target Apple Silicon and macOS 26 or later.
- Keep the bootstrap compatible with the system Bash 3.2. Do not require Homebrew or Python before bootstrap installs them.
- Use the system Zsh and do not change the login shell.
- Preserve personal configuration, credentials, unknown installations, and software managed by another tool.
- Treat download receipts and pending records as ownership metadata, never as proof that software is healthy.

## Repository layout

- `1bite` builds the plan and dispatches installation stages.
- `scripts/` contains configuration, desktop, official CLI, verification, inventory, update, manual-step, and session helpers.
- `config/` contains reviewed package lists, source URLs, and installed templates.
- `tests/` contains isolated regression tests and the full configuration golden fixture.
- `scripts/quality.sh` is the canonical local and CI quality harness.
- `.github/workflows/quality.yml` runs that same harness for pull requests, pushes to `master`, and manual dispatches.
- `config/repository-files.txt` is the exact public file allowlist and archive manifest.

The installer reads executable download locations from `config/sources.tsv`. Documentation links do not change installation behavior.

## Change workflow

1. Update `VERSION` by one patch release for distributable product changes.
2. Change implementation, tests, and user documentation together.
3. Add or remove public paths in `config/repository-files.txt` deliberately.
4. When any file under `config/` changes, update the complete `tests/fixtures/config-golden.json` fixture after reviewing the new bytes.
5. Run `./scripts/quality.sh` from an independent Git checkout. `make check` is an alias for the same harness.
6. Review the Git diff, archive members, executable modes, and privacy boundary before committing.

The harness builds `dist/1bite.tar.gz`, validates Zsh and shell syntax, runs actionlint, ShellCheck, and shfmt checks, executes the Python regression suite, verifies formatting, confirms that the repository and archive exactly match the allowlist, and fails if a check changes tracked source. Missing quality dependencies fail before any phase runs. The pull request template carries the same change-set checklist into review.

Install the contributor-only quality dependencies with `brew install actionlint ripgrep shellcheck shfmt`. They validate source and test helpers; this command does not install the One Bite developer environment.

`scripts/check-change.py` compares the submission with the base revision supplied by CI. Product paths require exactly one patch version bump plus a regression-test change and user-documentation change. File additions or removals require a publication-manifest change, and every `config/` change requires the complete golden fixture. With no CI base, it checks local staged and unstaged changes against `HEAD`.

## Required CI gate

The `One Bite quality` workflow is the repository-level submission gate. It uses a GitHub-hosted macOS runner with read-only repository permissions and calls `./scripts/quality.sh`; it does not maintain a second list of checks. Configure the `master` branch to require the `Repository quality gate` status before merging. A feature is ready for review only when its implementation, regression tests, user-facing documentation, `VERSION`, publication manifest, and complete configuration golden fixture are consistent and this status is green.

This in-repository gate is intentionally isolated. It must not run `./1bite`, install the selected developer environment, remove runner applications, exercise real DMGs, complete GUI onboarding, or claim physical Docker behavior. Those operations belong to a separate release gate on disposable Macs. Store its run URL and evidence outside the published source, and require both gates before describing a release candidate as fully accepted.

## Behavioral checks

Changes to installation logic should cover a fresh install, a healthy repeat, an explicit update, managed damage repair, and preservation of an unknown or personal installation. Changes to shell files should also cover an existing `.zshrc`, canonicalization of recognized loader variants, duplicate collapse, unchanged repeat runs, and real interactive Zsh behavior with the declared tools installed.

Default desktop mode must download and validate selected DMGs without placing `.app` bundles. Its final guide must be derived from the current run's receipts, exclude old or unselected packages, save `manual-steps.txt` with mode `0600`, and print a strict follow-up verification command. Managed desktop mode has separate placement and Kiro integration checks.

Full installation tests belong on disposable macOS runners because they can install Homebrew packages and replace runner applications. Local development and the repository quality workflow use unit tests, archive checks, and isolated temporary homes.

## Documentation map

- [automation.md](automation.md) defines modes, stages, locks, reports, failure handling, and CI expectations.
- [sources.md](sources.md) records source-review rules and release maintenance.
- [installation.md](installation.md) explains each package manager and desktop policy.
- [shell-editor.md](shell-editor.md) defines managed templates and configuration ownership.
- [obsidian.md](obsidian.md) defines the portable starter, bundled theme, and vault ownership boundary.
- [troubleshooting.md](troubleshooting.md) contains user-facing recovery procedures.

Keep public documentation free of personal paths, account details, internal repositories, credentials, test artifacts, and local release records.
