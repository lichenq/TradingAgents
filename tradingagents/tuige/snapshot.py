"""Market snapshot helpers for Tuige regime / rebalance detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Index code suffixes in all-quote payloads (6-digit or prefixed)
_INDEX_CODES = {
    "sh000001": "shanghai",
    "000001": "shanghai",
    "sz399001": "shenzhen",
    "399001": "shenzhen",
    "sz399006": "chinext",
    "399006": "chinext",
    "sh000688": "star50",
    "000688": "star50",
}


@dataclass
class MarketSnapshot:
    trade_date: str = ""
    total_amount_yuan: float = 0.0
    advancers: int = 0
    decliners: int = 0
    unchanged: int = 0
    index_changes: Dict[str, float] = field(default_factory=dict)
    industry_flows: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def breadth_ratio(self) -> float:
        total = self.advancers + self.decliners
        if total <= 0:
            return 0.5
        return self.advancers / total


def _normalize_code(raw: str) -> str:
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if len(digits) >= 6:
        return digits[-6:]
    return digits


def _code_key(raw: str) -> str:
    s = (raw or "").strip().lower()
    digits = _normalize_code(s)
    if s.startswith("sh") or s.startswith("sz"):
        return s.replace(".", "")[:8]
    return digits


def snapshot_from_quotes(
    trade_date: str,
    quotes: List[Dict[str, Any]],
    *,
    industry_flows: Optional[List[Dict[str, Any]]] = None,
) -> MarketSnapshot:
    snap = MarketSnapshot(trade_date=trade_date, industry_flows=industry_flows or [])
    index_changes: Dict[str, float] = {}

    for q in quotes or []:
        code_raw = q.get("code") or q.get("symbol") or ""
        key = _code_key(str(code_raw))
        change = q.get("change_pct")
        if change is None:
            change = q.get("涨跌幅(%)")
        try:
            change_f = float(change)
        except (TypeError, ValueError):
            change_f = 0.0

        mapped = _INDEX_CODES.get(key) or _INDEX_CODES.get(_normalize_code(key))
        if mapped and mapped not in index_changes:
            index_changes[mapped] = change_f
            continue

        if change_f > 0:
            snap.advancers += 1
        elif change_f < 0:
            snap.decliners += 1
        else:
            snap.unchanged += 1

        amount = q.get("amount") or q.get("成交额") or 0
        try:
            snap.total_amount_yuan += float(amount)
        except (TypeError, ValueError):
            pass

    snap.index_changes = index_changes
    return snap


def merge_index_payload(snap: MarketSnapshot, index_payload: Dict[str, Any]) -> MarketSnapshot:
    """Merge ``fetch_realtime.py --index`` JSON into snapshot index_changes."""
    items = index_payload.get("data") or index_payload.get("items") or []
    if isinstance(index_payload.get("data"), dict):
        items = index_payload["data"].get("items") or items

    for item in items:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or item.get("名称") or "").strip()
        code = _code_key(str(item.get("code") or item.get("代码") or ""))
        change = item.get("change_pct")
        if change is None:
            change = item.get("涨跌幅(%)")
        try:
            change_f = float(change)
        except (TypeError, ValueError):
            continue

        if "上证" in name or code in ("000001", "sh000001"):
            snap.index_changes["shanghai"] = change_f
        elif "深证成指" in name or code in ("399001", "sz399001"):
            snap.index_changes["shenzhen"] = change_f
        elif "创业板" in name or code in ("399006", "sz399006"):
            snap.index_changes["chinext"] = change_f
        elif "科创" in name or code in ("000688", "sh000688"):
            snap.index_changes["star50"] = change_f

    return snap
