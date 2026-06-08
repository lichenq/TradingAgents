"""User-provided cost basis and share count for held-position analysis."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

_PRICE_CN_RE = re.compile(r"\*\*现价\*\*:\s*([\d]+(?:\.\d+)?)\s*元")


def parse_position_cost(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        cost = float(value)
    except (TypeError, ValueError):
        return None
    return cost if cost > 0 else None


def parse_position_shares(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        shares = int(float(value))
    except (TypeError, ValueError):
        return None
    return shares if shares > 0 else None


def get_holdings_from_config(config: Dict[str, Any]) -> Tuple[Optional[float], Optional[int]]:
    return (
        parse_position_cost(config.get("position_cost")),
        parse_position_shares(config.get("position_shares")),
    )


def has_position_holdings(config: Dict[str, Any]) -> bool:
    cost, shares = get_holdings_from_config(config)
    return cost is not None or shares is not None


def ensure_held_context_for_holdings(config: Dict[str, Any]) -> None:
    """When cost or shares are set, upgrade empty→held (but preserve retail explicitly)."""
    if not has_position_holdings(config):
        return
    ctx = (config.get("position_context") or "empty").strip().lower()
    if ctx == "empty":
        config["position_context"] = "held"


def extract_price_from_verified(verified_md: str) -> Optional[float]:
    if not verified_md:
        return None
    match = _PRICE_CN_RE.search(verified_md)
    if not match:
        return None
    try:
        price = float(match.group(1))
    except ValueError:
        return None
    return price if price > 0 else None


def _use_chinese(config: Dict[str, Any]) -> bool:
    lang = (config.get("output_language") or "English").strip().lower()
    return lang not in ("english", "en")


def format_position_holdings_markdown(
    cost: Optional[float],
    shares: Optional[int],
    *,
    current_price: Optional[float] = None,
    use_chinese: bool = True,
) -> str:
    if use_chinese:
        lines = ["## 投资者持仓（用户提供，须引用）", ""]
        if cost is not None:
            lines.append(f"- **持仓成本**: {cost:.4g} 元/股")
        if shares is not None:
            lines.append(f"- **持股数量**: {shares} 股")
        if cost is not None and shares is not None:
            total_cost = cost * shares
            lines.append(f"- **持仓成本总额**: {total_cost:.2f} 元")
            if current_price is not None and current_price > 0:
                market_value = current_price * shares
                pnl = market_value - total_cost
                pnl_pct = (pnl / total_cost) * 100.0
                lines.extend(
                    [
                        f"- **现价**: {current_price:.2f} 元（来自上方行情硬数据）",
                        f"- **持仓市值**: {market_value:.2f} 元",
                        f"- **浮动盈亏**: {pnl:+.2f} 元（{pnl_pct:+.2f}%）",
                    ]
                )
            else:
                lines.append("- **浮动盈亏**: 未计算（行情硬数据块无现价）")
        lines.append("")
        lines.append(
            "*持仓成本与股数由投资者提供；加减仓建议应结合上述盈亏，勿编造持仓成本。*"
        )
        return "\n".join(lines)

    lines = ["## Investor position (user-provided — cite in debate)", ""]
    if cost is not None:
        lines.append(f"- **Cost basis**: {cost:.4g} per share")
    if shares is not None:
        lines.append(f"- **Shares held**: {shares}")
    if cost is not None and shares is not None:
        total_cost = cost * shares
        lines.append(f"- **Total cost basis**: {total_cost:.2f}")
        if current_price is not None and current_price > 0:
            market_value = current_price * shares
            pnl = market_value - total_cost
            pnl_pct = (pnl / total_cost) * 100.0
            lines.extend(
                [
                    f"- **Last price**: {current_price:.2f} (from verified market data above)",
                    f"- **Market value**: {market_value:.2f}",
                    f"- **Unrealized P&L**: {pnl:+.2f} ({pnl_pct:+.2f}%)",
                ]
            )
        else:
            lines.append("- **Unrealized P&L**: not computed (no price in verified block)")
    lines.append("")
    lines.append(
        "*Cost and shares are user-supplied; do not invent a different cost basis.*"
    )
    return "\n".join(lines)


def enrich_verified_with_position_holdings(verified_md: str, config: Dict[str, Any]) -> str:
    """Append holdings block to verified facts; may set position_context to held."""
    ensure_held_context_for_holdings(config)
    cost, shares = get_holdings_from_config(config)
    if cost is None and shares is None:
        return verified_md

    current_price = extract_price_from_verified(verified_md)
    block = format_position_holdings_markdown(
        cost,
        shares,
        current_price=current_price,
        use_chinese=_use_chinese(config),
    )
    verified = (verified_md or "").strip()
    if verified:
        return f"{verified}\n\n{block}"
    return block
