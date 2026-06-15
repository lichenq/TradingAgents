#!/usr/bin/env bash
# 盘前/夜报定时任务入口（launchd / cron 调用）
# Usage:
#   ./scripts/premarket_jobs.sh audit       # 收盘复盘 N 日前推荐
#   ./scripts/premarket_jobs.sh evening      # audit + ①②③④ + 微信夜报
#   ./scripts/premarket_jobs.sh open         # ⑨ 开盘确认 + 微信
#   ./scripts/premarket_jobs.sh auction      # ⑧ 竞价预警（条件触发）
#   ./scripts/premarket_jobs.sh exhaustion   # ⑩ 主题衰竭（条件触发）
#   ./scripts/premarket_jobs.sh status       # 查看 launchd 任务状态
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python3"
[[ -x "$PY" ]] || PY="python3"
LOG_DIR="${TRADINGAGENTS_RESULTS_DIR:-$ROOT/results}/premarket_dryrun/jobs"
ENV_FILE="$ROOT/scripts/premarket_jobs.env"

mkdir -p "$LOG_DIR"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck source=/dev/null
  source "$ENV_FILE"
fi

export PREMARKET_RUN_FORECAST="${PREMARKET_RUN_FORECAST:-1}"
export PREMARKET_RUN_AUDIT="${PREMARKET_RUN_AUDIT:-1}"
export PREMARKET_AUDIT_DAYS="${PREMARKET_AUDIT_DAYS:-3,5}"
export PREMARKET_RUN_TA="${PREMARKET_RUN_TA:-1}"
export PREMARKET_RUN_DEEP="${PREMARKET_RUN_DEEP:-0}"
export PREMARKET_LLM="${PREMARKET_LLM:-1}"
export PREMARKET_LLM_OPEN="${PREMARKET_LLM_OPEN:-0}"
export PREMARKET_DEEP_CURATE="${PREMARKET_DEEP_CURATE:-1}"
export TRADINGAGENTS_FORCE_CURATION="${TRADINGAGENTS_FORCE_CURATION:-1}"
export PREMARKET_SKIP_NON_TRADING_DAY="${PREMARKET_SKIP_NON_TRADING_DAY:-1}"
export TRADINGAGENTS_RESULTS_DIR="${TRADINGAGENTS_RESULTS_DIR:-$ROOT/results}"

unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NO_PROXY='*'

JOB="${1:-}"
JOB_LOG="$LOG_DIR/${JOB}-$(date +%Y%m%d_%H%M%S).log"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$JOB_LOG"
}

skip_unless_trading_day() {
  [[ "$PREMARKET_SKIP_NON_TRADING_DAY" == "1" ]] || return 0
  if "$PY" -c "
from datetime import date
from tradingagents.dataflows.trade_date import _cn_trading_days_between
d = date.today()
days = _cn_trading_days_between(d, d)
raise SystemExit(0 if d.isoformat() in days else 2)
" 2>/dev/null; then
    return 0
  fi
  log "skip: today is not an A-share trading day"
  exit 0
}

run_audit() {
  skip_unless_trading_day
  [[ "$PREMARKET_RUN_AUDIT" == "1" ]] || { log "audit skipped (PREMARKET_RUN_AUDIT=0)"; return 0; }
  log "start backtest audit horizons=${PREMARKET_AUDIT_DAYS}"
  local d
  IFS=',' read -ra _audit_days <<< "$PREMARKET_AUDIT_DAYS"
  for d in "${_audit_days[@]}"; do
    d="${d// /}"
    [[ -n "$d" ]] || continue
    log "audit --days-ago $d"
    if "$PY" "$ROOT/scripts/auto_backtest_audit.py" --days-ago "$d" >>"$JOB_LOG" 2>&1; then
      log "audit $d done"
    else
      log "audit $d failed (continuing)"
    fi
  done
    log "audit done"
  log "audit KPI report"
  if "$PY" "$ROOT/scripts/audit_report.py" --print >>"$JOB_LOG" 2>&1; then
    log "audit report done"
  else
    log "audit report failed (continuing)"
  fi
}

run_evening() {
  skip_unless_trading_day
  run_audit
  log "start evening pipeline (forecast=${PREMARKET_RUN_FORECAST} ta=${PREMARKET_RUN_TA} deep=${PREMARKET_RUN_DEEP})"
  "$ROOT/scripts/premarket_dryrun.sh" --node evening >>"$JOB_LOG" 2>&1
  log "send evening WeChat"
  "$ROOT/scripts/premarket_notify.sh" evening-send >>"$JOB_LOG" 2>&1
  log "evening done"
}

run_notify_mode() {
  local mode="$1"
  skip_unless_trading_day
  log "start notify mode=$mode"
  "$ROOT/scripts/premarket_notify.sh" "$mode" >>"$JOB_LOG" 2>&1
  log "$mode done"
}

show_status() {
  local uid plists loaded=0
  uid="$(id -u)"
  plists=(
    com.tradingagents.premarket.audit
    com.tradingagents.premarket.evening
    com.tradingagents.premarket.auction
    com.tradingagents.premarket.open
    com.tradingagents.premarket.exhaustion
    com.tradingagents.premarket.verify
  )
  echo "LaunchAgents (gui/$uid):"
  for label in "${plists[@]}"; do
    if launchctl print "gui/$uid/$label" &>/dev/null; then
      echo "  ✓ $label"
      loaded=$((loaded + 1))
    else
      echo "  ✗ $label (not loaded)"
    fi
  done
  echo ""
  echo "Recent job logs: $LOG_DIR"
  ls -t "$LOG_DIR"/*.log 2>/dev/null | head -5 || echo "  (none)"
  echo ""
  echo "Schedule (Mon–Fri, local time):"
  echo "  15:05  audit     推荐复盘 + AI反思"
  echo "  21:30  evening   夜报生成 + 微信"
  echo "  09:15  auction   竞价预警（条件触发）"
  echo "  09:35  open      开盘确认 + 微信"
  echo "  10:30  exhaustion 主题衰竭（条件触发）"
  echo "  Fri 16:10 verify    推荐/预测闭环健康检查"
  echo ""
  echo "Manual: ./scripts/verify_recommendation_loop.sh"
  echo "Env: ${ENV_FILE} $([[ -f $ENV_FILE ]] && echo '(loaded)' || echo '(missing — copy from .example)')"
}

run_verify() {
  log "start recommendation loop verify"
  if "$ROOT/scripts/verify_recommendation_loop.sh" >>"$JOB_LOG" 2>&1; then
    log "verify ok (exit 0)"
  else
    ec=$?
    log "verify finished exit=$ec (1=warn 2=critical)"
    return "$ec"
  fi
}

case "$JOB" in
  audit) run_audit ;;
  evening) run_evening ;;
  open) run_notify_mode open ;;
  auction) run_notify_mode auction ;;
  exhaustion) run_notify_mode exhaustion ;;
  verify) run_verify ;;
  status) show_status ;;
  *)
    echo "usage: $0 {audit|evening|open|auction|exhaustion|verify|status}" >&2
    exit 1
    ;;
esac
