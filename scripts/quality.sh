#!/bin/bash
set -euo pipefail

ROOT=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
cd "$ROOT"

if (($#)); then
  printf 'Usage: %s\n' "${0##*/}" >&2
  exit 2
fi

for tool in git make python3 zsh awk actionlint rg shellcheck shfmt; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'Missing quality dependency: %s\n' "$tool" >&2
    exit 69
  fi
done

if ! git rev-parse --show-toplevel >/dev/null 2>&1 ||
  [[ $(git rev-parse --show-toplevel) != "$ROOT" ]]; then
  printf 'Run the quality harness from an independent One Bite Git checkout.\n' >&2
  exit 2
fi

SNAPSHOT_DIR=$(mktemp -d "${TMPDIR:-/tmp}/1bite-quality.XXXXXX")
trap 'rm -rf "$SNAPSHOT_DIR"' EXIT HUP INT TERM
snapshot_source() {
  if git rev-parse --verify HEAD >/dev/null 2>&1; then
    git diff --binary HEAD --
  else
    git diff --cached --binary --
    git diff --binary --
  fi
}

snapshot_source >"$SNAPSHOT_DIR/before.diff"

run_phase() {
  local name=$1
  shift
  printf '\n==> %s\n' "$name"
  "$@"
}

run_phase 'Build, syntax, static analysis, and publication boundary' make build
run_phase 'Isolated regression tests' make test
run_phase 'Formatting and public-text policy' make format-check

snapshot_source >"$SNAPSHOT_DIR/after.diff"
if ! cmp -s "$SNAPSHOT_DIR/before.diff" "$SNAPSHOT_DIR/after.diff"; then
  printf 'Quality checks changed tracked source files. Review and commit or revert those changes.\n' >&2
  diff -u "$SNAPSHOT_DIR/before.diff" "$SNAPSHOT_DIR/after.diff" || true
  exit 1
fi

printf '\nOne Bite quality gate passed. Full installation acceptance remains a separate disposable-Mac gate.\n'
