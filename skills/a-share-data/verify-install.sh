#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_ROOT="$(dirname "$SKILL_DIR")"
PY="$SKILL_DIR/.venv/bin/python3"
FAIL=0

ok() { echo "[OK] $*"; }
fail() { echo "[FAIL] $*"; FAIL=1; }

echo "=== a-share-skill install check ==="

for skill in a-share-data a-share-paper-trading a-share-strategy-mainboard-multi-swing-defensive \
  macd-second-golden-cross macd-trend-resonance-stock-picker tuige-shortline-trading; do
  if [[ -f "$SKILLS_ROOT/$skill/SKILL.md" ]]; then
    ok "skill: $skill"
  else
    fail "missing $SKILLS_ROOT/$skill/SKILL.md"
  fi
done

for f in SKILL.md scripts/fetch_realtime.py scripts/fetch_history.py scripts/fetch_technical.py; do
  [[ -f "$SKILL_DIR/$f" ]] && ok "a-share-data/$f" || fail "missing a-share-data/$f"
done

if [[ -x "$SKILL_DIR/.venv/bin/python3" ]]; then
  ok "venv: $SKILL_DIR/.venv"
else
  fail "venv missing — run: python3 -m venv .venv && .venv/bin/pip install akshare MyTT pandas numpy requests dnspython"
fi

if "$PY" -c "import akshare, pandas, numpy, requests, dns.resolver" 2>/dev/null; then
  ok "python deps (akshare, pandas, numpy, requests, dnspython)"
else
  fail "python deps not importable"
fi

unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy \
  SOCKS_PROXY SOCKS5_PROXY socks_proxy socks5_proxy GIT_HTTP_PROXY GIT_HTTPS_PROXY
export NO_PROXY="*"

QUOTE=$(curl -fsS --max-time 15 "https://qt.gtimg.cn/q=sh600519" 2>/dev/null || true)
if [[ -n "$QUOTE" && "$QUOTE" == *"600519"* ]]; then
  ok "network: Tencent quote API (600519)"
else
  fail "network: cannot reach Tencent quote API (check proxy/VPN)"
fi

KLINE=$(curl -fsS --max-time 15 "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600519,day,,,3,qfq" 2>/dev/null || true)
if [[ -n "$KLINE" && "$KLINE" == *"qfqday"* ]]; then
  ok "network: Tencent daily kline API"
else
  fail "network: cannot reach Tencent kline API"
fi

echo ""
echo "=== optional: script smoke test (run in Terminal.app if Agent proxy blocks Python) ==="
echo "  $SKILL_DIR/run.sh fetch_realtime.py --quote 600519 --json"
echo ""

if [[ $FAIL -eq 0 ]]; then
  echo "All install checks passed."
  exit 0
fi
echo "Some checks failed."
exit 1
