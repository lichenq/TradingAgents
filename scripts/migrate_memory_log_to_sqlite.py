#!/usr/bin/env python3
"""Migrate markdown trading memory log entries into SQLite memory_log_entries."""

from __future__ import annotations

import argparse
import datetime
import sqlite3
from pathlib import Path

from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.graph.storage import get_db_path


def parse_percent(text: str | None) -> float | None:
    if not text:
        return None
    t = str(text).strip()
    if not t.endswith("%"):
        return None
    try:
        return float(t[:-1]) / 100.0
    except ValueError:
        return None


def parse_holding_days(text: str | None) -> int | None:
    if not text:
        return None
    t = str(text).strip().lower()
    if t.endswith("d"):
        t = t[:-1]
    try:
        return int(t)
    except ValueError:
        return None


def migrate(memory_log_path: Path, results_dir: Path) -> tuple[int, int]:
    # Force file backend so we can always parse old markdown source.
    reader = TradingMemoryLog(
        {
            "memory_log_backend": "file",
            "memory_log_path": str(memory_log_path),
        }
    )
    entries = reader.load_entries()
    if not entries:
        return 0, 0

    db_path = get_db_path(results_dir)
    writer = TradingMemoryLog(
        {
            "memory_log_backend": "sqlite",
            "results_dir": str(results_dir),
        }
    )
    # Ensure schema exists.
    writer.load_entries()

    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.cursor()
        inserted = 0
        updated = 0
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for e in entries:
            raw_return = parse_percent(e.get("raw"))
            alpha_return = parse_percent(e.get("alpha"))
            holding_days = parse_holding_days(e.get("holding"))
            pending_flag = 1 if e.get("pending") else 0

            # Try update existing row first (idempotent reruns).
            cursor.execute(
                """
                UPDATE memory_log_entries
                SET rating = ?,
                    pending = ?,
                    raw_return = ?,
                    alpha_return = ?,
                    holding_days = ?,
                    decision = ?,
                    reflection = ?,
                    updated_at = ?
                WHERE ticker = ? AND trade_date = ?
                """,
                (
                    e.get("rating") or "Hold",
                    pending_flag,
                    raw_return,
                    alpha_return,
                    holding_days,
                    e.get("decision") or "",
                    e.get("reflection") or "",
                    now,
                    e.get("ticker") or "",
                    e.get("date") or "",
                ),
            )
            if cursor.rowcount > 0:
                updated += 1
                continue

            cursor.execute(
                """
                INSERT INTO memory_log_entries (
                    trade_date, ticker, rating, pending,
                    raw_return, alpha_return, holding_days,
                    decision, reflection, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    e.get("date") or "",
                    e.get("ticker") or "",
                    e.get("rating") or "Hold",
                    pending_flag,
                    raw_return,
                    alpha_return,
                    holding_days,
                    e.get("decision") or "",
                    e.get("reflection") or "",
                    now,
                    now,
                ),
            )
            inserted += 1
        conn.commit()
        return inserted, updated
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate trading_memory.md into SQLite memory_log_entries table.")
    parser.add_argument(
        "--memory-log-path",
        type=str,
        default=str(Path.home() / ".tradingagents" / "memory" / "trading_memory.md"),
        help="Path to legacy markdown memory log file.",
    )
    parser.add_argument(
        "--results-dir",
        type=str,
        default=str(Path.home() / "Projects" / "TradingAgents" / "results"),
        help="Results directory where trading_agents.db is located.",
    )
    args = parser.parse_args()

    memory_log_path = Path(args.memory_log_path).expanduser().resolve()
    results_dir = Path(args.results_dir).expanduser().resolve()

    if not memory_log_path.exists():
        print(f"No source file found: {memory_log_path}")
        return

    inserted, updated = migrate(memory_log_path, results_dir)
    db_path = get_db_path(results_dir)
    print(f"Migration complete. inserted={inserted}, updated={updated}, db={db_path}")


if __name__ == "__main__":
    main()
