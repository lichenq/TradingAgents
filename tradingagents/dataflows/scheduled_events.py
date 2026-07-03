"""Normalize forward-looking scheduled events for CN analyze pipeline."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from tradingagents.dataflows.trade_date import cn_trading_days_until

_EVENT_LABELS = {
    "restricted_release": "限售解禁",
    "earnings_disclosure": "预约披露",
    "ex_dividend": "除权除息",
}


def _severity(event: Dict[str, Any], trading_days: int) -> str:
    etype = str(event.get("type") or "")
    pct = event.get("pct_of_float")
    try:
        pct_f = float(pct) if pct is not None else None
    except (TypeError, ValueError):
        pct_f = None
    mv = event.get("market_value_yi")
    try:
        mv_f = float(mv) if mv is not None else None
    except (TypeError, ValueError):
        mv_f = None

    if etype == "restricted_release":
        if trading_days <= 14 and (
            (pct_f is not None and pct_f >= 3.0) or (pct_f is None and mv_f is not None and mv_f >= 50.0)
        ):
            return "high"
        if trading_days <= 30 and (
            (pct_f is not None and pct_f >= 5.0) or (pct_f is None and mv_f is not None and mv_f >= 80.0)
        ):
            return "medium"
        return "low"

    if etype in ("earnings_disclosure", "ex_dividend"):
        if trading_days <= 7:
            return "high"
        if trading_days <= 14:
            return "medium"
        return "low"

    return "low"


def _format_detail(event: Dict[str, Any]) -> str:
    etype = str(event.get("type") or "")
    if etype == "restricted_release":
        parts = []
        shares = event.get("shares_wan")
        if shares is not None:
            parts.append(f"{float(shares):.2f}万股")
        pct = event.get("pct_of_float")
        if pct is not None:
            parts.append(f"占流通约{float(pct):.2f}%")
        mv = event.get("market_value_yi")
        if mv is not None:
            parts.append(f"市值约{float(mv):.1f}亿")
        return "，".join(parts) if parts else "限售股解禁"

    if etype == "earnings_disclosure":
        period = event.get("report_period") or ""
        first = event.get("first_schedule") or ""
        return f"{period} 预约披露" + (f"（首次预约 {first}）" if first else "")

    if etype == "ex_dividend":
        cash = event.get("cash_dividend")
        transfer = event.get("transfer_ratio")
        parts = []
        if cash is not None:
            parts.append(f"现金分红比例 {cash}")
        if transfer is not None:
            parts.append(f"送转 {transfer}")
        progress = event.get("progress") or ""
        if progress:
            parts.append(progress)
        return "，".join(str(p) for p in parts if p) or "除权除息"

    return etype or "排期事件"


def build_scheduled_alerts(
    payload: Optional[Dict[str, Any]],
    trade_date: str,
) -> List[Dict[str, Any]]:
    """Turn fetch_stock_events scheduled_events.upcoming into alert dicts."""
    if not payload:
        return []
    block = payload.get("scheduled_events") or {}
    rows = block.get("upcoming") or []
    if not isinstance(rows, list):
        return []

    alerts: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        event_date = str(row.get("event_date") or "")[:10]
        if not event_date:
            continue
        trading_days = cn_trading_days_until(trade_date, event_date)
        if trading_days <= 0:
            continue
        etype = str(row.get("type") or "unknown")
        label = _EVENT_LABELS.get(etype, etype)
        severity = _severity(row, trading_days)
        alerts.append(
            {
                "type": etype,
                "label": label,
                "event_date": event_date,
                "trading_days_until": trading_days,
                "severity": severity,
                "detail": _format_detail(row),
                "source": row.get("source"),
                "raw": row,
            }
        )

    rank = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda a: (rank.get(a.get("severity", "low"), 9), a.get("event_date", "")))
    return alerts


def format_scheduled_events_block(alerts: List[Dict[str, Any]], *, horizon_days: int = 60) -> str:
    if not alerts:
        return ""
    lines = [f"### 排期事件 · 未来 {horizon_days} 日 ({len(alerts)} 条)"]
    for a in alerts[:8]:
        lines.append(
            f"- [{a.get('severity', 'low')}] {a.get('event_date')} {a.get('label')} "
            f"| 距今{a.get('trading_days_until')}个交易日 | {a.get('detail', '')}"
        )
    return "\n".join(lines)


def format_scheduled_verified_block(alerts: List[Dict[str, Any]]) -> str:
    if not alerts:
        return ""
    lines = ["【排期事件硬数据】"]
    for a in alerts[:6]:
        lines.append(
            f"- {a.get('event_date')}：{a.get('label')}（{a.get('detail', '')}），"
            f"距分析日 {a.get('trading_days_until')} 个交易日，严重度 {a.get('severity')}"
        )
    return "\n".join(lines)


def enrich_verified_with_scheduled_events(verified_md: str, alerts: List[Dict[str, Any]]) -> str:
    block = format_scheduled_verified_block(alerts)
    if not block:
        return verified_md
    base = (verified_md or "").strip()
    if "【排期事件硬数据】" in base:
        return base
    return f"{base}\n\n{block}\n" if base else f"{block}\n"


def has_high_restricted_release(alerts: List[Dict[str, Any]]) -> bool:
    return any(
        a.get("type") == "restricted_release" and a.get("severity") == "high"
        for a in alerts
    )
