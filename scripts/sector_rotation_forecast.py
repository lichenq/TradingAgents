#!/usr/bin/env python3
"""
TradingAgents Sector Rotation Forecast & Main Force Probability Inference Tool
Author: TradingAgents Core Team
Date: May 30, 2026

This script performs bottom-up sector capital flow reverse-engineering.
It identifies where the 'main force' (mega-cap institutions) are moving their capital next,
calculating sector rotation probabilities by analyzing the top-3 market cap trendsetters in each sector.
"""

import sys
import os
import json
import time
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Any, Optional

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

BOARDS_SUMMARY_URL = "https://dang-invest.com/api/market/boards/summary"
BOARDS_DETAIL_URL = "https://dang-invest.com/api/market/boards/detail"

# EastMoney API configurations
EM_FUND_FLOW_URL = "https://push2delay.eastmoney.com/api/qt/stock/fflow/daykline/get"
EM_FUND_FLOW_UT = "b2884a393a59ad64002292a3e90d46a5"


def _http_get_json(url: str, params: dict = None, timeout: int = 15) -> Optional[dict]:
    """Helper to perform proxy-clean, stable HTTP requests to market endpoints."""
    # Clean proxy env variables to avoid sandbox interception
    env_backup = {}
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        if key in os.environ:
            env_backup[key] = os.environ[key]
            del os.environ[key]
    os.environ["NO_PROXY"] = "*"

    query_str = ""
    if params:
        query_str = "?" + urllib.parse.urlencode(params)
    full_url = url + query_str

    try:
        req = urllib.request.Request(full_url, headers=HEADERS)
        proxy_support = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(proxy_support)
        with opener.open(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        # Ignore warning for cleaner CLI outputs
        pass
    finally:
        # Restore env
        for k, v in env_backup.items():
            os.environ[k] = v
    return None


def get_top_sectors(limit: int = 15) -> List[dict]:
    """Fetch top sectors from DangInvest summary, sorted by market cap or turnover."""
    # Get standard industry board summaries
    payload = _http_get_json(BOARDS_SUMMARY_URL, {"mode": "industry", "limit": limit, "sort": "market_cap_desc"})
    if payload and payload.get("rc") == 0 or payload and "data" in payload:
        # DangInvest standard wrap is usually direct 'data' or 'data.items'
        data_block = payload.get("data") or {}
        if isinstance(data_block, dict):
            return data_block.get("items") or []
        elif isinstance(data_block, list):
            return data_block
    return []


def get_sector_top_companies(group_key: str, limit: int = 3) -> List[dict]:
    """Fetch the top N largest companies (by market cap) for a given sector."""
    payload = _http_get_json(BOARDS_DETAIL_URL, {
        "mode": "industry",
        "groupKey": group_key,
        "sort": "market_cap_desc",
        "items_limit": limit
    })
    if payload and "data" in payload:
        data_block = payload.get("data") or {}
        if isinstance(data_block, dict):
            return data_block.get("items") or []
    return []


def get_stock_secid(code: str) -> str:
    """Parse stock code (e.g. 688981.SH or 003021.SZ) into EastMoney secid string."""
    clean_code = "".join(ch for ch in code if ch.isdigit())[-6:]
    if len(clean_code) < 6:
        return ""
    # SH is 1, SZ is 0. BJ/NQ is usually 0 or 1, SH shares start with 5, 6, 9
    market_id = "1" if clean_code.startswith(("5", "6", "9")) or ".SH" in code.upper() else "0"
    return f"{market_id}.{clean_code}"


def fetch_stock_fund_flow_days(code: str, days: int = 3) -> List[dict]:
    """Fetch recent N days of main force net flows for a specific stock."""
    secid = get_stock_secid(code)
    if not secid:
        return []

    params = {
        "lmt": str(days),
        "klt": "101", # Daily
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "ut": EM_FUND_FLOW_UT,
        "secid": secid,
        "_": str(int(time.time() * 1000))
    }

    payload = _http_get_json(EM_FUND_FLOW_URL, params)
    if not payload or payload.get("rc") != 0 or not payload.get("data"):
        return []

    klines = payload["data"].get("klines") or []
    result = []
    for kline in klines:
        parts = kline.split(",")
        if len(parts) < 13:
            continue
        # f51: Date, f52: Main force net, f56: Super force net, f55: Big force net, f57: Main force pct, f62: Close, f63: Chg pct
        try:
            result.append({
                "date": parts[0],
                "main_flow_yuan": float(parts[1]),
                "super_flow_yuan": float(parts[5]),
                "big_flow_yuan": float(parts[4]),
                "main_pct": float(parts[6]),
                "close": float(parts[11]),
                "change_pct": float(parts[12])
            })
        except ValueError:
            continue
    return result


def analyze_sector_rotation(sector: dict) -> dict:
    """Analyze sector fund flows and compute probability score for rotation."""
    group_key = sector.get("groupKey") or sector.get("groupLabel") or ""
    if not group_key:
        return {}

    # 1. Fetch top 3 trendsetters
    companies = get_sector_top_companies(group_key, limit=3)
    if not companies:
        return {}

    # 2. Fetch fund flow for each trendsetter (Parallelized)
    aggregated_flows = []
    total_market_cap = 0.0
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fetch_stock_fund_flow_days, c["code"], days=3): c for c in companies}
        for future in as_completed(futures):
            company = futures[future]
            flows = future.result()
            if flows:
                aggregated_flows.append({
                    "company": company,
                    "flows": flows
                })
                total_market_cap += float(company.get("marketCapYuan") or 0.0)

    if not aggregated_flows:
        return {}

    # 3. Aggregate 1-day and 3-day indicators
    # We aggregate weighted by company market cap or simple sum of flows
    latest_date = aggregated_flows[0]["flows"][-1]["date"] if aggregated_flows[0]["flows"] else ""
    
    main_flow_t0_yi = 0.0
    main_flow_3d_yi = 0.0
    weighted_change_pct = 0.0
    weighted_main_pct = 0.0
    weight_total = 0.0
    
    details = []

    for item in aggregated_flows:
        comp = item["company"]
        flows = item["flows"]
        weight = float(comp.get("marketCapYuan") or 1.0)
        weight_total += weight
        
        # Latest day (T0)
        t0_flow = flows[-1]
        main_flow_t0_yi += t0_flow["main_flow_yuan"] / 1e8
        weighted_change_pct += t0_flow["change_pct"] * weight
        weighted_main_pct += t0_flow["main_pct"] * weight
        
        # 3-day sum
        d3_flow_sum = sum(f["main_flow_yuan"] for f in flows) / 1e8
        main_flow_3d_yi += d3_flow_sum
        
        # Check slope (T0 vs T-1 and T-2)
        slope_str = "Stable"
        if len(flows) >= 3:
            f0 = flows[-1]["main_flow_yuan"]
            f1 = flows[-2]["main_flow_yuan"]
            f2 = flows[-3]["main_flow_yuan"]
            if f0 > f1 > f2 and f0 > 0:
                slope_str = "Accelerating Inflow"
            elif f0 < f1 < f2 and f0 < 0:
                slope_str = "Accelerating Outflow"
            elif f0 > 0 and f1 < 0:
                slope_str = "Turning Positive"
            elif f0 < 0 and f1 > 0:
                slope_str = "Turning Negative"

        details.append(
            f"{comp['name']}(T0净额={t0_flow['main_flow_yuan']/1e8:+.2f}亿, 3日累计={d3_flow_sum:+.2f}亿, 趋势={slope_str})"
        )

    sector_change_pct = float(sector.get("changePct") or 0.0)
    sector_turnover_yi = float(sector.get("totalTurnoverYuan") or 0.0) / 1e8

    # 4. Compute Rotation Score & Probability Category
    # Score metrics:
    # - T0 flow volume relative to sector turnover (Net inflow density)
    # - 3-day momentum (continuous buying)
    # - Sector change percentage (divergence check)
    t0_inflow_density = (main_flow_t0_yi / sector_turnover_yi) if sector_turnover_yi > 0 else 0.0
    
    # Classification logic based on Serenity's five-factor criteria:
    category = "NORMAL"
    probability = "Medium"
    confidence_score = 50.0
    action_advice = "Hold & Watch"

    if main_flow_t0_yi > 1.5 and sector_change_pct < -2.0:
        # Case A: Severe Price Drop but Major Main Force Net Inflow -> "Adversarial Accumulation" (Low price, high buying)
        category = "ADV_ACCUMULATION"
        probability = "Very High"
        confidence_score = 90.0
        action_advice = "Strong Buy Candidate (Perfect Pullback Low-Risk Entry)"
    elif main_flow_t0_yi > 1.5 and main_flow_3d_yi > 3.0 and sector_change_pct >= 0:
        # Case B: Momentum Inflow -> "Trend Following"
        category = "MOM_INFLOW"
        probability = "High"
        confidence_score = 80.0
        action_advice = "Overweight (Follow Strong Main Force Inflow)"
    elif main_flow_t0_yi < -3.0 and sector_change_pct > 1.0:
        # Case C: Price Rises but Major Main Force Net Outflow -> "Overheated Distribution" (Divergence/FOMO exit)
        category = "FOMO_DISTRIBUTION"
        probability = "Very Low (Danger)"
        confidence_score = 15.0
        action_advice = "Strong Avoid / Profit Taking (High Trap Risk)"
    elif main_flow_t0_yi < -5.0 and main_flow_3d_yi < -10.0:
        # Case D: Heavy continuous outflow -> "Systemic Liquidation"
        category = "SYSTEMIC_LIQUIDATION"
        probability = "Extremely Low"
        confidence_score = 5.0
        action_advice = "Sell / Avoid (Capital Flight - Do not catch the knife)"
    elif abs(main_flow_t0_yi) < 0.5 and main_flow_3d_yi > 1.0 and abs(sector_change_pct) < 1.5:
        # Case E: Quiet accumulation at bottom
        category = "QUIET_ACCUMULATION"
        probability = "High (Medium-Term)"
        confidence_score = 70.0
        action_advice = "Accumulate (Patience Play - Invisible Institutional Buying)"
    elif main_flow_t0_yi < -1.0 and sector_change_pct < -2.0:
        # Case F: Panicked exit
        category = "PANIC_EXIT"
        probability = "Low"
        confidence_score = 25.0
        action_advice = "Avoid (Wait for Selling Pressure to Dry Up)"

    return {
        "sector_name": group_key,
        "change_pct": sector_change_pct,
        "turnover_yi": sector_turnover_yi,
        "companies": [c["name"] for c in companies],
        "main_flow_t0_yi": main_flow_t0_yi,
        "main_flow_3d_yi": main_flow_3d_yi,
        "t0_inflow_density": t0_inflow_density,
        "category": category,
        "probability": probability,
        "confidence": confidence_score,
        "action_advice": action_advice,
        "details": details,
        "trade_date": latest_date
    }


