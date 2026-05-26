"""Fetch verified A-share valuation metrics before debate (no LLM guesses)."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from tradingagents.dataflows.cn_prefetch import _cache, get_prefetched
from tradingagents.market import normalize_a_share_code

_TENCENT_URL = "https://qt.gtimg.cn/q="


@dataclass
class QuoteValuation:
    code: str
    name: str
    price: float
    pe_ttm: float
    pe_annualized_q_eps: Optional[float]
    pb: Optional[float]
    as_of: str
    source: str


def _curl_quotes(codes: List[str], *, timeout: int = 20) -> str:
    import os

    env = os.environ.copy()
    for key in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    ):
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    query = ",".join(codes)
    proc = subprocess.run(
        ["curl", "-sS", f"{_TENCENT_URL}{query}"],
        capture_output=True,
        timeout=timeout,
        env=env,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or b"").decode("utf-8", errors="replace")
        raise RuntimeError(err or f"curl exit {proc.returncode}")
    stdout = proc.stdout or b""
    for enc in ("gbk", "gb18030", "utf-8"):
        try:
            return stdout.decode(enc)
        except UnicodeDecodeError:
            continue
    return stdout.decode("utf-8", errors="replace")


def _parse_tencent_line(line: str) -> Optional[Dict[str, Any]]:
    if '="' not in line or "~" not in line:
        return None
    val = line.split('="', 1)[1].rstrip('";')
    parts = val.split("~")
    if len(parts) < 48:
        return None
    try:
        price = float(parts[3])
        if price <= 0:
            return None
        pe_ttm = float(parts[39]) if parts[39] else None
        pe_ann = float(parts[52]) if len(parts) > 52 and parts[52] else None
        pb = float(parts[46]) if len(parts) > 46 and parts[46] else None
        as_of = parts[30] if len(parts) > 30 else ""
        return {
            "code": parts[2],
            "name": parts[1],
            "price": price,
            "pe_ttm": pe_ttm,
            "pe_annualized_q_eps": pe_ann,
            "pb": pb,
            "as_of": as_of,
            "source": "腾讯 qt.gtimg.cn",
        }
    except (ValueError, IndexError):
        return None


def _market_prefix(code6: str) -> str:
    return "sh" if code6.startswith(("5", "6", "9")) else "sz"


def fetch_tencent_valuations(code6_list: List[str]) -> Dict[str, Dict[str, Any]]:
    codes = [_market_prefix(c) + c for c in code6_list]
    text = _curl_quotes(codes)
    out: Dict[str, Dict[str, Any]] = {}
    for line in text.strip().splitlines():
        parsed = _parse_tencent_line(line)
        if parsed:
            out[parsed["code"]] = parsed
    return out


def _parse_events_eps(events_block: str) -> Optional[Dict[str, Any]]:
    """Extract latest quarterly EPS / profit growth from prefetch events JSON text."""
    if not events_block:
        return None
    try:
        # block may be markdown-wrapped JSON
        m = re.search(r"\{[\s\S]*\"financial_abstract\"[\s\S]*\}", events_block)
        payload = json.loads(m.group(0) if m else events_block)
    except (json.JSONDecodeError, AttributeError):
        return None
    perf = payload.get("performance") or {}
    rows = perf.get("financial_abstract") or []
    if not rows:
        return None
    row = rows[0]
    eps = row.get("基本每股收益")
    if eps is None:
        return None
    return {
        "report_period": row.get("报告期"),
        "basic_eps": float(eps),
        "net_profit_yoy_pct": None,
    }


def _fetch_events_eps(code6: str) -> Optional[Dict[str, Any]]:
    from tradingagents.dataflows.a_share_runner import run_script

    ok, raw, data = run_script(
        "fetch_stock_events.py",
        ["--code", code6, "--limit", "5", "--skip-sentiment", "--max-seconds", "40", "--json"],
        timeout=50,
    )
    if ok and isinstance(data, dict):
        rows = (data.get("performance") or {}).get("financial_abstract") or []
        if rows:
            row = rows[0]
            eps = row.get("基本每股收益")
            if eps is not None:
                return {
                    "report_period": row.get("报告期"),
                    "basic_eps": float(eps),
                }
    return _parse_events_eps(raw or "")


def _peer_codes(config: dict) -> List[str]:
    peers = config.get("cn_valuation_peers") or []
    if isinstance(peers, str):
        peers = [p.strip() for p in peers.split(",") if p.strip()]
    return [normalize_a_share_code(p) for p in peers if p]


def fetch_cn_valuation_payload(
    ticker: str,
    trade_date: str,
    config: dict,
) -> Tuple[bool, Dict[str, Any], str]:
    """
    Return (ok, structured_payload, markdown_for_agents).
    ok is False when price or pe_ttm cannot be obtained from market data.
    """
    code6 = normalize_a_share_code(ticker)
    all_codes = [code6, *_peer_codes(config)]
    try:
        quotes = fetch_tencent_valuations(all_codes)
    except Exception as exc:
        return False, {}, f"valuation fetch failed: {exc}"

    primary = quotes.get(code6)
    if not primary or not primary.get("price") or primary["price"] <= 0:
        return False, {}, f"valuation missing price for {code6}"
    pe = primary.get("pe_ttm")
    is_etf = "ETF" in (primary.get("name") or "").upper()
    if (not pe or pe <= 0) and not is_etf:
        return False, {}, f"valuation missing pe_ttm for {code6}"

    eps_info = _fetch_events_eps(code6)
    peers = {c: quotes[c] for c in all_codes if c != code6 and c in quotes}

    payload: Dict[str, Any] = {
        "ticker": code6,
        "trade_date": str(trade_date),
        "primary": primary,
        "latest_eps": eps_info,
        "peers": peers,
        "disclaimer": (
            "pe_ttm 来自腾讯行情字段（滚动市盈率）；pe_annualized_q_eps 为 Q1 基本 EPS×4 年化口径，"
            "非公告 TTM。禁止将净利润同比增速（%）当作市盈率（倍）。"
        ),
    }
    md = format_valuation_markdown(payload)
    return True, payload, md


def format_valuation_markdown(payload: Dict[str, Any]) -> str:
    p = payload["primary"]
    lines = [
        "## 行情硬数据（预取，辩论唯一估值来源）",
        "",
        f"- **标的**: {p.get('name', '')} ({payload['ticker']})",
        f"- **现价**: {p['price']:.2f} 元",
    ]
    if p.get("pe_ttm") and p["pe_ttm"] > 0:
        lines.append(f"- **动态市盈率 TTM**: **{p['pe_ttm']:.2f}×**（{p.get('source', '')}）")
    elif "ETF" in (p.get("name") or "").upper():
        lines.append("- **动态市盈率 TTM**: 不适用（ETF 无个股 PE）")
    if p.get("pe_annualized_q_eps"):
        lines.append(f"- **参考市盈率（Q1 EPS×4 年化）**: {p['pe_annualized_q_eps']:.2f}×")
    if p.get("pb"):
        lines.append(f"- **市净率 PB**: {p['pb']:.2f}×")
    if p.get("as_of"):
        lines.append(f"- **行情时间**: {p['as_of']}")
    eps = payload.get("latest_eps")
    if eps:
        lines.append(
            f"- **最近财报基本 EPS**: {eps['basic_eps']}（报告期 {eps.get('report_period', 'N/A')}）"
        )
    peers = payload.get("peers") or {}
    if peers:
        lines.append("")
        lines.append("### 同业对照（同次预取）")
        lines.append("")
        lines.append("| 代码 | 名称 | 现价 | TTM PE |")
        lines.append("|------|------|------|--------|")
        for code, q in sorted(peers.items()):
            lines.append(
                f"| {code} | {q.get('name', '')} | {q['price']:.2f} | {q.get('pe_ttm', 'N/A')}× |"
            )
    lines.append("")
    lines.append(f"*{payload.get('disclaimer', '')}*")
    return "\n".join(lines)


def fetch_and_cache_cn_valuation(
    ticker: str,
    trade_date: str,
    config: dict,
) -> Tuple[str, bool]:
    """Cache markdown + JSON; return (status_line, ok)."""
    code6 = normalize_a_share_code(ticker)
    ok, payload, md = fetch_cn_valuation_payload(ticker, trade_date, config)
    if ok:
        _cache(f"valuation:{code6}", md)
        _cache(f"valuation_json:{code6}", json.dumps(payload, ensure_ascii=False))
        pe = payload["primary"].get("pe_ttm")
        if pe and pe > 0:
            return f"ok · TTM PE {pe:.1f}×", True
        return "ok · ETF（无 PE）", True
    _cache(f"valuation:{code6}", "")
    return f"FAILED · {md[:120]}", False


def require_cn_valuation_ready(ticker: str, config: dict) -> str:
    """Return verified markdown block or raise if required and missing."""
    if not config.get("require_verified_valuation", True):
        block = get_prefetched(f"valuation:{normalize_a_share_code(ticker)}") or ""
        return block
    code6 = normalize_a_share_code(ticker)
    block = get_prefetched(f"valuation:{code6}") or ""
    if not block.strip():
        raise RuntimeError(
            f"A-share valuation prefetch failed for {code6}: "
            "debate cannot start without verified price/PE. "
            "Check a-share-data skill / network, or set require_verified_valuation=false."
        )
    return block
