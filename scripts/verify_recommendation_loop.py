#!/usr/bin/env python3
"""Verify recommendation audit loop + forecast prediction health (exit codes for alerting)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

current_dir = Path(__file__).resolve().parent
project_root = current_dir.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.dataflows.recommendation_loop_health import run_health_checks


def _print_human(report: dict) -> None:
    print(f"status={report['status']} exit_code={report['exit_code']}")
    print(f"results_dir={report['results_dir']} as_of={report['as_of']}")
    sm = report.get("summary") or {}
    print(f"findings: ok={sm.get('ok')} warn={sm.get('warn')} critical={sm.get('critical')}")
    print("")
    for f in report.get("findings") or []:
        tag = f["level"].upper()
        print(f"[{tag}] {f['code']}: {f['message']}")
    overall = report.get("audit_overall") or {}
    if overall.get("count"):
        wr = overall.get("win_rate")
        ar = overall.get("avg_return")
        wr_s = f"{wr:.0%}" if wr is not None else "N/A"
        ar_s = f"{ar:+.1%}" if ar is not None else "N/A"
        print("")
        print(f"audit_overall: n={overall['count']} win_rate={wr_s} avg_return={ar_s}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify TradingAgents recommendation + forecast loops"
    )
    parser.add_argument("--results-dir", default="", help="Results directory")
    parser.add_argument("--json", action="store_true", help="Print JSON report to stdout")
    parser.add_argument("--as-of", default="", help="As-of date YYYY-MM-DD")
    parser.add_argument(
        "--write",
        default="",
        help="Write JSON report to path (default: results/health/latest.json)",
    )
    args = parser.parse_args()

    results_dir = Path(args.results_dir) if args.results_dir else Path(DEFAULT_CONFIG["results_dir"])
    as_of = (
        datetime.strptime(args.as_of[:10], "%Y-%m-%d").date()
        if args.as_of.strip()
        else None
    )
    report = run_health_checks(results_dir, as_of=as_of)

    out_path = args.write.strip() or str(results_dir / "health" / "latest.json")
    if out_path:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        if not args.json:
            print(f"Wrote {p}")

    if args.json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        _print_human(report)

    return int(report["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
