#!/usr/bin/env bash
# 本地重置 OpenClaw 微信凭证（无需在微信里找「解除绑定」）
# 原理：清空 local_token_list 后重新扫码，服务端会走完整授权而非「已连接过」。
set -euo pipefail

ACCOUNT="${OPENCLAW_WEIXIN_ACCOUNT:-6af8255c243c-im-bot}"
WX_DIR="${HOME}/.openclaw/openclaw-weixin"
BK="${WX_DIR}/backup-$(date +%Y%m%d-%H%M%S)"

echo "==> 备份到 ${BK}"
mkdir -p "${BK}/accounts"
[[ -f "${WX_DIR}/accounts.json" ]] && cp "${WX_DIR}/accounts.json" "${BK}/"
for f in "${WX_DIR}/accounts/${ACCOUNT}"*; do
  [[ -e "$f" ]] && cp -a "$f" "${BK}/accounts/"
done

echo "==> 删除本地过期凭证"
rm -f "${WX_DIR}/accounts/${ACCOUNT}.json"
rm -f "${WX_DIR}/accounts/${ACCOUNT}.sync.json"
rm -f "${WX_DIR}/accounts/${ACCOUNT}.context-tokens.json"

if [[ -f "${WX_DIR}/accounts.json" ]]; then
  python3 - <<PY
import json
from pathlib import Path
p = Path("${WX_DIR}/accounts.json")
ids = json.loads(p.read_text()) if p.is_file() else []
ids = [i for i in ids if i != "${ACCOUNT}"]
p.write_text(json.dumps(ids, indent=2) + "\n")
PY
fi

echo "==> 重启 gateway"
openclaw gateway restart

echo ""
echo "下一步请在终端执行（需手机扫码）："
echo "  openclaw channels login --channel openclaw-weixin"
echo ""
echo "若出现「已将此 OpenClaw 连接到微信」即成功。"
echo "若仍显示「已连接过」，请改用另一微信号扫码，或联系 OpenClaw 微信渠道支持。"
echo ""
echo "扫码成功后，务必在微信里给 OpenClaw 机器人发一条消息（如 ping），建立会话。"
echo "确认 context-tokens 文件生成后再测推送。"
echo ""
echo "验证推送："
echo "  cd $(cd "$(dirname "$0")/.." && pwd)"
echo "  PREPUMP_MSG='【测试】推送已恢复' ./scripts/premarket_notify.sh prepump-send"
