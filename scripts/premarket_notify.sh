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

ensure_openclaw_gateway() {
  if "$OPENCLAW_BIN" gateway status 2>/dev/null | grep -q "Connectivity probe: ok"; then
    return 0
  fi
  echo "openclaw gateway not reachable; restarting..." >&2
  "$OPENCLAW_BIN" gateway restart >&2 || true
  for _ in 1 2 3 4 5 6 10 12; do
    sleep "$_"
    if "$OPENCLAW_BIN" gateway status 2>/dev/null | grep -q "Connectivity probe: ok"; then
      echo "openclaw gateway ready" >&2
      return 0
    fi
  done
  echo "openclaw gateway still unreachable after restart" >&2
  return 1
}

check_weixin_session() {
  local ctx_path="${HOME}/.openclaw/openclaw-weixin/accounts/${WEIXIN_ACCOUNT}.context-tokens.json"
  if [[ -f "$ctx_path" ]] && CTX_PATH="$ctx_path" WEIXIN_TARGET="$WEIXIN_TARGET" "$PY" -c '
import json, os, sys
from pathlib import Path
p = Path(os.environ["CTX_PATH"])
t = os.environ.get("WEIXIN_TARGET", "")
d = json.loads(p.read_text())
if t in d and d[t]:
    sys.exit(0)
sys.exit(1)
' 2>/dev/null; then
    # Gateway 插件用内存会话 + context_token 发信；本地 bot_token 文件可能陈旧，勿用裸 API 探测误拦
    return 0
  fi
  CHECK_WEIXIN_SESSION=1 WEIXIN_ACCOUNT="$WEIXIN_ACCOUNT" WEIXIN_TARGET="$WEIXIN_TARGET" "$PY" <<'PY'
import json, os, sys, urllib.request
from pathlib import Path

home = Path.home()
acc_path = home / ".openclaw/openclaw-weixin/accounts" / f"{os.environ['WEIXIN_ACCOUNT']}.json"
ctx_path = home / ".openclaw/openclaw-weixin/accounts" / f"{os.environ['WEIXIN_ACCOUNT']}.context-tokens.json"
if not acc_path.is_file():
    print("weixin account file missing", file=sys.stderr)
    sys.exit(2)
acc = json.loads(acc_path.read_text())
ctx_map = json.loads(ctx_path.read_text()) if ctx_path.is_file() else {}
to = os.environ.get("WEIXIN_TARGET", "")
body = json.dumps({
    "msg": {
        "from_user_id": "",
        "to_user_id": to,
        "client_id": "session-probe",
        "message_type": 1,
        "message_state": 2,
        "item_list": [{"type": 1, "text_item": {"text": "session-probe"}}],
        "context_token": ctx_map.get(to),
    },
    "base_info": {"bot_agent": "OpenClaw"},
}).encode()
req = urllib.request.Request(
    f"{acc['baseUrl'].rstrip('/')}/ilink/bot/sendmessage",
    data=body,
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {acc['token']}",
    },
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode()
except Exception as e:
    print(f"weixin session probe failed: {e}", file=sys.stderr)
    sys.exit(2)
data = json.loads(raw)
err = data.get("errcode", 0)
if err == 0:
    sys.exit(0)
if err == -14:
    print(
        "weixin session timeout (errcode -14): bot_token 已过期。"
        "扫码若提示「已连接过」不会刷新 token。"
        "请先在微信里解除 OpenClaw 绑定，再执行 openclaw channels login --channel openclaw-weixin，"
        "直到出现「已将此 OpenClaw 连接到微信」。",
        file=sys.stderr,
    )
    sys.exit(14)
print(f"weixin API errcode={err} errmsg={data.get('errmsg')}", file=sys.stderr)
sys.exit(2)
PY
}

send_weixin() {
  local msg="$1"
  local ec=0
  ensure_openclaw_gateway || return 1
  check_weixin_session || ec=$?
  if [[ "$ec" -ne 0 ]]; then
    if [[ "$ec" == 14 ]]; then
      echo "hint: 微信机器人会话已过期，需手机扫码: openclaw channels login --channel openclaw-weixin" >&2
    fi
    return "$ec"
  fi
  # Gateway RPC + accountId，插件侧会带上 contextToken
  local params
  params=$(MSG="$msg" WEIXIN_TARGET="$WEIXIN_TARGET" WEIXIN_CHANNEL="$WEIXIN_CHANNEL" \
    WEIXIN_ACCOUNT="$WEIXIN_ACCOUNT" IDEMPOTENCY_KEY="premarket-$(date +%s)-$$" \
    "$PY" -c 'import json, os; print(json.dumps({"to": os.environ["WEIXIN_TARGET"], "message": os.environ["MSG"], "channel": os.environ["WEIXIN_CHANNEL"], "accountId": os.environ["WEIXIN_ACCOUNT"], "idempotencyKey": os.environ["IDEMPOTENCY_KEY"]}))')
  local out
  if ! out=$("$OPENCLAW_BIN" gateway call send --params "$params" --json 2>&1); then
    echo "$out" >&2
    return 1
  fi
  echo "$out"
  if echo "$out" | grep -q '"messageId"'; then
    return 0
  fi
  echo "weixin send returned no messageId" >&2
  return 1
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
  local f
  for f in $(ls -t "$OUT_DIR"/*_open_sectors.json 2>/dev/null); do
    [[ -s "$f" ]] || continue
    echo "$f"
    return 0
  done
}

case "$MODE" in
  test)
    SECTORS=$(latest_evening_sectors)
    [[ -n "$SECTORS" ]] || { echo "no sectors json; run premarket_dryrun.sh --node 3 first" >&2; exit 1; }
    ;;
  evening)
    PREMARKET_RUN_FORECAST="${PREMARKET_RUN_FORECAST:-1}"
    PREMARKET_RUN_TA="${PREMARKET_RUN_TA:-1}"
    export PREMARKET_RUN_FORECAST PREMARKET_RUN_TA
    "$ROOT/scripts/premarket_dryrun.sh" --node evening >/dev/null
    SECTORS=$(latest_evening_sectors)
    ;;
  open)
    "$ROOT/scripts/premarket_dryrun.sh" --node 9 >/dev/null || true
    SECTORS=$(latest_open_sectors)
    [[ -n "$SECTORS" ]] || { echo "open: node 9 failed (no open_sectors json)" >&2; exit 1; }
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
  open-send)
    SECTORS=$(latest_open_sectors)
    [[ -n "$SECTORS" ]] || { echo "no open_sectors json; run premarket_dryrun --node 9 first" >&2; exit 1; }
    MSG=$(format_msg open "$SECTORS")
    echo "$MSG"
    send_weixin "$MSG"
    exit 0
    ;;
  *)
    echo "usage: $0 {test|evening|evening-send|open|open-send|auction|exhaustion}" >&2
    exit 1
    ;;
esac

if [[ "$MODE" != "auction" && "$MODE" != "exhaustion" ]]; then
  MSG=$(format_msg "$MODE" "$SECTORS")
fi

echo "$MSG"
send_weixin "$MSG"
