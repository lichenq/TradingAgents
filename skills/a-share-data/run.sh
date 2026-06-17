#!/usr/bin/env bash
# Run a-share-data scripts with skill venv; bypass broken IDE proxy for market APIs.
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy \
  SOCKS_PROXY SOCKS5_PROXY socks_proxy socks5_proxy GIT_HTTP_PROXY GIT_HTTPS_PROXY
export NO_PROXY="*"
export no_proxy="*"
# Cursor Agent: prefer curl (often works when requests hits sandbox DNS/proxy issues).
export A_SHARE_PREFER_CURL="${A_SHARE_PREFER_CURL:-1}"
export A_SHARE_SKILL_DIR="$SKILL_DIR"
exec "$SKILL_DIR/.venv/bin/python3" "$SKILL_DIR/scripts/_run.py" "$SKILL_DIR/scripts/${1:?usage: run.sh <script.py> [args...]}" "${@:2}"
