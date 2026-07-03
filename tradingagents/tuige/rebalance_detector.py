"""Institutional rebalance window detection (Tuige institutional-rebalance.md)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from tradingagents.tuige.calendar import in_rebalance_calendar_window
from tradingagents.tuige.snapshot import MarketSnapshot

# ~3 trillion yuan all-market turnover (approximate "天量" threshold)
_VOLUME_SPIKE_YUAN = 3.0e12
# Sector main-force net flow threshold (100 million yuan) for "significant" move
_SECTOR_FLOW_YUAN = 5.0e9
_BREADTH_STRONG = 3500


@dataclass
class RebalanceAssessment:
    window: str  # yes | watch | no
    signal_hits: List[str] = field(default_factory=list)
    note: str = ""


def _index_val(snap: MarketSnapshot, key: str, default: float = 0.0) -> float:
    return float(snap.index_changes.get(key, default))


def detect_rebalance_window(snap: MarketSnapshot) -> RebalanceAssessment:
    hits: List[str] = []

    if snap.total_amount_yuan >= _VOLUME_SPIKE_YUAN:
        hits.append("volume_spike")

    sh = _index_val(snap, "shanghai")
    chinext = _index_val(snap, "chinext")
    star50 = _index_val(snap, "star50")
    if snap.advancers >= _BREADTH_STRONG and (chinext < -0.3 or star50 < -0.3) and sh >= -0.2:
        hits.append("index_divergence")

    if _sector_flow_reverse(snap):
        hits.append("sector_flow_reverse")

    calendar = in_rebalance_calendar_window(snap.trade_date)
    if calendar:
        hits.append("calendar_window")

    # Need >=3 hits for yes; calendar alone => watch
    if len(hits) >= 3:
        return RebalanceAssessment(
            window="yes",
            signal_hits=hits,
            note="机构换仓信号簇≥3：按再平衡/换手理解，勿极端切换",
        )
    if len(hits) >= 2 or (calendar and len(hits) >= 1):
        return RebalanceAssessment(
            window="watch",
            signal_hits=hits,
            note="换仓观察模式：提高警惕，单日资金流不作全仓依据",
        )
    return RebalanceAssessment(window="no", signal_hits=hits, note="")


def _sector_flow_reverse(snap: MarketSnapshot) -> bool:
    flows = snap.industry_flows or []
    if len(flows) < 4:
        return False

    def _net(row: dict) -> float:
        for key in ("main_net_inflow_yuan", "f62", "net_inflow", "main_net"):
            if key in row:
                try:
                    return float(row[key])
                except (TypeError, ValueError):
                    pass
        return 0.0

    def _name(row: dict) -> str:
        return str(row.get("name") or row.get("industry") or row.get("f14") or "")

    sorted_flows = sorted(flows, key=_net, reverse=True)
    top_in = sorted_flows[:3]
    top_out = sorted_flows[-3:]

    out_mag = abs(min(_net(r) for r in top_out))
    in_mag = max(_net(r) for r in top_in)
    if out_mag < _SECTOR_FLOW_YUAN or in_mag < _SECTOR_FLOW_YUAN:
        return False

    growth_kw = ("半导体", "通信", "电子", "软件", "计算机", "传媒", "光")
    value_kw = ("证券", "保险", "银行", "非银", "医药", "养殖", "化工", "煤炭")

    out_growth = any(any(k in _name(r) for k in growth_kw) for r in top_out if _net(r) < 0)
    in_value = any(any(k in _name(r) for k in value_kw) for r in top_in if _net(r) > 0)
    return out_growth and in_value
