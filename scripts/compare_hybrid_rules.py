#!/usr/bin/env python3
"""Compare hybrid v1 vs v2 entry rules on historical data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from tradingagents.dataflows.limit_entry_rules import aggregate_compare, run_compare_for_ticker

DEFAULT_TICKERS = "601138,002475,002241,300433,002600,603296"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare hybrid entry rule variants")
    parser.add_argument("--tickers", default=DEFAULT_TICKERS)
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-07-03")
    parser.add_argument("--json", action="store_true", dest="output_json")
    args = parser.parse_args()

    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    all_rows = []
    for ticker in tickers:
        try:
            all_rows.extend(run_compare_for_ticker(ticker, args.start, args.end))
        except Exception as exc:
            print(f"[WARN] {ticker}: {exc}", file=sys.stderr)

    agg = aggregate_compare(all_rows)
    if args.output_json:
        print(json.dumps({"rows": all_rows, "aggregate": agg}, ensure_ascii=False, indent=2))
        return 0 if all_rows else 1

    print(f"Hybrid compare · signal=hybrid_entry · {args.start} → {args.end}\n")
    print("Per ticker:")
    hdr = f"{'ticker':<8} {'rule':<26} {'sig':>5} {'fill%':>6} {'win20%':>7} {'r20':>7} {'stop%':>6}"
    print(hdr)
    print("-" * len(hdr))
    for row in all_rows:
        print(
            f"{row['ticker']:<8} {row['rule']:<26} {row['signals']:>5} "
            f"{row['fill_rate_pct']:>6.1f} "
            f"{row['win_rate_20d_pct'] if row['win_rate_20d_pct'] is not None else 'n/a':>7} "
            f"{row['ret_20d_pct'] if row['ret_20d_pct'] is not None else 'n/a':>7} "
            f"{row['stop_hit_pct'] if row['stop_hit_pct'] is not None else 'n/a':>6}"
        )

    print("\nAggregate (6 tickers, score=0.35×fill+0.35×win+0.30×ret×10):")
    ahdr = f"{'rule':<30} {'fill%':>6} {'win20%':>7} {'r20':>7} {'stop%':>6} {'score':>6}"
    print(ahdr)
    print("-" * len(ahdr))
    for v in agg["variants"]:
        print(
            f"{v['rule']:<30} {v['avg_fill_rate_pct']:>6.1f} "
            f"{v['avg_win_rate_20d_pct']:>7.1f} "
            f"{v['avg_ret_20d_pct']:>7.2f} "
            f"{v['avg_stop_hit_pct']:>6.1f} {v['score']:>6.1f}"
        )
    best = agg["variants"][0] if agg["variants"] else None
    if best:
        print(
            f"\nBest composite score: {best['rule']} "
            f"(fill={best['avg_fill_rate_pct']}%, win={best['avg_win_rate_20d_pct']}%, r20={best['avg_ret_20d_pct']}%)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
