#!/usr/bin/env bash
# 安装 / 卸载 macOS LaunchAgents 定时任务
# Usage:
#   ./scripts/install_premarket_launchd.sh install
#   ./scripts/install_premarket_launchd.sh uninstall
#   ./scripts/install_premarket_launchd.sh status
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_SRC="$ROOT/scripts/launchd"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
UID_NUM="$(id -u)"
DOMAIN="gui/$UID_NUM"

labels=(
  com.tradingagents.premarket.audit
  com.tradingagents.premarket.evening
  com.tradingagents.premarket.auction
  com.tradingagents.premarket.open
  com.tradingagents.premarket.exhaustion
  com.tradingagents.premarket.verify
  com.tradingagents.prepump.intraday
  com.tradingagents.prepump.confirm
  com.tradingagents.prepump.morning
)

render_plist() {
  local src="$1" dest="$2"
  sed \
    -e "s|@TRADINGAGENTS_ROOT@|$ROOT|g" \
    -e "s|@HOME@|$HOME|g" \
    "$src" >"$dest"
}

bootout_one() {
  local label="$1"
  launchctl bootout "$DOMAIN/$label" 2>/dev/null || true
}

bootstrap_one() {
  local label="$1" plist="$2"
  bootout_one "$label"
  launchctl bootstrap "$DOMAIN" "$plist"
  launchctl enable "$DOMAIN/$label" 2>/dev/null || true
}

install_all() {
  mkdir -p "$ROOT/logs/premarket" "$ROOT/results/premarket_dryrun/jobs" "$ROOT/logs/prepump"
  chmod +x "$ROOT/scripts/premarket_jobs.sh" "$ROOT/scripts/verify_recommendation_loop.sh" \
    "$ROOT/scripts/prepump_notify.sh"

  if [[ ! -f "$ROOT/scripts/premarket_jobs.env" ]]; then
    cp "$ROOT/scripts/premarket_jobs.env.example" "$ROOT/scripts/premarket_jobs.env"
    echo "Created scripts/premarket_jobs.env from example"
  fi

  for label in "${labels[@]}"; do
    src="$PLIST_SRC/$label.plist"
    dest="$LAUNCH_AGENTS/$label.plist"
    [[ -f "$src" ]] || { echo "missing $src" >&2; exit 1; }
    render_plist "$src" "$dest"
    bootstrap_one "$label" "$dest"
    echo "loaded $label"
  done

  echo ""
  echo "Installed ${#labels[@]} LaunchAgents → $LAUNCH_AGENTS"
  "$ROOT/scripts/premarket_jobs.sh" status
}

uninstall_all() {
  for label in "${labels[@]}"; do
    bootout_one "$label"
    rm -f "$LAUNCH_AGENTS/$label.plist"
    echo "removed $label"
  done
}

show_status() {
  "$ROOT/scripts/premarket_jobs.sh" status
}

ACTION="${1:-install}"
case "$ACTION" in
  install) install_all ;;
  uninstall) uninstall_all ;;
  status) show_status ;;
  *)
    echo "usage: $0 {install|uninstall|status}" >&2
    exit 1
    ;;
esac
