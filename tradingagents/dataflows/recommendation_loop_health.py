"""Health checks for recommendation audit + forecast prediction loops."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from tradingagents.dataflows.audit_report import build_audit_report
from tradingagents.graph.storage import get_db_path, init_db


@dataclass
class HealthFinding:
    level: str  # ok | warn | critical
    code: str
    message: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def health_config() -> Dict[str, Any]:
    return {
        "min_audit_samples": _env_int("VERIFY_MIN_AUDIT_SAMPLES", 5),
        "min_win_rate": _env_float("VERIFY_MIN_WIN_RATE", 0.5),
        "win_rate_min_samples": _env_int("VERIFY_WIN_RATE_MIN_SAMPLES", 10),
        "max_report_age_days": _env_int("VERIFY_MAX_REPORT_AGE_DAYS", 3),
        "max_job_log_age_days": _env_int("VERIFY_MAX_JOB_LOG_AGE_DAYS", 2),
        "require_launchd": os.environ.get("VERIFY_REQUIRE_LAUNCHD", "").strip().lower()
        in ("1", "true", "yes", "on"),
        "audit_horizon": _env_int("AUDIT_GATE_HORIZON", 3),
    }


def _db_counts(db_path: Path) -> Dict[str, int]:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        out: Dict[str, int] = {}
        for table in ("recommendations", "backtest_audits", "reports"):
            try:
                out[table] = int(cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            except sqlite3.OperationalError:
                out[table] = 0
        return out
    finally:
        conn.close()


def _pending_audits(db_path: Path, horizon: int) -> int:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*) FROM recommendations r
            LEFT JOIN backtest_audits b
              ON r.code = b.ticker AND r.trade_date = b.recommendation_date
              AND b.days_elapsed = ?
            WHERE b.id IS NULL
            """,
            (horizon,),
        )
        return int(cur.fetchone()[0])
    finally:
        conn.close()


def _file_age_days(path: Path) -> Optional[float]:
    if not path.is_file():
        return None
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return (datetime.now() - mtime).total_seconds() / 86400.0


