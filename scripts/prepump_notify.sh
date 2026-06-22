#!/usr/bin/env bash
# 买点扫描 → OpenClaw 微信
# Usage:
#   ./scripts/prepump_notify.sh scan-intraday   # 14:35 尾盘扫描+推送（主信号）
#   ./scripts/prepump_notify.sh scan-confirm    # 15:10 收盘复核（有变化才推）
#   ./scripts/prepump_notify.sh scan            # 同 scan-intraday
#   ./scripts/prepump_notify.sh send|test|morning
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python3"
[[ -x "$PY" ]] || PY="python3"
SKILL_DIR="${A_SHARE_SKILL_DIR:-$HOME/.cursor/skills/a-share-data}"
OUT_DIR="${A_SHARE_SCAN_OUT:-$SKILL_DIR/output/prepump}"
LATEST="$OUT_DIR/latest.json"
LATEST_INTRADAY="$OUT_DIR/latest_intraday.json"
WATCHLIST="$OUT_DIR/watchlist.json"
MODE="${1:-scan-intraday}"

mkdir -p "$OUT_DIR" "$ROOT/logs/prepump"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NO_PROXY='*'

skip_unless_trading_day() {
  [[ "${PREPUMP_SKIP_NON_TRADING_DAY:-1}" == "1" ]] || return 0
  if "$PY" -c "
from datetime import date
try:
    from tradingagents.dataflows.trade_date import _cn_trading_days_between
    d = date.today()
    days = _cn_trading_days_between(d, d)
    raise SystemExit(0 if d.isoformat() in days else 2)
except Exception:
    raise SystemExit(0)
" 2>/dev/null; then
    return 0
  fi
  echo "skip: not a trading day"
  exit 0
}

run_scan() {
  local intraday_flag=()
  if [[ "${1:-}" == "intraday" ]]; then
    intraday_flag=(--intraday)
  fi
  STAMP=$(date +%Y%m%d_%H%M)
  "$SKILL_DIR/run.sh" screen_prepump.py --top "${PREPUMP_SCAN_TOP:-60}" \
    "${intraday_flag[@]}" --watchlist "$WATCHLIST" --json \
    >"$OUT_DIR/prepump_${STAMP}.json" 2>"$OUT_DIR/prepump_${STAMP}.err"
  ln -sf "prepump_${STAMP}.json" "$OUT_DIR/latest.json"
  if [[ "${1:-}" == "intraday" ]]; then
    ln -sf "prepump_${STAMP}.json" "$OUT_DIR/latest_intraday.json"
  fi
  echo "scan saved: $OUT_DIR/prepump_${STAMP}.json"
}

format_msg() {
  local kind="$1"
  [[ -f "$LATEST" ]] || { echo "missing $LATEST; run scan first" >&2; exit 1; }
  if [[ "$kind" == "morning" ]]; then
    "$PY" "$ROOT/scripts/prepump_notify_format.py" --morning "$LATEST"
  else
    "$PY" "$ROOT/scripts/prepump_notify_format.py" "$LATEST"
  fi
}

SEND=1

case "$MODE" in
  scan|scan-intraday)
    skip_unless_trading_day
    run_scan intraday
    MSG=$(format_msg evening)
    ;;
  scan-confirm)
    skip_unless_trading_day
    run_scan close
    if [[ -f "$LATEST_INTRADAY" ]] && DIFF=$("$PY" "$ROOT/scripts/prepump_confirm_diff.py" "$LATEST_INTRADAY" "$LATEST" 2>/dev/null); then
      MSG=$(format_msg evening)
      MSG="【收盘复核】与14:35相比有变化
$DIFF

$MSG"
    else
      echo "confirm: no entry change vs intraday, skip push"
      exit 0
    fi
    ;;
  send|test)
    MSG=$(format_msg evening)
    ;;
  morning)
    skip_unless_trading_day
    MSG=$(format_msg morning)
    ;;
  *)
    echo "usage: $0 {scan-intraday|scan-confirm|scan|send|morning|test}" >&2
    exit 1
    ;;
esac

echo "$MSG"
PREPUMP_MSG="$MSG" "$ROOT/scripts/premarket_notify.sh" prepump-send
