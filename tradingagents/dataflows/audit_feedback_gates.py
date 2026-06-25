"""Hard feedback gates from audit KPIs (P1): strategy disable + sector high-PE block."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from tradingagents.agents.utils.rating import RATINGS_5_TIER
from tradingagents.dataflows.sector_mapping import resolve as resolve_sector


def _fetch_enriched_audits(*args, **kwargs):
    from tradingagents.dataflows.audit_report import fetch_enriched_audits

    return fetch_enriched_audits(*args, **kwargs)

BEARISH_RATINGS = {r for r in RATINGS_5_TIER if r in ("Hold", "Underweight", "Sell")}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def audit_gate_config() -> Dict[str, Any]:
    return {
        "lookback_days": _env_int("AUDIT_GATE_LOOKBACK_DAYS", 30),
        "min_samples": _env_int("AUDIT_GATE_MIN_SAMPLES", 3),
        "min_win_rate": _env_float("AUDIT_GATE_MIN_WIN_RATE", 0.4),
        "horizon": _env_int("AUDIT_GATE_HORIZON", 3),
        "high_pe": _env_float("AUDIT_GATE_HIGH_PE", 60.0),
        "sector_min_losses": _env_int("AUDIT_GATE_SECTOR_MIN_LOSSES", 2),
    }


def _strategy_returns(
    enriched: List[Dict[str, Any]],
    strategy: str,
    horizon: int,
) -> List[float]:
    rows = [
        r for r in enriched
        if r.get("strategy") == strategy
        and int(r.get("days_elapsed") or 0) == horizon
        and r.get("raw_return") is not None
    ]
    rows.sort(key=lambda r: str(r.get("recommendation_date") or ""))
    return [float(r["raw_return"]) for r in rows]


def evaluate_strategy_audit_gate(
    results_dir: str | Path,
    strategy: str,
    *,
    as_of: Optional[date] = None,
) -> Dict[str, Any]:
    """Return whether strategy is allowed based on recent audit win rate."""
    cfg = audit_gate_config()
    enriched = _fetch_enriched_audits(
        results_dir,
        lookback_days=cfg["lookback_days"],
        as_of=as_of,
    )
    returns = _strategy_returns(enriched, strategy, cfg["horizon"])
    stats = {
        "count": len(returns),
        "win_rate": None,
        "avg_return": None,
        "horizon": cfg["horizon"],
        "lookback_days": cfg["lookback_days"],
    }
    if not returns:
        return {
            "allowed": True,
            "reason": "insufficient audit samples",
            "stats": stats,
        }

    wins = sum(1 for x in returns if x > 0)
    stats["win_rate"] = wins / len(returns)
    stats["avg_return"] = sum(returns) / len(returns)

    if len(returns) < cfg["min_samples"]:
        return {
            "allowed": True,
            "reason": f"samples {len(returns)} < min {cfg['min_samples']}",
            "stats": stats,
        }

    oos_block = False
    oos_note = ""
    if len(returns) >= cfg["min_samples"] * 2:
        mid = len(returns) // 2
        train = returns[:mid]
        validate = returns[mid:]
        train_wr = sum(1 for x in train if x > 0) / len(train)
        val_wr = sum(1 for x in validate if x > 0) / len(validate)
        stats["oos_train_win_rate"] = train_wr
        stats["oos_validate_win_rate"] = val_wr
        stats["oos_train_n"] = len(train)
        stats["oos_validate_n"] = len(validate)
        if val_wr < cfg["min_win_rate"] and train_wr < cfg["min_win_rate"]:
            oos_block = True
            oos_note = (
                f"OOS train={train_wr:.0%} validate={val_wr:.0%} "
                f"both < {cfg['min_win_rate']:.0%}"
            )

    if stats["win_rate"] < cfg["min_win_rate"] or oos_block:
        wr = stats["win_rate"]
        reason = (
            f"strategy {strategy} {cfg['horizon']}d audit win_rate {wr:.0%} "
            f"< {cfg['min_win_rate']:.0%} (n={len(returns)})"
        )
        if oos_block:
            reason = oos_note
        return {
            "allowed": False,
            "reason": reason,
            "stats": stats,
        }

    return {"allowed": True, "reason": "ok", "stats": stats}


def _canonical_industry_for_ticker(ticker: str) -> str:
    from tradingagents.dataflows.sector_queries import fetch_sector_payload

    payload = fetch_sector_payload(ticker)
    if not payload:
        return ""
    industry = (payload.get("industry") or "").strip()
    if not industry:
        return ""
    return resolve_sector(industry)


def build_cautious_sectors(
    results_dir: str | Path,
    *,
    as_of: Optional[date] = None,
) -> Dict[str, Dict[str, Any]]:
    """Sectors with >= N losing audits and at least one bearish rating that was correct."""
    cfg = audit_gate_config()
    enriched = _fetch_enriched_audits(
        results_dir,
        lookback_days=cfg["lookback_days"],
        as_of=as_of,
    )
    industry_cache: Dict[str, str] = {}
    sector_losses: Dict[str, List[Dict[str, Any]]] = {}

    for row in enriched:
        ret = row.get("raw_return")
        if ret is None or float(ret) >= 0:
            continue
        ticker = str(row.get("ticker") or "")
        code6 = "".join(ch for ch in ticker if ch.isdigit())[-6:]
        if code6 not in industry_cache:
            industry_cache[code6] = _canonical_industry_for_ticker(ticker or code6)
        sector = industry_cache[code6]
        if not sector:
            continue
        sector_losses.setdefault(sector, []).append(row)

    cautious: Dict[str, Dict[str, Any]] = {}
    for sector, rows in sector_losses.items():
        if len(rows) < cfg["sector_min_losses"]:
            continue
        bearish_ok = any(
            str(r.get("rating") or "") in BEARISH_RATINGS for r in rows
        )
        if not bearish_ok:
            continue
        cautious[sector] = {
            "loss_count": len(rows),
            "tickers": [_ticker_code6(r.get("ticker")) for r in rows[:5]],
        }
    return cautious


def _ticker_code6(ticker: str) -> str:
    return "".join(ch for ch in str(ticker or "") if ch.isdigit())[-6:]


def evaluate_sector_high_pe_gate(
    code: str,
    trade_date: str,
    cautious_sectors: Dict[str, Dict[str, Any]],
    config: Dict[str, Any],
) -> Tuple[bool, str]:
    """Return (should_prune, reason) when sector is cautious and PE is high."""
    if not cautious_sectors:
        return False, ""

    sector = _canonical_industry_for_ticker(code)
    if not sector or sector not in cautious_sectors:
        return False, ""

    cfg = audit_gate_config()
    from tradingagents.dataflows.cn_valuation import fetch_cn_valuation_payload

    code6 = _ticker_code6(code)
    ok, payload, _ = fetch_cn_valuation_payload(code6, trade_date, config)
    if not ok or not isinstance(payload, dict):
        return False, ""

    pe = payload.get("pe_ttm")
    if pe is None:
        return False, ""
    try:
        pe_f = float(pe)
    except (TypeError, ValueError):
        return False, ""

    if pe_f <= 0 or pe_f <= cfg["high_pe"]:
        return False, ""

    meta = cautious_sectors[sector]
    return True, (
        f"复盘门禁: 板块「{sector}」近{cfg['lookback_days']}日亏损复盘"
        f"{meta['loss_count']}次(含Hold/Underweight正确看跌)，"
        f"PE TTM {pe_f:.1f}x > {cfg['high_pe']:.0f}x，禁止追高"
    )


def summarize_audit_gates(
    results_dir: str | Path,
    strategy: str,
    *,
    as_of: Optional[date] = None,
) -> Dict[str, Any]:
    """Combined gate summary for logging / audit report."""
    strategy_gate = evaluate_strategy_audit_gate(results_dir, strategy, as_of=as_of)
    cautious = build_cautious_sectors(results_dir, as_of=as_of)
    return {
        "strategy_gate": strategy_gate,
        "cautious_sectors": cautious,
        "config": audit_gate_config(),
    }
