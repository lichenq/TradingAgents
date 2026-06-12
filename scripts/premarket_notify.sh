#!/usr/bin/env bash
# 盘前摘要 → 个人微信（openclaw-weixin）
# Usage:
#   ./scripts/premarket_notify.sh test          # 用最新 sectors.json 发测试
#   ./scripts/premarket_notify.sh evening       # 跑 node 3 后发夜报 (P0)
#   ./scripts/premarket_notify.sh open          # 跑 node 9 后发开盘确认 (P0)
#   ./scripts/premarket_notify.sh auction       # 跑 node 8，条件满足才推 (P1, 9:15)
#   ./scripts/premarket_notify.sh exhaustion    # 跑 node 10，条件满足才推 (P1, 10:30)
#   ./scripts/premarket_notify.sh evening-send  # 用最新 sectors.json 发夜报（不重跑 node3）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python3"
[[ -x "$PY" ]] || PY="python3"
OUT_DIR="${TRADINGAGENTS_RESULTS_DIR:-$ROOT/results}/premarket_dryrun"
OPENCLAW_BIN="${OPENCLAW_BIN:-openclaw}"
if ! command -v "$OPENCLAW_BIN" >/dev/null 2>&1 && [[ -x "$HOME/.npm-global/bin/openclaw" ]]; then
  OPENCLAW_BIN="$HOME/.npm-global/bin/openclaw"
fi

WEIXIN_CHANNEL="${OPENCLAW_WEIXIN_CHANNEL:-openclaw-weixin}"
WEIXIN_ACCOUNT="${OPENCLAW_WEIXIN_ACCOUNT:-6af8255c243c-im-bot}"
WEIXIN_TARGET="${OPENCLAW_WEIXIN_TARGET:-o9cq809WYr9JuLYry23aicMuyckY@im.wechat}"

MODE="${1:-test}"

send_weixin() {
  local msg="$1"
  # 必须走 Gateway RPC：CLI `message send` 在独立进程里缺 contextToken，微信会静默丢消息
  local params
  params=$(MSG="$msg" WEIXIN_TARGET="$WEIXIN_TARGET" WEIXIN_CHANNEL="$WEIXIN_CHANNEL" \
    WEIXIN_ACCOUNT="$WEIXIN_ACCOUNT" IDEMPOTENCY_KEY="premarket-$(date +%s)-$$" \
    "$PY" -c 'import json, os; print(json.dumps({"to": os.environ["WEIXIN_TARGET"], "message": os.environ["MSG"], "channel": os.environ["WEIXIN_CHANNEL"], "accountId": os.environ["WEIXIN_ACCOUNT"], "idempotencyKey": os.environ["IDEMPOTENCY_KEY"]}))')
  "$OPENCLAW_BIN" gateway call send --params "$params" --json
}

format_msg() {
  local kind="$1" sectors_json="$2"
  "$PY" "$ROOT/scripts/premarket_notify_format.py" "$kind" "$sectors_json"
}

p1_msg_from_check() {
  export CHECK_JSON="$1"
  export ROOT
  "$PY" <<'PY'
import json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(os.environ["ROOT"]) / "scripts"))
from premarket_notify_format import format_p1_auction, format_p1_exhaustion

d = json.loads(os.environ["CHECK_JSON"])
lines = d.get("lines") or []
if d.get("kind") == "auction":
    print(format_p1_auction(lines))
else:
    print(format_p1_exhaustion(lines))
PY
}

p1_triggered() {
  local check_json="$1"
  CHECK_JSON="$check_json" "$PY" -c 'import json, os; print(json.loads(os.environ["CHECK_JSON"]).get("triggered", False))'
}

latest_evening_sectors() {
  ls -t "$OUT_DIR"/*_sectors.json 2>/dev/null | grep -v '_open_' | head -1 || true
}

latest_open_sectors() {
  ls -t "$OUT_DIR"/*_open_sectors.json 2>/dev/null | head -1 || true
}

case "$MODE" in
  test)
    SECTORS=$(latest_evening_sectors)
    [[ -n "$SECTORS" ]] || { echo "no sectors json; run premarket_dryrun.sh --node 3 first" >&2; exit 1; }
    ;;
  evening)
    "$ROOT/scripts/premarket_dryrun.sh" --node 3 >/dev/null
    SECTORS=$(latest_evening_sectors)
    ;;
  open)
    "$ROOT/scripts/premarket_dryrun.sh" --node 9 >/dev/null
    SECTORS=$(latest_open_sectors)
    ;;
  auction)
    "$ROOT/scripts/premarket_dryrun.sh" --node 8 >/dev/null || true
    SECTORS=$(latest_evening_sectors)
    CHECK=$("$PY" "$ROOT/scripts/premarket_p1_check.py" auction ${SECTORS:+--sectors "$SECTORS"})
    if [[ "$(p1_triggered "$CHECK")" != "True" ]]; then
      echo "auction: no alert (skipped)"
      exit 0
    fi
    MSG=$(p1_msg_from_check "$CHECK")
    ;;
  exhaustion)
    "$ROOT/scripts/premarket_dryrun.sh" --node 10 >/dev/null
    SECTORS=$(latest_open_sectors)
    [[ -n "$SECTORS" ]] || SECTORS=$(latest_evening_sectors)
    CHECK=$("$PY" "$ROOT/scripts/premarket_p1_check.py" exhaustion ${SECTORS:+--sectors "$SECTORS"})
    if [[ "$(p1_triggered "$CHECK")" != "True" ]]; then
      echo "exhaustion: no alert (skipped)"
      exit 0
    fi
    MSG=$(p1_msg_from_check "$CHECK")
    ;;
  evening-send)
    SECTORS=$(latest_evening_sectors)
    [[ -n "$SECTORS" ]] || { echo "no sectors json; run premarket_dryrun first" >&2; exit 1; }
    MSG=$(format_msg evening "$SECTORS")
    echo "$MSG"
    send_weixin "$MSG"
    exit 0
    ;;
  *)
    echo "usage: $0 {test|evening|evening-send|open|auction|exhaustion}" >&2
    exit 1
    ;;
esac

if [[ "$MODE" != "auction" && "$MODE" != "exhaustion" ]]; then
  MSG=$(format_msg "$MODE" "$SECTORS")
fi

echo "$MSG"
send_weixin "$MSG"
