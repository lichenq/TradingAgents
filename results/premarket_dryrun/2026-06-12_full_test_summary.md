# 盘前 SOP 完整流程测试报告 · 2026-06-12

测试时间：11:48–12:12（午间休市，节点⑧竞价为代理测试）

## 节点结果总览

| 节点 | 计划时间 | 测试状态 | 实测耗时 | 工具 |
|:--:|----------|:--:|:--:|------|
| ① 海外+大盘定调 | 前一晚 21:00 | ✅ | ~10s | a-share-data index/limit-stats |
| ② 新闻扫描 | 前一晚 21:20 | ✅ | ~6s | market-news（DangInvest） |
| ③ 观察单+IF-THEN | 前一晚 21:35 | ⚠️ 半自动 | ~2s | quote 600522 + **人工** |
| ④ TA recommend | 前一晚 22:00 | ✅/⚠️ | 111s~1250s | 见下方说明 |
| ⑤ TA analyze 持仓 | 前一晚 22:30 | ✅ | **505s** | 600522 全量重跑 |
| ⑥ 隔夜刷新 | 次日 7:00 | ✅ | ~7s | index + holding quote |
| ⑦ 晨会前修正 | 次日 7:30 | ⚠️ 人工 | 0 | 读 log 判断 |
| ⑧ 集合竞价 | 次日 9:15 | ⚠️ 代理 | ~1s | 休市时用 quote 代替 |
| ⑨ 涨停+资金流 | 次日 9:35 | ✅ | ~13s | limit-up-pool + fund-flow |
| ⑩ 盘中检查 | 10:00/10:30/14:00 | ✅ | ~4s | index + fund-flow |
| ⑪ 盘后复盘 | 15:30 | 未测 | — | 可选 analyze |

## 当日盘面快照（测试时）

- 上证 +1.27%，涨停 98 / 跌停 4
- 行业资金 TOP5：电池 50.9亿、证券 47.1亿、小金属 45.4亿、工业金属 33.4亿、军工 20.6亿
- 持仓 600522：50.09 元（+1.66%），成本 50.6，浮亏约 0.8%

## ④ recommend 策略对比

| 策略 | 耗时 | 结果 |
|------|------|------|
| em_hot_momentum | 111s | **0 只命中**（初筛过严） |
| trend_pullback + validate-top 3 | 1250s (~21min) | 有推荐（含京东方等，读 SQLite/深度研判） |

**建议**：定时任务用 `trend_pullback`，`--skip-curation`，`validate-top=2`；或 **仅周末** 跑完整 recommend，平日只用 a-share-data。

## ⑤ analyze 缓存

本次 **未命中缓存**，600522 全量 analyze **505s**。若 SQLite 已有同日报告，应 <10s。

建议 cron：`analyze` **仅周末或持仓变更时**触发，或加 `--force` 控制。

## 脚本

```bash
# 仅盘前快节点（~25s）
./scripts/premarket_dryrun.sh --node morning

# 前一晚（含 TA，耗时长）
./scripts/premarket_dryrun.sh --node evening

# 全流程
./scripts/premarket_dryrun.sh --node all
```

输出：`results/premarket_dryrun/<run_id>.json` + `.log`

## 建议 cron 时间表（待你确认）

| cron | 节点 | 命令 |
|------|------|------|
| 0 21 * * 1-5 | ①②③ | `--node 1` + `--node 2` + `--node 3` |
| 0 22 * * 0 | ④⑤ | `--node evening` |
| 0 7 * * 1-5 | ⑥⑦ | `--node morning`（或拆 6、7） |
| 15 9 * * 1-5 | ⑧ | `--node 8` |
| 35 9 * * 1-5 | ⑨ | `--node 9` |
| 0 10,30 14 * * 1-5 | ⑩ | `--node 10` |

环境变量可选：
`PREMARKET_HOLDING_TICKER=600522 PREMARKET_HOLDING_COST=50.6 PREMARKET_HOLDING_SHARES=200`