def _latest_job_log_age(log_dir: Path, prefix: str) -> Optional[float]:
    if not log_dir.is_dir():
        return None
    logs = sorted(log_dir.glob(f"{prefix}-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return None
    return _file_age_days(logs[0])


def check_launchd_agents(labels: List[str]) -> List[HealthFinding]:
    import subprocess

    findings: List[HealthFinding] = []
    uid = os.getuid()
    missing: List[str] = []
    for label in labels:
        try:
            subprocess.run(
                ["launchctl", "print", f"gui/{uid}/{label}"],
                capture_output=True,
                check=True,
                timeout=5,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            missing.append(label)
    if missing:
        findings.append(
            HealthFinding(
                "critical",
                "launchd_missing",
                f"LaunchAgents not loaded: {', '.join(missing)}",
            )
        )
    else:
        findings.append(
            HealthFinding("ok", "launchd_ok", f"LaunchAgents loaded ({len(labels)})")
        )
    return findings


def run_health_checks(
    results_dir: str | Path,
    *,
    as_of: Optional[date] = None,
) -> Dict[str, Any]:
    """Run all verification checks; return report dict with exit_code."""
    cfg = health_config()
    as_of = as_of or date.today()
    results_dir = Path(results_dir)
    findings: List[HealthFinding] = []

    db_path = get_db_path(results_dir)
    if not db_path.is_file():
        findings.append(
            HealthFinding("critical", "db_missing", f"SQLite not found: {db_path}")
        )
        return _finalize(findings, cfg, results_dir, as_of)

    init_db(results_dir)
    counts = _db_counts(db_path)
    findings.append(
        HealthFinding(
            "ok",
            "db_counts",
            f"DB rows: recommendations={counts['recommendations']} "
            f"audits={counts['backtest_audits']} reports={counts['reports']}",
        )
    )

    pending = _pending_audits(db_path, cfg["audit_horizon"])
    if counts["recommendations"] > 0 and pending > 0:
        findings.append(
            HealthFinding(
                "warn",
                "audit_pending",
                f"{pending} recommendation(s) not yet audited at {cfg['audit_horizon']}d horizon",
            )
        )

    report_path = results_dir / "audit_reports" / "latest.json"
    report_age = _file_age_days(report_path)
    audit_report: Dict[str, Any] = {}
    if report_age is None:
        findings.append(
            HealthFinding("warn", "audit_report_missing", "audit_reports/latest.json missing")
        )
    elif report_age > cfg["max_report_age_days"]:
        findings.append(
            HealthFinding(
                "warn",
                "audit_report_stale",
                f"audit_reports/latest.json is {report_age:.1f}d old",
            )
        )
    else:
        try:
            audit_report = json.loads(report_path.read_text(encoding="utf-8"))
            findings.append(
                HealthFinding("ok", "audit_report_fresh", f"audit report age {report_age:.1f}d")
            )
        except (json.JSONDecodeError, OSError) as exc:
            findings.append(
                HealthFinding("warn", "audit_report_invalid", f"Cannot read audit report: {exc}")
            )

    if not audit_report:
        try:
            audit_report = build_audit_report(results_dir, lookback_days=30, as_of=as_of)
        except Exception as exc:
            findings.append(
                HealthFinding("warn", "audit_report_build_failed", str(exc)[:120])
            )

    overall = audit_report.get("overall") or {}
    n = int(overall.get("count") or 0)
    if n < cfg["min_audit_samples"]:
        findings.append(
            HealthFinding(
                "warn",
                "audit_low_samples",
                f"Only {n} audit cases (need {cfg['min_audit_samples']} for reliable KPI)",
            )
        )
    else:
        wr = overall.get("win_rate")
        ar = overall.get("avg_return")
        wr_s = f"{wr:.0%}" if wr is not None else "N/A"
        ar_s = f"{ar:+.1%}" if ar is not None else "N/A"
        findings.append(
            HealthFinding(
                "ok",
                "audit_kpi",
                f"30d KPI n={n} win_rate={wr_s} avg_return={ar_s}",
            )
        )
        if n >= cfg["win_rate_min_samples"] and wr is not None and wr < cfg["min_win_rate"]:
            findings.append(
                HealthFinding(
                    "warn",
                    "audit_win_rate_low",
                    f"win_rate {wr:.0%} < {cfg['min_win_rate']:.0%} (n={n})",
                )
            )

    cal = audit_report.get("rating_calibration") or {}
    if cal.get("downgrade_buy"):
        findings.append(
            HealthFinding(
                "warn",
                "buy_calibration_active",
                cal.get("downgrade_buy_reason") or "Buy downgrade active",
            )
        )

    job_dir = results_dir / "audit_jobs"
    if not job_dir.is_dir():
        legacy = results_dir / "premarket_dryrun" / "jobs"
        job_dir = legacy if legacy.is_dir() else job_dir
    audit_log_age = _latest_job_log_age(job_dir, "audit")
    if audit_log_age is None:
        findings.append(
            HealthFinding("warn", "audit_job_log_missing", f"No audit job logs in {job_dir}")
        )
    elif audit_log_age > cfg["max_job_log_age_days"]:
        findings.append(
            HealthFinding(
                "warn",
                "audit_job_stale",
                f"Last audit job log {audit_log_age:.1f}d ago",
            )
        )
    else:
        findings.append(
            HealthFinding("ok", "audit_job_recent", f"Last audit job log {audit_log_age:.1f}d ago")
        )

    rec_dir = results_dir / "recommendations"
    recent_json = sorted(rec_dir.glob("*/recommended_stocks.json"), reverse=True)[:3]
    if not recent_json:
        findings.append(
            HealthFinding("warn", "no_recommendation_exports", "No recommended_stocks.json found")
        )
    else:
        latest = recent_json[0]
        findings.append(
            HealthFinding(
                "ok",
                "latest_recommendation",
                f"Latest export: {latest.parent.name} ({_file_age_days(latest):.1f}d ago)",
            )
        )

    if cfg["require_launchd"]:
        labels = [
            "com.tradingagents.premarket.audit",
            "com.tradingagents.premarket.verify",
        ]
        findings.extend(check_launchd_agents(labels))

    return _finalize(findings, cfg, results_dir, as_of, audit_report=audit_report)


def _finalize(
    findings: List[HealthFinding],
    cfg: Dict[str, Any],
    results_dir: Path,
    as_of: date,
    *,
    audit_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    critical = [f for f in findings if f.level == "critical"]
    warns = [f for f in findings if f.level == "warn"]
    if critical:
        exit_code = 2
    elif warns:
        exit_code = 1
    else:
        exit_code = 0

    return {
        "as_of": as_of.isoformat(),
        "results_dir": str(results_dir),
        "exit_code": exit_code,
        "status": "critical" if exit_code == 2 else ("warn" if exit_code == 1 else "ok"),
        "config": cfg,
        "findings": [f.to_dict() for f in findings],
        "summary": {
            "critical": len(critical),
            "warn": len(warns),
            "ok": len([f for f in findings if f.level == "ok"]),
        },
        "audit_overall": (audit_report or {}).get("overall"),
        "by_strategy": (audit_report or {}).get("by_strategy"),
        "by_rating": (audit_report or {}).get("by_rating"),
    }
