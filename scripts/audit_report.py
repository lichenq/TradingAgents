#!/usr/bin/env python3
"""Write weekly audit KPI report (win rate by strategy/rating)."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dataflows.audit_report import build_audit_report, write_audit_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate audit KPI report JSON")
    parser.add_argument("--results-dir", default="", help="Results directory")
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--as-of", default="", help="Report as-of date YYYY-MM-DD")
    parser.add_argument("--print", action="store_true", help="Print summary to stdout")
    args = parser.parse_args()

    results_dir = Path(args.results_dir) if args.results_dir else Path(DEFAULT_CONFIG["results_dir"])
    as_of = (
        datetime.strptime(args.as_of[:10], "%Y-%m-%d").date()
        if args.as_of.strip()
        else None
    )
    path = write_audit_report(results_dir, lookback_days=args.lookback_days, as_of=as_of)
    print(f"Wrote {path}")

    if args.print:
        report = build_audit_report(
            results_dir,
            lookback_days=args.lookback_days,
            as_of=as_of or datetime.now().date(),
        )
        overall = report["overall"]
        wr = overall.get("win_rate")
        ar = overall.get("avg_return")
        wr_s = f"{wr:.0%}" if wr is not None else "N/A"
        ar_s = f"{ar:+.1%}" if ar is not None else "N/A"
        print(
            f"Overall ({overall['count']} cases, {report['since']}..{report['as_of']}): "
            f"win_rate={wr_s} avg_return={ar_s}"
        )
        for label, bucket in report.get("by_strategy", {}).items():
            bwr = bucket.get("win_rate")
            bwr_s = f"{bwr:.0%}" if bwr is not None else "N/A"
            print(f"  strategy={label}: n={bucket['count']} win_rate={bwr_s}")
        for label, bucket in report.get("by_rating", {}).items():
            bwr = bucket.get("win_rate")
            bwr_s = f"{bwr:.0%}" if bwr is not None else "N/A"
            print(f"  rating={label}: n={bucket['count']} win_rate={bwr_s}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
