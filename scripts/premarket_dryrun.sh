#!/usr/bin/env bash
# 盘前 SOP：板块轮动 + 代表股 / 潜在大涨候选（不含自持仓）
# Usage:
#   ./scripts/premarket_dryrun.sh --node morning   # 盘前快节点 ~30s
#   ./scripts/premarket_dryrun.sh --node evening   # 前一晚 + 可选 TA 初筛
#   ./scripts/premarket_dryrun.sh --node all
#   PREMARKET_RUN_TA=1 ./scripts/premarket_dryrun.sh --node 4   # TOP3 板块 Stage1
#   PREMARKET_RUN_FORECAST=1  # 节点③前跑 sector_rotation_forecast
#   PREMARKET_RUN_DEEP=1 ./scripts/premarket_dryrun.sh --node 11  # 深度补全+精选
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
A_SHARE="$HOME/.cursor/skills/a-share-data/run.sh"
TA="$HOME/.cursor/skills/trading-agents/run.sh"
PY="$ROOT/.venv/bin/python3"
[[ -x "$PY" ]] || PY="python3"
OUT_DIR="${TRADINGAGENTS_RESULTS_DIR:-$ROOT/results}/premarket_dryrun"
TA_STRATEGY="${PREMARKET_TA_STRATEGY:-trend_pullback}"
TA_VALIDATE_TOP="${PREMARKET_TA_VALIDATE_TOP:-0}"
TA_TOP_N="${PREMARKET_TA_TOP_N:-40}"
PREMARKET_RUN_TA="${PREMARKET_RUN_TA:-0}"
PREMARKET_RUN_FORECAST="${PREMARKET_RUN_FORECAST:-0}"
PREMARKET_RUN_DEEP="${PREMARKET_RUN_DEEP:-0}"
PREMARKET_TA_BOARDS="${PREMARKET_TA_BOARDS:-3}"

unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NO_PROXY='*'
export TRADINGAGENTS_MARKET=cn
export TRADINGAGENTS_OUTPUT_LANGUAGE=Chinese
export TRADINGAGENTS_RESULTS_DIR="${TRADINGAGENTS_RESULTS_DIR:-$ROOT/results}"

NODE="${1:-}"
if [[ "${1:-}" == "--node" ]]; then
  NODE="${2:-all}"
fi
[[ -n "$NODE" ]] || NODE="all"

mkdir -p "$OUT_DIR"
RUN_ID="$(date +%Y-%m-%d_%H%M%S)"
LOG="$OUT_DIR/${RUN_ID}.log"
REPORT="$OUT_DIR/${RUN_ID}.json"
SECTOR_JSON="$OUT_DIR/${RUN_ID}_sectors.json"
touch "$LOG"

log() { echo "[$(date '+%H:%M:%S')] $*" >> "$LOG"; }
run_step() {
  local id="$1" name="$2"
  shift 2
  log "▶ Node $id: $name"
  local t0=$SECONDS
  if "$@" >>"$LOG" 2>&1; then
    local elapsed=$((SECONDS - t0))
    log "✓ Node $id done (${elapsed}s)"
    printf '"%s":{"name":"%s","ok":true,"elapsed_s":%s}' "$id" "$name" "$elapsed"
  else
    local elapsed=$((SECONDS - t0))
    log "✗ Node $id FAILED (${elapsed}s)"
    printf '"%s":{"name":"%s","ok":false,"elapsed_s":%s}' "$id" "$name" "$elapsed"
  fi
}

should_run() {
  local id="$1"
  if [[ "$id" == "11" && "${PREMARKET_RUN_DEEP:-0}" != "1" ]]; then
    return 1
  fi
  case "$NODE" in
    all|evening|morning) ;;
    [0-9]|10|11) [[ "$NODE" == "$id" ]] || return 1 ;;
    *) echo "Unknown --node $NODE (use all|evening|morning|1-11)" >&2; exit 1 ;;
  esac
  case "$NODE" in
    evening)
      if [[ "$id" == "11" ]]; then return 0; fi
      [[ "$id" =~ ^[1-4]$ ]] || return 1
      ;;
    morning) [[ "$id" =~ ^[5-9]$|^10$ ]] || return 1 ;;
  esac
  return 0
}

