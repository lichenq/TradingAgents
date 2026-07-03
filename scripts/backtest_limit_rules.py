#!/usr/bin/env python3
"""Backtest limit-order entry rules on historical A-share daily bars."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from tradingagents.dataflows.limit_entry_rules import (  # noqa: E402
    RULE_IDS,
    SIGNAL_MODES,
    run_backtest_for_ticker,
)

DEFAULT_TICKERS = "601138,002475,002241,300433,002600,603296"


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest limit entry rules")
    parser.add_argument("--tickers", default=DEFAULT_TICKERS, help="Comma-separated 6-digit codes")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-07-03")
    parser.add_argument("--signal", choices=SIGNAL_MODES, default="macd_bear")
    parser.add_argument("--json", action="store_true", dest="output_json")
    args = parser.parse_args()

    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    all_rows = []
    for ticker in tickers:
        try:
            rows = run_backtest_for_ticker(ticker, args.start, args.end, signal_mode=args.signal)
            for row in rows:
                row["ticker"] = ticker
                row["signal_mode"] = args.signal
            all_rows.extend(rows)
        except Exception as exc:
            print(f"[WARN] {ticker}: {exc}", file=sys.stderr)

    if args.output_json:
        print(json.dumps(all_rows, ensure_ascii=False, indent=2))
        return 0 if all_rows else 1

    print(f"Limit rule backtest · signal={args.signal} · {args.start} → {args.end}\n")
    hdr = f"{'ticker':<8} {'rule':<14} {'signals':>7} {'fill%':>6} {'fill_d':>6} {'r5':>7} {'r20':>7} {'stop%':>6}"
    print(hdr)
    print("-" * len(hdr))
    for row in all_rows:
        print(
            f"{row['ticker']:<8} {row['rule']:<14} {row['signals']:>7} "
            f"{row['fill_rate_pct']:>6.1f} "
            f"{row['avg_fill_days'] or 0:>6.1f} "
            f"{row['ret_5d_pct'] if row['ret_5d_pct'] is not None else 'n/a':>7} "
            f"{row['ret_20d_pct'] if row['ret_20d_pct'] is not None else 'n/a':>7} "
            f"{row['stop_hit_pct'] if row['stop_hit_pct'] is not None else 'n/a':>6}"
        )

    hybrid = [r for r in all_rows if r["rule"] == "hybrid" and r.get("signals", 0) > 0]
    if hybrid:
        avg_r20 = sum(r["ret_20d_pct"] or 0 for r in hybrid) / len(hybrid)
        avg_fill = sum(r["fill_rate_pct"] for r in hybrid) / len(hybrid)
        print(f"\nhybrid aggregate: avg fill_rate={avg_fill:.1f}% avg ret_20d={avg_r20:.2f}% (n={len(hybrid)} tickers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
