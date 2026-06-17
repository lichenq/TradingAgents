#!/usr/bin/env python3
"""Industry-board main-force fund flow: EastMoney JSON (primary) + THS fallback."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Tuple

from http_util import get_json

EM_HOSTS = (
    "https://push2delay.eastmoney.com",
    "https://push2.eastmoney.com",
)
EM_PATH = "/api/qt/clist/get"
EM_UT = "b2884a393a59ad64002292a3e90d46a5"
EM_PAGE_SIZE = 100


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        if val is None or val == "":
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _source_preference() -> str:
    raw = os.environ.get("A_SHARE_INDUSTRY_FUND_FLOW_SOURCE", "em").strip().lower()
    if raw in ("ths", "10jqka", "tonghuashun"):
        return "ths"
    if raw == "auto":
        return "auto"
    return "em"


def _rank_rows(rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    rows.sort(key=lambda x: x["main_net_inflow_yuan"], reverse=True)
    for j, row in enumerate(rows, start=1):
        row["rank"] = j
    if limit is None or limit <= 0:
        return rows
    return rows[:limit]


def _em_page_params(page: int, page_size: int) -> dict[str, str]:
    return {
        "pn": str(page),
        "pz": str(page_size),
        "po": "1",
        "np": "1",
        "ut": EM_UT,
        "fltt": "2",
        "invt": "2",
        "fid": "f62",
        "fs": "m:90 t:2",
        "fields": "f12,f14,f2,f3,f62",
    }


def _fetch_em_page(page: int, page_size: int = EM_PAGE_SIZE) -> Tuple[List[dict], int]:
    params = _em_page_params(page, page_size)
    last_err: Exception | None = None
    for host in EM_HOSTS:
        try:
            payload = get_json(f"{host}{EM_PATH}", params=params, timeout=15)
            data = payload.get("data") or {}
            diff = data.get("diff") or []
            total = int(data.get("total") or 0)
            return diff if isinstance(diff, list) else [], total
        except Exception as exc:
            last_err = exc
    raise RuntimeError(str(last_err or "eastmoney fund flow unavailable"))


def _parse_em_item(item: dict) -> Dict[str, Any] | None:
    industry = str(item.get("f14") or "").strip()
    if not industry:
        return None
    yuan = _safe_float(item.get("f62"))
    return {
        "industry": industry,
        "main_net_inflow_yuan": yuan,
        "main_net_inflow_yi": yuan / 1e8,
        "change_pct": _safe_float(item.get("f3")),
        "rank": 0,
    }


def fetch_em_industry_rows(limit: int = 30) -> List[Dict[str, Any]]:
    need_all = limit is None or limit <= 0
    rows: List[Dict[str, Any]] = []
    page = 1
    total = 0

    while True:
        diff, total = _fetch_em_page(page)
        for item in diff:
            if not isinstance(item, dict):
                continue
            parsed = _parse_em_item(item)
            if parsed:
                rows.append(parsed)
        if not need_all and len(rows) >= limit:
            break
        if not diff or (total and page * EM_PAGE_SIZE >= total):
            break
        page += 1

    if not rows:
        raise RuntimeError("eastmoney fund flow returned no rows")
    return _rank_rows(rows, limit)


def fetch_ths_industry_rows(limit: int = 30) -> List[Dict[str, Any]]:
    import akshare as ak

    df = ak.stock_fund_flow_industry(symbol="即时")
    if df is None or df.empty:
        return []

    name_col = "行业" if "行业" in df.columns else df.columns[0]
    flow_col = None
    for c in df.columns:
        if str(c) in ("净额", "主力净流入-净额"):
            flow_col = c
            break
    if flow_col is None:
        for c in df.columns:
            if "净额" in str(c):
                flow_col = c
                break

    chg_col = "行业-涨跌幅" if "行业-涨跌幅" in df.columns else None
    if chg_col is None:
        for c in df.columns:
            if "涨跌幅" in str(c):
                chg_col = c
                break

    rows: List[Dict[str, Any]] = []
    for _i, row in df.iterrows():
        industry = str(row.get(name_col, "")).strip()
        if not industry:
            continue
        main_yi = _safe_float(row.get(flow_col)) if flow_col else 0.0
        rows.append(
            {
                "industry": industry,
                "main_net_inflow_yuan": main_yi * 1e8,
                "main_net_inflow_yi": main_yi,
                "change_pct": _safe_float(row.get(chg_col)) if chg_col else None,
                "rank": 0,
            }
        )
    return _rank_rows(rows, limit)


def fetch_industry_rows(limit: int = 30) -> Tuple[List[Dict[str, Any]], str]:
    pref = _source_preference()
    if pref == "ths":
        return fetch_ths_industry_rows(limit), "ths"

    try:
        return fetch_em_industry_rows(limit), "eastmoney"
    except Exception:
        if pref == "em":
            raise
        return fetch_ths_industry_rows(limit), "ths"


def main() -> int:
    parser = argparse.ArgumentParser(description="行业板块主力资金流向（东财 JSON 主源，同花顺 fallback）")
    parser.add_argument(
        "--limit",
        type=int,
        default=30,
        help="返回条数；0 表示返回全部行业（用于板块名匹配）",
    )
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    try:
        items, source = fetch_industry_rows(limit=args.limit)
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc), "items": []}, ensure_ascii=False))
        else:
            print(f"获取失败: {exc}", file=sys.stderr)
        return 1

    payload = {
        "ok": True,
        "source": source,
        "queried_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(items),
        "items": items,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"【行业主力资金】{payload['queried_at']}  {source}  共 {len(items)} 个")
        show_n = len(items) if args.limit <= 0 else min(len(items), args.limit)
        for r in items[:show_n]:
            sign = "+" if r["main_net_inflow_yi"] >= 0 else ""
            chg = r.get("change_pct")
            chg_s = f"{chg:+.2f}%" if chg is not None else "N/A"
            print(
                f"  {r['rank']:>3}. {r['industry']:<12} 主力净流入 {sign}{r['main_net_inflow_yi']:.2f} 亿  涨跌 {chg_s}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
