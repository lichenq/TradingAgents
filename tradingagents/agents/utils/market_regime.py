# tradingagents/agents/utils/market_regime.py
from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any, Dict, List

from tradingagents.market import normalize_a_share_code
from tradingagents.dataflows.config import get_config

logger = logging.getLogger(__name__)

# 在线运行期内存缓存，避免单次分析中重复调用外网接口
_BOARDS_CACHE: List[Dict[str, Any]] = []
_SECTOR_INFO_CACHE: Dict[str, str] = {}


def fetch_boards_summary_raw() -> List[Dict[str, Any]]:
    """获取当天全市场行业板块的成交额与涨跌幅快照"""
    global _BOARDS_CACHE
    if _BOARDS_CACHE:
        return _BOARDS_CACHE

    # 清洗代理以防止沙箱干扰外网请求
    env = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"

    url = "https://dang-invest.com/api/market/boards/summary?mode=industry&limit=120"
    try:
        req = urllib.request.Request(url)
        # 显式空代理处理器以跳过任何本地环境代理配置
        proxy_support = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(proxy_support)
        with opener.open(req, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
            _BOARDS_CACHE = payload.get("data", {}).get("items", [])
            return _BOARDS_CACHE
    except Exception as e:
        logger.warning(f"Failed to fetch boards summary for regime detection: {e}")
        return []


def get_ticker_sector_name(ticker: str) -> str:
    """获取个股对应的行业分类"""
    global _SECTOR_INFO_CACHE
    code6 = normalize_a_share_code(ticker)
    if code6 in _SECTOR_INFO_CACHE:
        return _SECTOR_INFO_CACHE[code6]

    from tradingagents.dataflows.sector_queries import fetch_sector_payload
    try:
        payload = fetch_sector_payload(ticker)
        if payload and isinstance(payload, dict):
            ind = (payload.get("industry") or "").strip()
            if ind:
                _SECTOR_INFO_CACHE[code6] = ind
                return ind
    except Exception as e:
        logger.warning(f"Failed to fetch sector payload for {ticker}: {e}")
    return ""


def detect_market_regime(ticker: str, trade_date: str) -> str:
    """与时俱进：通过量化资金流占比与动量斜率，动态识别当前题材环境"""
    config = get_config()
    
    # 支持用户通过配置强制覆盖
    manual_override = (config.get("position_context_regime") or "").strip().lower()
    if manual_override in ("aggressive", "high_heat"):
        return "HIGH_HEAT_REGIME"
    if manual_override in ("conservative", "defensive"):
        return "DEFENSIVE_REGIME"

    market_profile = (config.get("market_profile") or "us").strip().lower()
    if market_profile not in ("cn", "a", "a_share", "china"):
        return "NORMAL_REGIME"

    raw_sector = get_ticker_sector_name(ticker)
    if not raw_sector:
        return "NORMAL_REGIME"

    # 行业/板块标准别名转换
    sector_mapping = {
        "券商信托": "证券",
        "通讯行业": "通信设备",
        "通信行业": "通信设备",
        "消费电子": "元器件",
        "电机": "电气设备",
    }
    sector_name = sector_mapping.get(raw_sector, raw_sector)

    # 动态获取行业轮动预测
    forecast_data = {}
    
    # 1. 优先从 SQLite 数据库获取 (主数据源)
    try:
        from tradingagents.graph.storage import query_sector_rotation, parse_json_safe
        results_dir = config.get("results_dir") or "results"
        db_res = query_sector_rotation(results_dir, trade_date)
        if db_res and db_res.get("forecast_json"):
            forecast_data = parse_json_safe(db_res["forecast_json"]) or {}
            logger.info(f"Regime Detector: Successfully retrieved sector rotation forecast from database for trade_date {trade_date}")
    except Exception as e:
        logger.warning(f"Regime Detector: Failed to query sector rotation from SQLite: {e}")

    # 2. 备用：从本地文件加载
    if not forecast_data:
        forecast_path = "results/recommendations/sector_rotation_forecast.json"
        if os.path.exists(forecast_path):
            try:
                from tradingagents.graph.storage import parse_json_safe
                with open(forecast_path, "r", encoding="utf-8") as f:
                    forecast_data = parse_json_safe(f.read()) or {}
                if forecast_data:
                    logger.info(f"Regime Detector: Fallback: Loaded sector rotation forecast from local file {forecast_path}")
            except Exception:
                pass

    if forecast_data:
        try:
            # 在预测结果中查找对应的板块
            target_fc = None
            for key, val in forecast_data.items():
                if key == sector_name or key in sector_name or sector_name in key:
                    target_fc = val
                    break
            
            if target_fc:
                category = target_fc.get("category")
                # 如果被定性为大流出或诱多，强制返回冷门防御环境，保护资金
                if category in ("SYSTEMIC_LIQUIDATION", "PANIC_EXIT", "FOMO_DISTRIBUTION"):
                    logger.info(f"Regime Detector: {ticker} ({sector_name}) overridden to DEFENSIVE_REGIME via Serenity Sector Rotation Forecast (Category: {category})")
                    return "DEFENSIVE_REGIME"
                # 如果属于主力砸盘吸筹或强趋势流入，激活高热度环境以容忍合理溢价
                elif category in ("ADV_ACCUMULATION", "MOM_INFLOW"):
                    logger.info(f"Regime Detector: {ticker} ({sector_name}) overridden to HIGH_HEAT_REGIME via Serenity Sector Rotation Forecast (Category: {category})")
                    return "HIGH_HEAT_REGIME"
        except Exception as e:
            pass

    boards = fetch_boards_summary_raw()
    if not boards:
        return "NORMAL_REGIME"

    total_turnover = 0.0
    target_board = None
    
    # 首先尝试精确匹配
    for b in boards:
        turn = float(b.get("totalTurnoverYuan") or 0.0)
        total_turnover += turn
        if b.get("groupLabel") == sector_name:
            target_board = b

    # 精确匹配不成功时，尝试子串匹配 fallback
    if not target_board:
        for b in boards:
            label = b.get("groupLabel")
            if label and (label in sector_name or sector_name in label):
                target_board = b
                sector_name = label # 对齐行业名称，用于后面的领涨动量判断
                break

    if not target_board:
        return "NORMAL_REGIME"

    sector_turnover = float(target_board.get("totalTurnoverYuan") or 0.0)
    sector_chg = float(target_board.get("changePct") or 0.0)
    
    # 核心量化指标：成交额占比（Turnover Share）
    turnover_share = sector_turnover / total_turnover if total_turnover > 0 else 0.0

    # 核心量化指标：行业日涨幅前 5 名
    sorted_by_chg = sorted([b for b in boards if b.get("changePct") is not None], 
                           key=lambda x: float(x["changePct"]), reverse=True)
    top_5_sectors = {b["groupLabel"] for b in sorted_by_chg[:5]}

    # 自适应规则：属于核心资金吸金池（占比 >= 4.0%）或者属于当日领涨动量题材
    is_liquidity_core = (turnover_share >= 0.04)
    is_momentum_leader = (sector_name in top_5_sectors or sector_chg >= 2.0)

    if is_liquidity_core or is_momentum_leader:
        logger.info(f"Regime Detector: {ticker} ({sector_name}) identified as HIGH_HEAT_REGIME (Share: {turnover_share:.2%}, Chg: {sector_chg:+.2f}%)")
        return "HIGH_HEAT_REGIME"
    
    logger.info(f"Regime Detector: {ticker} ({sector_name}) identified as DEFENSIVE_REGIME (Share: {turnover_share:.2%}, Chg: {sector_chg:+.2f}%)")
    return "DEFENSIVE_REGIME"


def get_regime_prompt_instructions(regime: str) -> str:
    """输出注入到智能体提示词中的偏好与风控纪律约束"""
    if regime == "HIGH_HEAT_REGIME":
        return """
=========================================
【当前市场环境：高热度/强资金流题材环境】
1. 【偏好倾向】该标的所属行业为当前市场核心资金主战场，流动性充沛，具有极强赚钱效应。
2. 【进取型决策弹性】在分析评估时，允许并鼓励多空研究员及投资组合经理（PM）对高成长、强趋势题材的估值溢价（如 30x - 60x TTM PE）给予一定容忍度，不要刻板地因为估值百分位偏高而一刀切。重点考察 AI/科技产业链景气度、订单转化潜力和资金承接强度。如果技术面处于缩量回踩良性阶段，支持给出 Buy 或 Overweight 评级。
3. 【防爆安全底线 — 必须坚守】
   - 估值熔断：若 TTM PE 超过 80x 且最近季度净利润同比增速低于 50%，一律视为过度投机泡沫，必须一票否决降至 Underweight 或 Sell。
   - 严重超买熔断：若股价偏离 30 日均线超过 25%，视为严重超买，禁止在当前价位建仓。
   - 强制保护：交易计划中必须强制写入 8% - 10% 的硬性保护止损线，禁止无防护裸奔。
=========================================
"""
    elif regime == "DEFENSIVE_REGIME":
        return """
=========================================
【当前市场环境：防御型/冷门题材环境】
1. 【偏好倾向】该标的所属板块当前流动性匮乏、缺乏共识。
2. 【保守型决策弹性】系统在评估时必须执行最严苛的“绝对安全边际”审核，死守 TTM PE < 15x、PB 接近 1.0 倍及持续正向经营现金流等防守硬指标。
3. 【防爆安全底线 — 必须坚守】
   - 宁缺毋滥：在没有超级订单、大股东增持或业绩绝对反转证据前，评级上限严格压死在 Hold（不开仓观望），坚决拒绝在非主流板块左侧接飞刀、买入价值陷阱。
=========================================
"""
    return ""
