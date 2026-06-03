# tradingagents/dataflows/fund_flow.py
from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from typing import Any, Dict, Optional, Tuple

from tradingagents.market import normalize_a_share_code
from tradingagents.dataflows.config import get_config

logger = logging.getLogger(__name__)


def fetch_raw_fund_flow(ticker: str) -> Optional[Dict[str, Any]]:
    """从 push2delay.eastmoney.com 获取最新资金流向（主力/大单/中单/小单）"""
    code6 = normalize_a_share_code(ticker)
    market_id = 1 if code6.startswith(("5", "6", "9")) else 0
    secid = f"{market_id}.{code6}"

    # 清洗代理以防止沙箱干扰
    env = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"

    # 使用 push2delay 作为主源，因为它最稳定且不封锁 IP
    url = (
        f"https://push2delay.eastmoney.com/api/qt/stock/fflow/daykline/get"
        f"?lmt=5&klt=101"
        f"&fields1=f1,f2,f3,f7"
        f"&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65"
        f"&ut=b2884a393a59ad64002292a3e90d46a5"
        f"&secid={secid}"
        f"&_={int(time.time() * 1000)}"
    )

    try:
        req = urllib.request.Request(url)
        proxy_support = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(proxy_support)
        with opener.open(req, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if payload.get("rc") == 0 and payload.get("data"):
                return payload["data"]
    except Exception as e:
        logger.warning(f"Failed to fetch raw fund flow from push2delay for {code6}: {e}")
    
    return None


def format_fund_flow_markdown(data: Dict[str, Any]) -> str:
    """将个股资金流数据解析并格式化为 markdown"""
    klines = data.get("klines") or []
    if not klines:
        return ""

    # 取最后一条，即最新交易日的数据
    latest_kline = klines[-1]
    parts = latest_kline.split(",")
    if len(parts) < 13:
        return ""

    # 解析字段 (参考 EastMoney / akshare 字段定义)
    # f51:日期, f52:主力净额, f53:小单净额, f54:中单净额, f55:大单净额, f56:超大单净额, 
    # f57:主力占比, f58:小单占比, f59:中单占比, f60:大单占比, f61:超大单占比, f62:收盘价, f63:涨跌幅
    date = parts[0]
    
    # 转化为万元单位 (东财原始单位是元)
    main_flow = float(parts[1]) / 10000.0
    small_flow = float(parts[2]) / 10000.0
    mid_flow = float(parts[3]) / 10000.0
    big_flow = float(parts[4]) / 10000.0
    super_flow = float(parts[5]) / 10000.0

    main_pct = float(parts[6])
    small_pct = float(parts[7])
    mid_pct = float(parts[8])
    big_pct = float(parts[9])
    super_pct = float(parts[10])

    close_price = float(parts[11])
    chg_pct = float(parts[12])

    # 格式化正负号显示
    def fmt_val(val: float, suffix: str = "万元") -> str:
        sign = "+" if val > 0 else ""
        return f"{sign}{val:,.2f} {suffix}"

    def fmt_pct(val: float) -> str:
        sign = "+" if val > 0 else ""
        return f"{sign}{val:.2f}%"

    lines = [
        "### 资金流向监测（最新交易日）",
        "",
        f"- **数据日期**: {date}",
        f"- **收盘价**: {close_price:.2f} 元（涨跌幅: {fmt_pct(chg_pct)}）",
        f"- **主力资金（超大单+大单）净流入**: **{fmt_val(main_flow)}**（占比: **{fmt_pct(main_pct)}**）",
        f"  - **超大单净流入**: {fmt_val(super_flow)}（占比: {fmt_pct(super_pct)}）",
        f"  - **大单净流入**: {fmt_val(big_flow)}（占比: {fmt_pct(big_pct)}）",
        f"- **中单（中散户）净流入**: {fmt_val(mid_flow)}（占比: {fmt_pct(mid_pct)}）",
        f"- **小单（小散户）净流入**: {fmt_val(small_flow)}（占比: {fmt_pct(small_pct)}）",
        "",
        "> **【主力与散户博弈偏好纪律 — 必须参考】**",
        "> 1. **大额主力净流入（占比 $\\ge 3.0\\%$）**：代表主力、机构大资金正在猛烈扫货吸筹，属于强烈的短期做多共鸣技术信号。在同等条件下，支持多空研究员及PM给该标的评级上调一个档次（如 Hold 升 Overweight，或 Overweight 升 Buy）。",
        "> 2. **大额主力净流出（占比 $\\le -3.0\\%$）**：代表主力大资金不计成本抛盘离场，即便由于散户抄底导致股价收红，也代表极高的拉高派发诱多风险，属于极强警示信号。所有智能体在制定交易计划时须高度警惕，评级应下调或严格限制在 Hold 以下。",
        "> 3. **散户抄底与背离（中小单净流入 vs 主力净流出）**：经典的资金面背离，暗示该上涨为虚胖筹码。必须严格控制仓位，防范左侧接飞刀或陷入价值陷阱。",
    ]

    return "\n".join(lines)


def fetch_and_format_cn_fund_flow(ticker: str) -> str:
    """获取并格式化资金流 markdown 文本"""
    config = get_config()
    market_profile = (config.get("market_profile") or "us").strip().lower()
    if market_profile not in ("cn", "a", "a_share", "china"):
        return ""

    raw_data = fetch_raw_fund_flow(ticker)
    if raw_data:
        md = format_fund_flow_markdown(raw_data)
        if md:
            return md
    return "### 资金流向监测\n\n*暂无最新主力资金流向数据。*"
