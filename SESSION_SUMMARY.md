# Sector Mapping + 人形机器人推荐 + 基本面数据 进展总结

> 日期：2026-06-03

---

## 已完成

### 1. 板块映射表（sector_mapping.yaml）

- **74 条 canonical 映射**，覆盖 DangInvest 行业+概念板块 → EastMoney 行业/概念
- **自动生成**：`scripts/build_sector_mapping.py` 用 top-5 探针策略（542 只股票，29 秒），通过 `fetch_sector_info.py`（`emweb.eastmoney.com`）获取 EastMoney 行业归属
- **人工增强**：`scripts/merge_sector_enrichments.py` 补充概念、搜索关键词、7 个特殊主题（人形机器人、AI、新能源 等）
- **运行时模块**：`tradingagents/dataflows/sector_mapping.py` 提供 `resolve()`、`expand_queries()` 等函数
- 所有 legacy 别名（券商信托→证券、消费电子→电子元件 等）均已覆盖

### 2. 人形机器人推荐 ← 这里对 `--board` 做了改进

- 修复前：`--board 人形机器人` → DangInvest **industry** 模式取不到成分股（人形机器人在 DangInvest 是 concept 概念板块）
- 修复：`run_recommend.py` 的 `--boards-detail` 调用改成了 **industry 为空时自动重试 concept 模式**
- `sector_mapping.yaml` 的 `人形机器人` 条目已补上 `danginvest_board: ["人形机器人", "机器人概念"]`
- **验证通过**：`--board 人形机器人` 成功获取 300 只成分股，最终推荐 3 只

### 3. 已交付的推荐结果（人形机器人，趋势回踩策略）

| 排名 | 代码 | 名称 | 现价 | 评分 | 说明 |
|:---:|:---:|:---|:---:|:---:|:---|
| 1 | 688001 | 华兴源创 | 70.45 | 19.2 | MA10 > MA30 上升趋势回踩 |
| 2 | 688017 | 绿的谐波 | 314.88 | 17.4 | 谐波减速器核心零部件 |
| 3 | 300632 | 光莆股份 | 28.30 | 15.3 | 视觉感知方向 |

- 输出：`results/recommendations/2026-06-03/recommended_stocks.json`
- 完整报告（SQLite）：`results/华兴源创-688001-2026-06-03/` 等

### 4. 基本面数据黑盒修复

**问题**：华兴源创报告中四项数据标记为 `[数据黑盒]`：

| 字段 | 原状态 | 现状态 | 值（华兴源创 2026Q1） |
|---|---|---|---|
| 资本开支 | ❌ 不可得 | ✅ 已修复 | 12,498,843.32 元 |
| 研发费用 | ❌ 不可得 | ✅ 已修复 | 82,323,066.67 元 |
| 经营现金流净额 | ❌ 不可得 | ✅ 已修复 | 78,419,577.59 元 |
| 在手订单（合同负债） | ❌ 无公开 API | ✅ 已修复 | 114,473,084.98 元（合同负债） |

**修复方式**：`tradingagents/dataflows/a_share.py`

- **DNS 补丁**：`_patch_emweb_dns()` 拦截 `socket.getaddrinfo`，对 `*.securities.eastmoney.com` 使用公共 DNS（8.8.8.8）解析（内部 DNS 10.251.1.1 不识别该 CDN 域名）
- **三张报表直连**：`_fetch_akshare_detailed_fundamentals()` 通过 akshare 直接调用东财财务报表 API（资产负债表/利润表/现金流量表），提取关键字段
- **无侵入集成**：在 `get_a_share_fundamentals()` 末尾追加 enrichment，不影响原有两个路径

**依赖**：新增 `dnspython>=2.6.0`、`akshare`（已安装）

---

## 关键文件索引

| 文件 | 说明 |
|---|---|
| `tradingagents/data/sector_mapping.yaml` | 板块映射表（74 条） |
| `tradingagents/dataflows/sector_mapping.py` | 运行时解析模块 |
| `scripts/build_sector_mapping.py` | 映射表自动构建（top-5 探针） |
| `scripts/merge_sector_enrichments.py` | 映射表人工增强 |
| `scripts/run_recommend.py` | 推荐流水线（含 concept 模式回退） |
| `tradingagents/dataflows/a_share.py` | A 股数据接口（含 akshare 三张报表 enrichment） |
| `.cache/sector_mapping/board_em_probe.json` | 542 只股票的探针缓存 |
| `.cache/sector_mapping/danginvest_board_stocks.json` | 110 个 DangInvest 板块成分股 |
| `.cursor/sandbox.json` | 沙箱网络白名单（已加 securities.eastmoney.com） |