def generate_rotation_report(results: List[dict]) -> str:
    """Format rotation results into a masterly analytical report."""
    if not results:
        return "### 行业轮动预测报告\n\n*未获取到足够的板块资金流向数据进行研判。*"

    # Sort results by confidence score descending
    sorted_results = sorted(results, key=lambda x: x.get("confidence", 50.0), reverse=True)
    trade_date = results[0]["trade_date"] if results else datetime.now().strftime("%Y-%m-%d")

    lines = [
        f"# 🌍 TradingAgents 板块主力资金「下一步」概率推断报告",
        f"- **分析交易日**: `{trade_date}`",
        f"- **量化数据底盘**: 东方财富 / DangInvest 实时板块大单流向统计 & 前三龙头资金逆向穿透",
        f"- **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        "",
        "## 🎯 主力资金下一步选择：黄金轮动红绿榜",
        "",
        "| 优先级 | 板块名称 | 涨跌幅 | 成交额(亿) | T0主力净额(亿) | 3日主力累计(亿) | 旋转特征分类 | 概率等级 (Next Step Opportunity) | 核心战术行动建议 |",
        "| :---: | :--- | :---: | :---: | :---: | :---: | :--- | :---: | :--- |"
    ]

    for i, r in enumerate(sorted_results):
        chg_sign = "+" if r["change_pct"] >= 0 else ""
        t0_sign = "+" if r["main_flow_t0_yi"] >= 0 else ""
        d3_sign = "+" if r["main_flow_3d_yi"] >= 0 else ""
        
        category_cn = {
            "ADV_ACCUMULATION": "🛑 逆向砸盘吸筹 (黄金坑)",
            "MOM_INFLOW": "🔥 强趋势资金流入 (主攻)",
            "QUIET_ACCUMULATION": "🤫 底部静悄悄建仓",
            "NORMAL": "⚖ 正常资金震荡",
            "FOMO_DISTRIBUTION": "⚠️ 拉高诱多派发 (陷阱)",
            "PANIC_EXIT": "📉 恐慌多杀多离场",
            "SYSTEMIC_LIQUIDATION": "💀 主力大举出逃"
        }.get(r["category"], r["category"])

        lines.append(
            f"| {i+1} | **{r['sector_name']}** | {chg_sign}{r['change_pct']:.2f}% | {r['turnover_yi']:.1f} | {t0_sign}{r['main_flow_t0_yi']:.2f} | {d3_sign}{r['main_flow_3d_yi']:.2f} | {category_cn} | **{r['probability']}** | *{r['action_advice']}* |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 🔍 个股级底层资金穿透细节 (Top 3 Mega-Caps Detail)",
        "通过对各板块市值最大、对资金趋势最有决定性影响的 3 家旗舰龙头个股进行底层主力资金（超大单+大单）追踪，交叉验证板块水分："
    ])

    for r in sorted_results:
        lines.append(f"### ❖ {r['sector_name']} 板块资金流深度穿透")
        lines.append(f"- **板块总揽**: 涨跌幅 `{r['change_pct']:+.2f}%`，总成交 `Yuan {r['turnover_yi']:.2f} 亿`")
        lines.append(f"- **领涨/权重旗舰个股主力行为追踪**:")
        for det in r["details"]:
            lines.append(f"  - {det}")
        lines.append("")

    lines.extend([
        "## 💡 终极复用洞察：如何在 TradingAgents 中落地使用？",
        "1. **大跌抄底验证**：周五半导体大跌，不要第一天进场。一旦本脚本显示半导体板块在价格继续阴跌或平盘时，`T0主力净额` 出现大额流入，特征转为 **[🛑 逆向砸盘吸筹]**，这才是 L2 级见底信号，即可触发单股建仓评估。",
        "2. **自动热点对齐避雷**：当 `recommend --board auto` 时，自动对比本报告，若热点前五中有板块分类被定性为 **[⚠️ 拉高诱多派发]**，自动予以过滤或降权，避免在科技泡沫见顶日 All-in。",
        "3. **槓铃对冲交易**：当高位科技板块呈现 **[💀 主力大举出逃]**，而高分红电力、低估消费出现 **[🔥 强趋势资金流入]** 或 **[🤫 底部静悄悄建仓]** 时，交易员（Trader）应当天减少科技配置，并自动向防御板块划拨 15%-25% 的对冲保证金。"
    ])

    return "\n".join(lines)


