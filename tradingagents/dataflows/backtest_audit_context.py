"""Format recent backtest audits for agent prompt injection."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from tradingagents.graph.storage import query_backtest_audits


def _ticker_code6(ticker: str) -> str:
    return "".join(ch for ch in ticker if ch.isdigit())[-6:]


def audit_win_rate_summary(
    results_dir: str | Path,
    limit: int = 30,
) -> dict[str, Any]:
    """Aggregate simple stats from recent backtest audits."""
    rows = query_backtest_audits(results_dir, limit=limit)
    if not rows:
        return {"count": 0, "win_rate": None, "avg_return": None}

    returns = [float(r["raw_return"]) for r in rows if r.get("raw_return") is not None]
    if not returns:
        return {"count": len(rows), "win_rate": None, "avg_return": None}

    wins = sum(1 for x in returns if x > 0)
    return {
        "count": len(returns),
        "win_rate": wins / len(returns),
        "avg_return": sum(returns) / len(returns),
    }


def format_backtest_audit_context(
    results_dir: str | Path,
    *,
    limit: int = 8,
    ticker: Optional[str] = None,
) -> str:
    """Build prompt block from recent recommendation post-audits."""
    rows = query_backtest_audits(results_dir, ticker=ticker, limit=limit)
    if not rows:
        return ""

    lines = [
        "Recent recommendation post-audit lessons (actual returns after recommend date):",
    ]
    for r in rows[:limit]:
        code6 = _ticker_code6(str(r.get("ticker") or ""))
        rec_date = r.get("recommendation_date") or ""
        days = r.get("days_elapsed")
        ret = r.get("raw_return")
        ret_s = f"{float(ret):+.1%}" if ret is not None else "N/A"
        init_p = r.get("initial_price")
        end_p = r.get("end_price")
        price_s = ""
        if init_p is not None and end_p is not None:
            price_s = f" {float(init_p):.2f}→{float(end_p):.2f} CNY"
        reflection = (r.get("reflection") or "").strip().replace("\n", " ")
        if len(reflection) > 280:
            reflection = reflection[:277] + "..."
        lines.append(
            f"- {code6} rec={rec_date} +{days}d return={ret_s}{price_s}: {reflection}"
        )

    stats = audit_win_rate_summary(results_dir, limit=30)
    if stats["count"]:
        wr = stats["win_rate"]
        ar = stats["avg_return"]
        wr_s = f"{wr:.0%}" if wr is not None else "N/A"
        ar_s = f"{ar:+.1%}" if ar is not None else "N/A"
        lines.append(
            f"Audit aggregate (last {stats['count']} cases): win_rate={wr_s}, avg_return={ar_s}."
        )
    lines.append(
        "Apply these lessons when rating: penalize repeated failure patterns; "
        "do not chase high-PE momentum when audits show Hold/Underweight was correct."
    )
    return "\n".join(lines)
