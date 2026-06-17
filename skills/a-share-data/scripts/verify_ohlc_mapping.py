#!/usr/bin/env python3
"""校验各数据源 OHLC 映射是否与 --quote 一致。用法：run.sh verify_ohlc_mapping.py [代码...]"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from fetch_realtime import (  # noqa: E402
    _get_price_day_tx,
    _get_price_sina,
    get_price,
    normalize_code,
)

RUN = Path.home() / ".cursor/skills/a-share-data/run.sh"
DEFAULT_CODES = ["600519", "002594", "300750", "688981", "000001"]


def ohlc_valid(row) -> bool:
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    return l <= min(o, c) + 1e-6 and max(o, c) <= h + 1e-6


def fetch_quote(code6: str) -> dict:
    proc = subprocess.run(
        [str(RUN), "fetch_realtime.py", "--quote", code6, "--json"],
        capture_output=True,
        text=True,
        timeout=25,
    )
    if proc.returncode != 0:
        return {}
    d = json.loads(proc.stdout)
    return {
        "price": float(d.get("最新价") or 0),
        "high": float(d.get("最高") or 0),
        "low": float(d.get("最低") or 0),
    }


def check_source(name: str, df: pd.DataFrame | None, quote: dict) -> str:
    if df is None or df.empty:
        return f"{name}:EMPTY"
    last = df.iloc[-1]
    if not ohlc_valid(last):
        return f"{name}:OHLC_INVALID close={last['close']}"
    qp = quote.get("price") or 0
    diff = abs(float(last["close"]) - qp) / qp * 100 if qp else -1
    flag = "OK" if diff >= 0 and diff <= 0.5 else "MISMATCH"
    return f"{name}:{flag} close={float(last['close']):.2f} diff={diff:.2f}%"


def main() -> int:
    codes = sys.argv[1:] if len(sys.argv) > 1 else DEFAULT_CODES
    failed = 0
    print("code | quote | sina | tencent | get_price(1d)")
    for code6 in codes:
        nc = normalize_code(code6)
        q = fetch_quote(code6)
        parts = [
            check_source("sina", _get_price_sina(nc, 5, "1d"), q),
            check_source("tencent", _get_price_day_tx(nc, 5, "1d"), q),
            check_source("get_price", get_price(nc, "1d", 5), q),
        ]
        line = f"{code6} | {q.get('price', '?')} | " + " | ".join(parts)
        print(line)
        if any(x.split(":")[1].split()[0] in ("OHLC_INVALID", "MISMATCH") for x in parts if "EMPTY" not in x):
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