def _build_forecast_json(results: List[dict]) -> dict:
    """Build sector rotation forecast dict from analysis results."""
    update_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    forecast = {}
    for r in results:
        forecast[r["sector_name"]] = {
            "category": r["category"],
            "probability": r["probability"],
            "confidence": r["confidence"],
            "action_advice": r["action_advice"],
            "main_flow_t0_yi": r["main_flow_t0_yi"],
            "main_flow_3d_yi": r["main_flow_3d_yi"],
            "t0_inflow_density": r["t0_inflow_density"],
            "update_time": update_time,
        }
    return forecast


def _write_json_atomic(path: str, data: dict) -> None:
    """Write JSON atomically to avoid partial/corrupted files."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def main():
    print("🤖 TradingAgents 正在执行行业板块主力资金穿透与概率推断...", file=sys.stderr)
    
    # 1. Fetch top 12 sectors
    sectors = get_top_sectors(limit=15)
    if not sectors:
        print("错误：无法获取行业板块 summary 快照。请检查网络或数据源接口。", file=sys.stderr)
        sys.exit(1)

    print(f"📊 成功获取 {len(sectors)} 个权重行业板块。正在并行逆向穿透个股资金流...", file=sys.stderr)
    
    # 2. Parallelly analyze each sector
    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(analyze_sector_rotation, sec): sec for sec in sectors}
        for future in as_completed(futures):
            sec = futures[future]
            try:
                res = future.result()
                if res:
                    results.append(res)
                    print(f"  ✓ 已完成板块【{res['sector_name']}】主力特征研判: {res['category']}", file=sys.stderr)
            except Exception as e:
                print(f"  ✗ 分析板块【{sec.get('groupLabel', '未知')}】失败: {e}", file=sys.stderr)

    if not results:
        print("错误：未生成任何板块主力研判结果。", file=sys.stderr)
        sys.exit(1)

    # 3. Output beautiful Markdown Report to stdout
    report = generate_rotation_report(results)
    print(report)

    # 4. Write forecast JSON once (avoid concurrent read-modify-write corruption)
    json_path = "results/recommendations/sector_rotation_forecast.json"
    forecast_data = _build_forecast_json(results)
    try:
        _write_json_atomic(json_path, forecast_data)
        print(f"  ✓ 板块轮动预测 JSON 已写入 {json_path}", file=sys.stderr)
    except Exception as e:
        print(f"  ✗ 写入板块轮动预测 JSON 失败: {e}", file=sys.stderr)

    # 5. Save to SQLite database to serve as the primary source of truth
    try:
        results_dir = os.environ.get("TRADINGAGENTS_RESULTS_DIR", "results")
        trade_date = results[0]["trade_date"] if results else datetime.now().strftime("%Y-%m-%d")
        forecast_json_str = json.dumps(forecast_data, ensure_ascii=False, indent=2)

        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
        from tradingagents.graph.storage import save_sector_rotation
        save_sector_rotation(results_dir, trade_date, report, forecast_json_str)
        print(f"  ✓ 行业主力资金推断报告与数据已成功同步至数据库。交易日: {trade_date}", file=sys.stderr)
    except Exception as e:
        print(f"  ✗ 同步行业主力资金推断报告至数据库失败: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