latest_evening_sectors() {
  ls -t "$OUT_DIR"/*_sectors.json 2>/dev/null | grep -v '_open_' | head -1 || true
}

JSON_PARTS=()
COMPARE_BASE=""
log "=== sector-rotation premarket run node=$NODE run_id=$RUN_ID ==="

# ① 大盘情绪
if should_run 1; then
  p=$(run_step 1 "index" "$A_SHARE" fetch_realtime.py --index --json)
  JSON_PARTS+=("$p")
  p=$(run_step 1b "limit-stats" "$A_SHARE" fetch_realtime.py --limit-stats --json)
  JSON_PARTS+=("$p")
fi

# ② 新闻催化（人工映射供应链）
if should_run 2; then
  p=$(run_step 2 "market-news" "$A_SHARE" fetch_realtime.py --market-news --news-limit 20 --json)
  JSON_PARTS+=("$p")
fi

# ③ 板块轮动快照：资金流 TOP + 涨停代表股
if should_run 3; then
  if [[ "$PREMARKET_RUN_FORECAST" == "1" ]]; then
    log "▶ Node 3-pre: sector_rotation_forecast"
    t0=$SECONDS
    if "$PY" "$ROOT/scripts/sector_rotation_forecast.py" >>"$LOG" 2>&1; then
      log "✓ Node 3-pre forecast done ($((SECONDS - t0))s)"
    else
      log "✗ Node 3-pre forecast failed (continuing)"
    fi
  fi
  log "▶ Node 3: sector-rotation-summary"
  t0=$SECONDS
  if "$PY" "$ROOT/scripts/premarket_sector_summary.py" >"$SECTOR_JSON" 2>>"$LOG"; then
    COMPARE_BASE="$SECTOR_JSON"
    log "✓ Node 3 done sectors=$SECTOR_JSON"
    JSON_PARTS+=("\"3\":{\"name\":\"sector-rotation\",\"ok\":true,\"elapsed_s\":$((SECONDS-t0)),\"output\":\"$SECTOR_JSON\"}")
  else
    JSON_PARTS+=("\"3\":{\"name\":\"sector-rotation\",\"ok\":false,\"elapsed_s\":$((SECONDS-t0))}")
  fi
fi

# ④ TA 初筛：TOP3 板块 Stage1（PREMARKET_RUN_TA=1）
if should_run 4 && [[ "$PREMARKET_RUN_TA" == "1" ]]; then
  TA_SECTORS="$SECTOR_JSON"
  [[ -n "$TA_SECTORS" && -f "$TA_SECTORS" ]] || TA_SECTORS=$(latest_evening_sectors)
  if [[ -n "$TA_SECTORS" && -f "$TA_SECTORS" ]]; then
    log "▶ Node 4: ta-recommend TOP${PREMARKET_TA_BOARDS} boards"
    t0=$SECONDS
    if PREMARKET_TA_STRATEGY="$TA_STRATEGY" PREMARKET_TA_TOP_N="$TA_TOP_N" \
      PREMARKET_TA_VALIDATE_TOP="$TA_VALIDATE_TOP" PREMARKET_TA_BOARDS="$PREMARKET_TA_BOARDS" \
      "$PY" "$ROOT/scripts/premarket_ta_recommend.py" "$TA_SECTORS" --write-back --boards "$PREMARKET_TA_BOARDS" >>"$LOG" 2>&1; then
      log "✓ Node 4 done (${SECONDS-t0}s)"
      JSON_PARTS+=("\"4\":{\"name\":\"ta-recommend\",\"ok\":true,\"elapsed_s\":$((SECONDS-t0)),\"sectors\":\"$TA_SECTORS\"}")
    else
      JSON_PARTS+=("\"4\":{\"name\":\"ta-recommend\",\"ok\":false,\"elapsed_s\":$((SECONDS-t0))}")
    fi
  else
    log "⊘ Node 4 skipped (no sectors json)"
    JSON_PARTS+=("\"4\":{\"name\":\"ta-recommend\",\"ok\":false,\"error\":\"no_sectors_json\"}")
  fi
elif should_run 4; then
  log "⊘ Node 4 skipped (set PREMARKET_RUN_TA=1 to enable)"
  JSON_PARTS+=("\"4\":{\"name\":\"ta-recommend\",\"ok\":true,\"skipped\":true}")
fi

# ⑪ 深度补全：SQLite 优先，缺报告才 analyze；可选 Stage3 精选
if should_run 11; then
  DEEP_SECTORS="$SECTOR_JSON"
  [[ -n "$DEEP_SECTORS" && -f "$DEEP_SECTORS" ]] || DEEP_SECTORS=$(latest_evening_sectors)
  if [[ -n "$DEEP_SECTORS" && -f "$DEEP_SECTORS" ]]; then
    log "▶ Node 11: deep-fill (max_new=${PREMARKET_DEEP_MAX_NEW:-2})"
    t0=$SECONDS
    DEEP_ARGS=(--write-back)
    [[ "${PREMARKET_DEEP_CURATE:-0}" == "1" ]] && DEEP_ARGS+=(--curate)
    if "$PY" "$ROOT/scripts/premarket_deep_fill.py" "$DEEP_SECTORS" "${DEEP_ARGS[@]}" >>"$LOG" 2>&1; then
      log "✓ Node 11 done (${SECONDS-t0}s)"
      JSON_PARTS+=("\"11\":{\"name\":\"deep-fill\",\"ok\":true,\"elapsed_s\":$((SECONDS-t0))}")
    else
      JSON_PARTS+=("\"11\":{\"name\":\"deep-fill\",\"ok\":false,\"elapsed_s\":$((SECONDS-t0))}")
    fi
  else
    JSON_PARTS+=("\"11\":{\"name\":\"deep-fill\",\"ok\":false,\"error\":\"no_sectors_json\"}")
  fi
fi

# ⑤ 连板已合并进节点 ③⑨ sector summary
if should_run 5; then
  log "⊘ Node 5 merged into sector summary (consecutive_limit_leaders)"
  JSON_PARTS+=("\"5\":{\"name\":\"consecutive-limit\",\"ok\":true,\"merged\":true}")
fi

# ⑥ 次日晨间刷新
if should_run 6; then
  p=$(run_step 6 "refresh-index" "$A_SHARE" fetch_realtime.py --index --json)
  JSON_PARTS+=("$p")
fi

# ⑦ 主题是否仍成立（读 sector 快照 + 新闻）
if should_run 7; then
  log "▶ Node 7: theme-check (review $SECTOR_JSON + log)"
  JSON_PARTS+=("\"7\":{\"name\":\"theme-check\",\"ok\":true,\"elapsed_s\":0,\"note\":\"manual_or_compare_prev_run\"}")
fi

# ⑧ 竞价：上证 open vs 昨收
if should_run 8; then
  p=$(run_step 8 "auction-index" "$A_SHARE" fetch_realtime.py --quote sh000001 --json)
  JSON_PARTS+=("$p")
fi

# ⑨ 开盘确认：对比前一快照（若存在）
OPEN_SECTORS="${OUT_DIR}/${RUN_ID}_open_sectors.json"
PREV_SECTORS=""
PREMARKET_OPEN_FORECAST="${PREMARKET_OPEN_FORECAST:-1}"
if should_run 9; then
  if [[ "$PREMARKET_OPEN_FORECAST" == "1" ]]; then
    log "▶ Node 9-pre: sector_rotation_forecast (open refresh)"
    t0_fc=$SECONDS
    if "$PY" "$ROOT/scripts/sector_rotation_forecast.py" >>"$LOG" 2>&1; then
      log "✓ Node 9-pre forecast done ($((SECONDS - t0_fc))s)"
    else
      log "✗ Node 9-pre forecast failed (continuing)"
    fi
  fi
  log "▶ Node 9: open-confirm sector snapshot"
  t0=$SECONDS
  PREV_SECTORS="$COMPARE_BASE"
  if [[ -z "$PREV_SECTORS" || ! -f "$PREV_SECTORS" ]]; then
    PREV_SECTORS=$(ls -t "$OUT_DIR"/*_sectors.json 2>/dev/null | grep -v "_open_" | grep -v "$RUN_ID" | head -1 || true)
  fi
  if [[ -n "$PREV_SECTORS" && -f "$PREV_SECTORS" ]]; then
    CMP_CMD=(env PREMARKET_LLM_OPEN=0 "$PY" "$ROOT/scripts/premarket_sector_summary.py" "--compare" "$PREV_SECTORS")
  else
    CMP_CMD=("$PY" "$ROOT/scripts/premarket_sector_summary.py")
  fi
  if "${CMP_CMD[@]}" >"$OPEN_SECTORS" 2>>"$LOG"; then
    log "✓ Node 9 done open=$OPEN_SECTORS compare=${PREV_SECTORS:-none}"
    JSON_PARTS+=("\"9\":{\"name\":\"open-confirm\",\"ok\":true,\"elapsed_s\":$((SECONDS-t0)),\"output\":\"$OPEN_SECTORS\",\"compare_with\":\"${PREV_SECTORS:-}\"}")
  else
    JSON_PARTS+=("\"9\":{\"name\":\"open-confirm\",\"ok\":false,\"elapsed_s\":$((SECONDS-t0))}")
  fi
fi

# ⑩ 盘中：主题是否衰竭
if should_run 10; then
  p=$(run_step 10 "intraday-fund-flow" "$A_SHARE" fetch_industry_fund_flow.py --limit 10 --json)
  JSON_PARTS+=("$p")
fi

{
  echo "{"
  echo "  \"run_id\": \"$RUN_ID\","
  echo "  \"node_mode\": \"$NODE\","
  echo "  \"focus\": \"sector_rotation_only\","
  echo "  \"sector_summary\": \"${SECTOR_JSON}\","
  echo "  \"finished_at\": \"$(date -Iseconds)\","
  echo "  \"log\": \"$LOG\","
  echo "  \"steps\": {"
  IFS=,
  echo "    ${JSON_PARTS[*]}"
  echo "  }"
  echo "}"
} >"$REPORT"

log "=== done report=$REPORT ==="
echo "Report:        $REPORT"
echo "Sector summary: $SECTOR_JSON"
echo "Log:           $LOG"
if [[ -f "$SECTOR_JSON" ]]; then
  SECTOR_SHOW="$SECTOR_JSON"
elif [[ -f "${OUT_DIR}/${RUN_ID}_open_sectors.json" ]]; then
  SECTOR_SHOW="${OUT_DIR}/${RUN_ID}_open_sectors.json"
else
  SECTOR_SHOW=""
fi
if [[ -n "$SECTOR_SHOW" ]]; then
  "$PY" "$ROOT/scripts/premarket_sector_summary.py" --print "$SECTOR_SHOW"
fi
if [[ -f "${OUT_DIR}/${RUN_ID}_open_sectors.json" && -f "$SECTOR_JSON" && "$SECTOR_JSON" != "${OUT_DIR}/${RUN_ID}_open_sectors.json" ]]; then
  echo "--- open vs prior snapshot ---"
  "$PY" -c "
import json, sys
d=json.load(open(sys.argv[1]))
delta=d.get('delta_vs_previous',{})
for x in delta.get('rank_up',[]): print(f\"↑ {x['industry']} #{x['from']} → #{x['to']}\")
for ind in delta.get('new_in_top',[]): print(f\"+ 新进入TOP: {ind}\")
if not delta.get('rank_up') and not delta.get('new_in_top'): print('（排名无显著变化）')
" "${OUT_DIR}/${RUN_ID}_open_sectors.json"
fi
