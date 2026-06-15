#!/usr/bin/env bash
# 验证推荐复盘 + 板块预测闭环健康度（供 launchd / 手动周检）
# Exit codes (from verify_recommendation_loop.py):
#   0 = ok
#   1 = warn (样本不足、forecast 未积累、job 日志偏旧等)
#   2 = critical (DB 缺失、launchd 未加载当 VERIFY_REQUIRE_LAUNCHD=1)
#
# Usage:
#   ./scripts/verify_recommendation_loop.sh
#   ./scripts/verify_recommendation_loop.sh --json
#   VERIFY_REQUIRE_LAUNCHD=1 ./scripts/verify_recommendation_loop.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python3"
[[ -x "$PY" ]] || PY="python3"
ENV_FILE="$ROOT/scripts/premarket_jobs.env"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck source=/dev/null
  source "$ENV_FILE"
fi

export TRADINGAGENTS_RESULTS_DIR="${TRADINGAGENTS_RESULTS_DIR:-$ROOT/results}"

exec "$PY" "$ROOT/scripts/verify_recommendation_loop.py" "$@"
