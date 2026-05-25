"""Invoke a-share-data skill scripts via ``run.sh`` (proxy-safe).

When ``market_profile`` is ``cn``, TradingAgents routes **all** data tools here —
never Yahoo Finance or Alpha Vantage. Skill root:

    ~/.cursor/skills/a-share-data/

Override with env ``A_SHARE_DATA_RUN_SH`` if installed elsewhere.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, List, Optional


def default_run_sh() -> Path:
    env = os.environ.get("A_SHARE_DATA_RUN_SH", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".cursor/skills/a-share-data/run.sh"


def run_script(
    script: str,
    args: List[str],
    *,
    timeout: int = 45,
) -> tuple[bool, str, Optional[Any]]:
    """Run ``run.sh <script> [args...]`` and return (ok, raw_stdout, parsed_json)."""
    run_sh = default_run_sh()
    if not run_sh.is_file():
        return False, f"<a_share skill missing: {run_sh}>", None

    cmd = [str(run_sh), script, *args]
    env = os.environ.copy()
    for key in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    ):
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    env.setdefault("A_SHARE_PREFER_CURL", "1")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(run_sh.parent),
        )
    except subprocess.TimeoutExpired:
        return False, f"<a_share timeout after {timeout}s: {' '.join(cmd[-6:])}>", None
    except OSError as exc:
        return False, f"<a_share exec error: {exc}>", None

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        msg = stderr or stdout or f"exit {proc.returncode}"
        return False, f"<a_share failed: {msg}>", None

    parsed = _try_parse_json(stdout)
    return True, stdout, parsed


def _try_parse_json(text: str) -> Optional[Any]:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # JSON array/object may be embedded in logs — take last line block
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith(("{", "[")):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
    return None
