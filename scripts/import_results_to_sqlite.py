#!/usr/bin/env python3
"""Import historical Markdown / JSON report bundles from ``results/`` into SQLite.

Scans for ``complete_report.md`` (same layout as live runs). For each bundle directory:
- Parses ``名称-六位代码-YYYY-MM-DD`` folder names (optional trailing time suffix).
- Falls back to ``*/TradingAgentsStrategy_logs/report_YYYY-MM-DD/`` style paths.
- Loads sibling ``{dir}.json`` state dump when present for full ``reports`` row fields.
- Otherwise stitches optional per-section ``.md`` files next to ``complete_report.md``.

Optionally imports ``results/recommendations/<date>/recommended_stocks.json`` into
``recommendations`` (same shape as ``run_recommend`` output).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.storage import (
    get_db_path,
    init_db,
    query_report,
    save_recommendation,
    save_report,
)
from tradingagents.market import normalize_a_share_code

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("import_results")

_BUNDLE_DIR_RE = re.compile(
    r"^(.+)-(?P<code>\d{6})-(?P<date>\d{4}-\d{2}-\d{2})(?:\s+.*)?$"
)
_REPORT_SUBDIR_RE = re.compile(r"^report_(?P<date>\d{4}-\d{2}-\d{2})$")


def _read(p: Path) -> str:
    if p.is_file():
        return p.read_text(encoding="utf-8")
    return ""


def a_share_prefixed_ticker(code6: str) -> str:
    c = normalize_a_share_code(code6)
    if not c.isdigit() or len(c) != 6:
        return c
    if c.startswith(("5", "6", "9")):
        return f"sh{c}"
    return f"sz{c}"


def parse_bundle_dir_name(dir_name: str) -> Optional[Tuple[str, str]]:
    """Return (prefixed_ticker, trade_date) from a standard bundle directory name."""
    m = _BUNDLE_DIR_RE.match(dir_name.strip())
    if not m:
        return None
    code6 = m.group("code")
    date_s = m.group("date")
    return a_share_prefixed_ticker(code6), date_s


def infer_ticker_and_date(bundle_dir: Path, results_root: Path) -> Tuple[str, str]:
    """Resolve DB (ticker, trade_date); may raise ValueError if unusable."""
    parsed = parse_bundle_dir_name(bundle_dir.name)
    if parsed:
        return parsed

    m = _REPORT_SUBDIR_RE.match(bundle_dir.name)
    if m:
        rel = bundle_dir.relative_to(results_root)
        parts = rel.parts
        if parts:
            top = parts[0]
            if top.endswith((".SS", ".SZ", ".SH")) or top.isdigit() or top.lower().startswith(
                ("sh", "sz")
            ):
                return top, m.group("date")

    raise ValueError(f"cannot infer ticker/date from directory name: {bundle_dir.name}")


def _rating_from_final_decision(text: str) -> str:
    if not text:
        return ""
    for line in text.splitlines():
        low = line.lower()
        if "rating" in low or "评级" in line:
            return line.strip()[:200]
    return text.strip()[:50]


def find_state_json(bundle_dir: Path) -> Optional[Path]:
    exact = bundle_dir / f"{bundle_dir.name}.json"
    if exact.is_file():
        return exact
    jsons = sorted(bundle_dir.glob("*.json"))
    for p in jsons:
        if p.name.startswith("."):
            continue
        try:
            if p.stat().st_size < 64:
                continue
        except OSError:
            continue
        return p
    return None


def load_state_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("skip bad JSON %s: %s", path, e)
        return None


def build_save_report_args(
    bundle_dir: Path,
    complete_report: str,
    data: Optional[Dict[str, Any]],
    ticker: str,
    trade_date: str,
) -> Dict[str, Any]:
    """Keyword args for ``save_report``."""
    if data:
        debate = data.get("investment_debate_state") or {}
        rating = (data.get("final_trade_decision_rating") or "").strip()
        if not rating:
            rating = _rating_from_final_decision(data.get("final_trade_decision") or "")
        if not rating:
            rating = "imported"
        return {
            "ticker": ticker,
            "trade_date": trade_date,
            "rating": str(rating)[:200],
            "complete_report": complete_report,
            "final_trade_decision": data.get("final_trade_decision") or "",
            "investment_plan": data.get("investment_plan") or "",
            "market_report": data.get("market_report") or "",
            "sentiment_report": data.get("sentiment_report") or "",
            "bull_history": debate.get("bull_history") or "",
            "bear_history": debate.get("bear_history") or "",
        }

    analysts = bundle_dir / "1_analysts"
    research = bundle_dir / "2_research"
    return {
        "ticker": ticker,
        "trade_date": trade_date,
        "rating": _rating_from_final_decision(
            _read(bundle_dir / "final_trade_decision.md")
        )
        or "imported",
        "complete_report": complete_report,
        "final_trade_decision": _read(bundle_dir / "final_trade_decision.md"),
        "investment_plan": _read(bundle_dir / "investment_plan.md"),
        "market_report": _read(analysts / "market.md"),
        "sentiment_report": _read(analysts / "sentiment.md"),
        "bull_history": _read(research / "bull.md"),
        "bear_history": _read(research / "bear.md"),
    }


def iter_complete_reports(results_root: Path) -> List[Path]:
    out: List[Path] = []
    if not results_root.is_dir():
        return out
    for p in results_root.rglob("complete_report.md"):
        if not p.is_file():
            continue
        if any(part.startswith(".") for part in p.parts):
            continue
        out.append(p)
    return sorted(out)


def import_one_report(
    complete_path: Path,
    results_root: Path,
    *,
    dry_run: bool,
    skip_existing: bool,
) -> str:
    bundle_dir = complete_path.parent
    text = _read(complete_path)
    if not text.strip():
        return "skip_empty"

    try:
        ticker_fs, date_fs = infer_ticker_and_date(bundle_dir, results_root)
    except ValueError:
        # Last resort: parse from Markdown header (标的 / 交易日)
        try:
            from scripts.generate_live_html import extract_meta

            meta = extract_meta(text)
            ticker_fs = meta.get("ticker") or ""
            date_fs = (meta.get("date") or "")[:10]
        except Exception:
            ticker_fs, date_fs = "", ""
        if not ticker_fs or not re.match(r"^\d{4}-\d{2}-\d{2}$", date_fs or ""):
            logger.warning("skip (cannot resolve ticker/date): %s", complete_path)
            return "skip_unresolved"

    # Normalize A-share storage key to sh/sz + 6 digits when possible
    code6 = normalize_a_share_code(ticker_fs)
    if code6.isdigit() and len(code6) == 6:
        ticker = a_share_prefixed_ticker(code6)
    else:
        ticker = ticker_fs

    trade_date = date_fs[:10]

    if skip_existing and query_report(results_root, ticker, trade_date):
        return "skip_existing"

    jpath = find_state_json(bundle_dir)
    data = load_state_json(jpath) if jpath else None

    kwargs = build_save_report_args(bundle_dir, text, data, ticker, trade_date)

    if dry_run:
        logger.info("[dry-run] would import report %s %s <- %s", ticker, trade_date, complete_path)
        return "dry_run"

    save_report(results_root, **kwargs)
    logger.info("imported report %s %s <- %s", ticker, trade_date, complete_path)
    return "imported"


def import_recommendation_files(results_root: Path, *, dry_run: bool) -> int:
    rec_root = results_root / "recommendations"
    if not rec_root.is_dir():
        return 0
    n = 0
    for day_dir in sorted(rec_root.iterdir()):
        if not day_dir.is_dir():
            continue
        jp = day_dir / "recommended_stocks.json"
        if not jp.is_file():
            continue
        try:
            summary = json.loads(jp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("skip recommendations %s: %s", jp, e)
            continue
        trade_date = (summary.get("trade_date") or day_dir.name)[:10]
        strategy = str(summary.get("strategy") or "imported")
        for rec in summary.get("recommendations") or []:
            if dry_run:
                logger.info(
                    "[dry-run] would import recommendation %s %s %s",
                    trade_date,
                    rec.get("code"),
                    strategy,
                )
            else:
                save_recommendation(results_root, trade_date, strategy, rec)
            n += 1
        if not dry_run:
            logger.info("imported %d recommendation rows from %s", len(summary.get("recommendations") or []), jp)
    return n


def resolve_results_root(cli_value: str) -> Path:
    """Prefer explicit flag, then env, then ./results if present, else default_config."""
    if cli_value.strip():
        return Path(cli_value).expanduser().resolve()
    env = (os.environ.get("TRADINGAGENTS_RESULTS_DIR") or "").strip()
    if env:
        return Path(env).expanduser().resolve()
    cwd_results = Path.cwd() / "results"
    if cwd_results.is_dir():
        return cwd_results.resolve()
    return Path(DEFAULT_CONFIG["results_dir"]).expanduser().resolve()


def main() -> int:
    ap = argparse.ArgumentParser(description="Import results/ report bundles into SQLite")
    ap.add_argument(
        "--results-dir",
        default="",
        help="Results root (default: ./results if present, else TRADINGAGENTS_RESULTS_DIR / config)",
    )
    ap.add_argument("--dry-run", action="store_true", help="Log actions only; do not write DB")
    ap.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip (ticker, trade_date) pairs that already exist in reports",
    )
    ap.add_argument(
        "--no-recommendations",
        action="store_true",
        help="Do not import results/recommendations/*/recommended_stocks.json",
    )
    args = ap.parse_args()

    results_root = resolve_results_root(args.results_dir)
    if not results_root.is_dir():
        logger.error("results directory not found: %s", results_root)
        return 1

    init_db(results_root)
    db_path = get_db_path(results_root)
    logger.info("SQLite database: %s", db_path)

    paths = iter_complete_reports(results_root)
    logger.info("found %d complete_report.md file(s) under %s", len(paths), results_root)

    stats = {"imported": 0, "dry_run": 0, "skip_empty": 0, "skip_unresolved": 0, "skip_existing": 0}
    for p in paths:
        r = import_one_report(
            p,
            results_root,
            dry_run=args.dry_run,
            skip_existing=args.skip_existing,
        )
        stats[r] = stats.get(r, 0) + 1

    rec_count = 0
    if not args.no_recommendations:
        rec_count = import_recommendation_files(results_root, dry_run=args.dry_run)

    logger.info("report import summary: %s", stats)
    if not args.no_recommendations:
        logger.info("recommendation rows processed: %s", rec_count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
