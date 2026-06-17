#!/usr/bin/env python3
"""雪球个股讨论流（xueqiu.com）— 供 TradingAgents A 股情绪分析使用。

接口示例::
    GET https://xueqiu.com/query/v1/symbol/search/status
        ?symbol=SH600519&count=20&page=1&sort=time

依赖：同目录 http_util（curl 优先）。可选环境变量 XUEQIU_COOKIE 增强稳定性。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from http_util import build_session, get_json  # noqa: E402

STATUS_API = "https://xueqiu.com/query/v1/symbol/search/status"
HOME_URL = "https://xueqiu.com"


def normalize_code6(code: str) -> str:
    c = (code or "").strip()
    if c.lower().startswith(("sh", "sz")):
        c = c[2:]
    if "." in c:
        parts = c.split(".")
        if parts[0].isdigit():
            c = parts[0]
        elif parts[-1].isdigit():
            c = parts[-1]
    if c.isdigit() and len(c) <= 6:
        return c.zfill(6)
    return c


def to_xueqiu_symbol(code: str) -> Optional[str]:
    code6 = normalize_code6(code)
    if not code6.isdigit() or len(code6) != 6:
        return None
    if code6.startswith(("5", "6", "9")):
        return f"SH{code6}"
    return f"SZ{code6}"


def _cookie_header() -> Dict[str, str]:
    raw = (os.environ.get("XUEQIU_COOKIE") or "").strip()
    if not raw:
        return {}
    return {"Cookie": raw}


def _bootstrap_session():
    session = build_session()
    headers = {"Referer": HOME_URL, "Accept": "application/json, text/plain, */*"}
    headers.update(_cookie_header())
    try:
        session.get(HOME_URL, headers=headers, timeout=8)
    except Exception:
        pass
    return session, headers


def fetch_statuses(
    code: str,
    *,
    page: int = 1,
    size: int = 20,
    timeout: int = 12,
) -> Dict[str, Any]:
    symbol = to_xueqiu_symbol(code)
    if not symbol:
        return {
            "ok": False,
            "error": f"invalid A-share code: {code!r}",
            "symbol": None,
            "posts": [],
        }

    params = {
        "symbol": symbol,
        "count": max(1, min(int(size), 50)),
        "page": max(1, int(page)),
        "sort": "time",
    }
    referer = f"https://xueqiu.com/S/{symbol}"
    headers = {
        "Referer": referer,
        "Accept": "application/json, text/plain, */*",
    }
    headers.update(_cookie_header())

    session, boot_headers = _bootstrap_session()
    try:
        session.get(HOME_URL, headers=boot_headers, timeout=8)
        resp = session.get(STATUS_API, params=params, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return {
                "ok": False,
                "error": f"HTTP {resp.status_code}",
                "symbol": symbol,
                "posts": [],
            }
        payload = resp.json()
    except Exception as exc:
        try:
            payload = get_json(STATUS_API, params=params, timeout=timeout, headers=headers)
        except Exception as exc2:
            return {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}; fallback: {exc2}",
                "symbol": symbol,
                "posts": [],
            }

    posts = _parse_posts(payload)
    return {
        "ok": bool(posts),
        "symbol": symbol,
        "url": referer,
        "queried_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "page": page,
        "size": size,
        "count": len(posts),
        "posts": posts,
        "raw_error": None if posts else "empty or unparsed response",
    }


def _parse_posts(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []

    candidates: List[Any] = []
    for key in ("list", "statuses", "items", "data"):
        val = payload.get(key)
        if isinstance(val, list):
            candidates = val
            break
        if isinstance(val, dict):
            for sub in ("list", "items", "statuses"):
                inner = val.get(sub)
                if isinstance(inner, list):
                    candidates = inner
                    break
            if candidates:
                break

    posts: List[Dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        text = (
            item.get("description")
            or item.get("text")
            or item.get("title")
            or ""
        )
        text = re.sub(r"<[^>]+>", "", str(text)).replace("\n", " ").strip()
        if not text:
            continue

        created = item.get("created_at") or item.get("time") or item.get("created")
        created_str = _format_ts(created)

        user_obj = item.get("user") or {}
        user = (
            user_obj.get("screen_name")
            or user_obj.get("name")
            or item.get("user_name")
            or "?"
        )

        posts.append({
            "time": created_str,
            "user": str(user),
            "text": text[:500],
            "reply_count": item.get("reply_count") or item.get("comment_count") or 0,
            "like_count": item.get("like_count") or item.get("fav_count") or 0,
            "retweet_count": item.get("retweet_count") or 0,
        })
    return posts


def _format_ts(value: Any) -> str:
    if value is None:
        return ""
    try:
        ts = int(value)
        if ts > 1_000_000_000_000:
            ts //= 1000
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return str(value)


def format_prompt_block(payload: Dict[str, Any]) -> str:
    """Plaintext block for LLM prompt injection."""
    if not payload.get("ok"):
        err = payload.get("error") or payload.get("raw_error") or "unknown"
        sym = payload.get("symbol") or "?"
        return f"<xueqiu unavailable for {sym}: {err}>"

    symbol = payload.get("symbol", "")
    url = payload.get("url", f"https://xueqiu.com/S/{symbol}")
    posts = payload.get("posts") or []
    if not posts:
        return f"<no Xueqiu posts found for {symbol}>"

    lines = [
        f"Symbol: {symbol} · Source: 雪球 xueqiu.com · Page: {payload.get('page', 1)}",
        f"URL: {url}",
        f"Posts: {len(posts)} (most recent first)",
        "",
    ]
    for i, p in enumerate(posts, 1):
        lines.append(
            f"{i}. [{p.get('time', '')} · @{p.get('user', '?')} · "
            f"👍{p.get('like_count', 0)} 💬{p.get('reply_count', 0)}] "
            f"{p.get('text', '')}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="雪球个股讨论帖（status 流）")
    parser.add_argument("--code", required=True, help="A股代码，如 600519 / 600519.SS")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--size", type=int, default=20, help="每页条数，最大 50")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    parser.add_argument("--json", action="store_true", dest="force_json", help="同 --format json")
    args = parser.parse_args()

    out_fmt = "json" if args.force_json else args.format
    payload = fetch_statuses(args.code, page=args.page, size=args.size)

    if out_fmt == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_prompt_block(payload))


if __name__ == "__main__":
    main()
