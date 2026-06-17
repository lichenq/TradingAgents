# Cursor Agent 执行说明

## 必须这样调用

```bash
SKILL_DIR="$HOME/.cursor/skills/a-share-data"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
export NO_PROXY='*' no_proxy='*'
"$SKILL_DIR/run.sh" <script.py> [args...]
```

禁止：`python3 scripts/...`（不会清代理，也不会 curl 优先）。

## 网络权限（关键）

Agent **不会**自动转到 macOS Terminal.app，只在 Cursor 内置终端执行。

推荐：**Settings → Agents → Sandbox Networking → Allow All**。`~/.cursor/sandbox.json` 域名白名单可作补充；改完后新开一轮对话。

验证：`"$SKILL_DIR/verify-agent.sh"`。核心项：报价、行业、K 线。`--fund-flow` 走 `push2his.eastmoney.com`，偶发 `Empty reply` 与 Allow All 无关，属东财端点/线路问题。

## 冒烟

```bash
"$SKILL_DIR/verify-agent.sh"
```

通过即表示 Agent 环境可直连：报价、行业、资金流、K 线。

## 实现要点

- `run.sh` 设置 `A_SHARE_PREFER_CURL=1`
- `scripts/http_util.py`：curl 优先 → requests 兜底，统一清代理
- `fetch_sector_info`：优先 **emweb** 公司概况（避开易断的 push2）
- `fetch_realtime --fund-flow`：curl 优先拉 push2his
