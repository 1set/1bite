#!/bin/bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3 is required. Run One Bite first, or run: brew install python' >&2
  exit 1
fi
exec python3 "$APP_DIR/qbt.py" "$@"
