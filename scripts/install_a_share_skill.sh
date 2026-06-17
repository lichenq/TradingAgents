#!/usr/bin/env bash
# Sync vendored a-share-data skill to ~/.cursor/skills/a-share-data (bootstrap venv if missing).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/skills/a-share-data"
DEST="${A_SHARE_SKILL_DIR:-$HOME/.cursor/skills/a-share-data}"

if [[ ! -f "$SRC/run.sh" ]]; then
  echo "missing $SRC/run.sh" >&2
  exit 1
fi

mkdir -p "$(dirname "$DEST")"
rsync -a \
  --exclude .venv --exclude __pycache__ --exclude '*.pyc' --exclude cache \
  "$SRC/" "$DEST/"

PY="$DEST/.venv/bin/python3"
if [[ ! -x "$PY" ]]; then
  python3 -m venv "$DEST/.venv"
  "$DEST/.venv/bin/pip" install -q -r "$DEST/requirements.txt"
fi

echo "a-share-data skill installed at $DEST"
