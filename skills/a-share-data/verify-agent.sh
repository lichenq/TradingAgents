#!/usr/bin/env bash
# Smoke test for Cursor Agent: same entry as production (run.sh + curl-first).
set -uo pipefail
SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
export A_SHARE_PREFER_CURL=1
FAIL=0
WARN=0
ok() { echo "[OK] $*"; }
warn() { echo "[WARN] $*"; WARN=1; }
fail() { echo "[FAIL] $*"; FAIL=1; }

run_json() {
  local label="$1"
  shift
  local optional=0
  if [[ "${1:-}" == "--optional" ]]; then
    optional=1
    shift
  fi
  local out=/tmp/a_share_agent_smoke.out
  local err=/tmp/a_share_agent_smoke.err
  if "$SKILL_DIR/run.sh" "$@" >"$out" 2>"$err" && grep -qE '^[\[{]' "$out" 2>/dev/null; then
    ok "$label"
    return 0
  fi
  local msg
  msg="$(head -2 "$err" "$out" 2>/dev/null | tr '\n' ' ')"
  if [[ "$optional" == "1" ]]; then
    warn "$label — ${msg:-no output}"
    return 0
  fi
  fail "$label — ${msg:-no output}"
  return 1
}

echo "=== a-share-data Agent smoke (run.sh) ==="
run_json "quote 600519" fetch_realtime.py --quote 600519 --json
run_json "sector 600519" fetch_sector_info.py --no-concepts 600519 --json
run_json "fund-flow 600519" fetch_realtime.py --fund-flow 600519 --days 5 --json
run_json "kline 600519" fetch_history.py --kline 600519 --start 2026-05-01 --end 2026-05-24 --freq d --json

if [[ $FAIL -eq 0 ]]; then
  if [[ $WARN -eq 1 ]]; then
    echo "Core checks passed (some optional warnings on stderr)."
    exit 0
  fi
  echo "All agent smoke checks passed."
  exit 0
fi
echo "Some agent smoke checks failed."
exit 1
