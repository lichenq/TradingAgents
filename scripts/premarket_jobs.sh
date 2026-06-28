#!/usr/bin/env bash
# 推荐复盘定时任务（launchd / 手动）
# Usage:
#   ./scripts/premarket_jobs.sh audit    # 收盘复盘 N 日前推荐
#   ./scripts/premarket_jobs.sh verify   # 闭环健康检查
#   ./scripts/premarket_jobs.sh status   # 查看 launchd 任务状态
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python3"
[[ -x "$PY" ]] || PY="python3"
LOG_DIR="${TRADINGAGENTS_RESULTS_DIR:-$ROOT/results}/audit_jobs"
ENV_FILE="$ROOT/scripts/premarket_jobs.env"

mkdir -p "$LOG_DIR"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck source=/dev/null
  source "$ENV_FILE"
fi

export PREMARKET_RUN_AUDIT="${PREMARKET_RUN_AUDIT:-1}"
export PREMARKET_AUDIT_DAYS="${PREMARKET_AUDIT_DAYS:-3,5}"
export PREMARKET_SKIP_NON_TRADING_DAY="${PREMARKET_SKIP_NON_TRADING_DAY:-1}"
export RECOMMEND_RUN="${RECOMMEND_RUN:-1}"
export RECOMMEND_STRATEGY="${RECOMMEND_STRATEGY:-trend_pullback}"
export RECOMMEND_BOARD="${RECOMMEND_BOARD:-auto}"
export RECOMMEND_TOP_N="${RECOMMEND_TOP_N:-120}"
export RECOMMEND_VALIDATE_TOP="${RECOMMEND_VALIDATE_TOP:-5}"
export RECOMMEND_CONCURRENCY="${RECOMMEND_CONCURRENCY:-3}"
export RECOMMEND_WRITE_MD="${RECOMMEND_WRITE_MD:-1}"
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

run_recommend() {
  skip_unless_trading_day
  [[ "$RECOMMEND_RUN" == "1" ]] || { log "recommend skipped (RECOMMEND_RUN=0)"; return 0; }
  log "start daily recommend strategy=${RECOMMEND_STRATEGY} board=${RECOMMEND_BOARD}"
  local rec_args=(
    "$PY" "$ROOT/scripts/run_recommend.py"
    --strategy "$RECOMMEND_STRATEGY"
    --top-n "$RECOMMEND_TOP_N"
    --validate-top "$RECOMMEND_VALIDATE_TOP"
    --concurrency "$RECOMMEND_CONCURRENCY"
    --json
  )
  if [[ -n "$RECOMMEND_BOARD" ]]; then
    rec_args+=(--board "$RECOMMEND_BOARD")
  fi
  if [[ "$RECOMMEND_WRITE_MD" == "1" ]]; then
    rec_args+=(--md)
  fi
  if "${rec_args[@]}" >>"$JOB_LOG" 2>&1; then
    log "recommend done"
  else
    ec=$?
    log "recommend failed exit=$ec"
    return "$ec"
  fi
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
  log "audit KPI report"
  if "$PY" "$ROOT/scripts/audit_report.py" --print >>"$JOB_LOG" 2>&1; then
    log "audit report done"
  else
    log "audit report failed (continuing)"
  fi
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

show_status() {
  local uid plists loaded=0
  uid="$(id -u)"
  plists=(
    com.tradingagents.recommend.daily
    com.tradingagents.premarket.audit
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
  echo "  15:15  recommend  每日量化推荐（Stage3 入库）"
  echo "  15:05  audit      推荐复盘 + AI 反思"
  echo "  Fri 16:10 verify   推荐闭环健康检查"
  echo ""
  echo "Manual: ./scripts/premarket_jobs.sh recommend|audit"
  echo "Env: ${ENV_FILE} $([[ -f $ENV_FILE ]] && echo '(loaded)' || echo '(missing — copy from .example)')"
}

case "$JOB" in
  recommend) run_recommend ;;
  audit) run_audit ;;
  verify) run_verify ;;
  status) show_status ;;
  *)
    echo "usage: $0 {recommend|audit|verify|status}" >&2
    exit 1
    ;;
esac
