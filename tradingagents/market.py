"""Market detection and ticker normalization for multi-region support."""

from __future__ import annotations

import re
from typing import Optional

# Yahoo-style A-share suffixes and bare 6-digit codes.
_CN_SUFFIXES = (".SS", ".SZ", ".SH")
_CN_BARE_RE = re.compile(r"^\d{6}$")


def normalize_a_share_code(ticker: str) -> str:
    """Return 6-digit A-share code from ``600519``, ``600519.SS``, ``sh600519``."""
    raw = (ticker or "").strip().upper()
    if raw.lower().startswith(("sh", "sz")) and len(raw) > 2:
        raw = raw[2:]
    for suffix in _CN_SUFFIXES:
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
            break
    if "." in raw:
        head = raw.split(".", 1)[0]
        if head.isdigit():
            raw = head
    if raw.isdigit() and len(raw) <= 6:
        return raw.zfill(6)
    return raw


def to_yahoo_a_share_symbol(code6: str) -> str:
    """Map 6-digit code to Yahoo ticker (``.SS`` / ``.SZ``)."""
    c = normalize_a_share_code(code6)
    if not c.isdigit() or len(c) != 6:
        return code6
    if c.startswith(("5", "6", "9")):
        return f"{c}.SS"
    return f"{c}.SZ"


def is_cn_ticker(ticker: str, *, market_profile: Optional[str] = None) -> bool:
    """True when ticker or explicit profile indicates China A-share context."""
    if market_profile and market_profile.strip().lower() in ("cn", "a", "a_share", "china"):
        return True
    if market_profile and market_profile.strip().lower() in ("us", "usa"):
        return False

    t = (ticker or "").strip().upper()
    if any(t.endswith(s) for s in _CN_SUFFIXES):
        return True
    if _CN_BARE_RE.fullmatch(t):
        return True
    if t.lower().startswith(("sh", "sz")) and len(t) >= 8:
        return True
    return False


def effective_market_profile(ticker: str, config: dict) -> str:
    """Resolve ``us`` vs ``cn`` from config and ticker."""
    profile = (config.get("market_profile") or "us").strip().lower()
    if profile in ("cn", "a", "a_share", "china"):
        return "cn"
    if profile in ("auto", ""):
        return "cn" if is_cn_ticker(ticker) else "us"
    return "us"


def cn_uses_a_share_skill(ticker: str, config: dict) -> bool:
    """True when data tools must use the a-share-data skill (``run.sh``) only."""
    if is_hk_ticker(ticker):
        return True
    return effective_market_profile(ticker, config) == "cn"


def is_hk_ticker(ticker: str) -> bool:
    """True when ticker represents a Hong Kong stock, e.g. '0700.HK'."""
    t = (ticker or "").strip().upper()
    if t.endswith(".HK"):
        return True
    if t.isdigit() and len(t) == 5:
        return True
    return False

