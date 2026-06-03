"""Shared 5-tier rating vocabulary and a deterministic heuristic parser.

Rating semantics follow ``position_context`` in config (default ``empty`` = flat;
see ``agents.utils.position_context``). The same five-tier scale is used by:
- The Research Manager (investment plan recommendation)
- The Portfolio Manager (final position decision)
- The signal processor (rating extracted for downstream consumers)
- The memory log (rating tag stored alongside each decision entry)

Centralising it here avoids drift between those call sites.
"""

from __future__ import annotations

import re
from typing import Tuple


# Canonical, ordered 5-tier scale (most bullish to most bearish).
RATINGS_5_TIER: Tuple[str, ...] = (
    "Buy", "Overweight", "Hold", "Underweight", "Sell",
)

_RATING_SET = {r.lower() for r in RATINGS_5_TIER}

# Matches "Rating: X" / "rating - X" / "Rating: **X**" — tolerates markdown
# bold wrappers and either a colon or hyphen separator.
_RATING_LABEL_RE = re.compile(r"rating.*?[:\-][\s*]*(\w+)", re.IGNORECASE)

# Chinese-style decision labels that embed the rating word directly,
# e.g. "最终交易决策：Underweight" or "评级：Buy".
_CJK_RATING_RE = re.compile(
    r"(?:评级|决策|评分|行动)[：:]\s*", re.IGNORECASE
)

# For CJK-heavy text where split() won't isolate English rating words,
# try to match any rating word as a substring within each line.
_LINE_MATCH_CACHE: dict = {}


def _find_rating_substring(text: str) -> str | None:
    """Line-level substring match for rating words in CJK text.

    Unlike split()-based word isolation, this catches patterns like
    "最终交易决策：Underweight" where the rating is embedded in CJK
    without surrounding whitespace.
    """
    lower = text.lower()
    for r in RATINGS_5_TIER:
        if r.lower() in lower:
            return r
    return None


def parse_rating(text: str, default: str = "Hold") -> str:
    """Heuristically extract a 5-tier rating from prose text.

    Three-pass strategy:
    1. Look for an explicit "Rating: X" label (tolerant of markdown bold).
    2. On CJK-heavy text, scan the first 5 lines for rating words embedded
       in decision headers like "最终交易决策：Underweight".
    3. Fall back to the first 5-tier rating word found anywhere in the text
       (word-boundary split).

    Returns a Title-cased rating string, or ``default`` if no rating word appears.
    """
    lines = text.splitlines()

    # ------------------------------------------------------------------
    # Pass 1: explicit English "Rating: X" label
    # ------------------------------------------------------------------
    for line in lines:
        m = _RATING_LABEL_RE.search(line)
        if m and m.group(1).lower() in _RATING_SET:
            return m.group(1).capitalize()

    # ------------------------------------------------------------------
    # Pass 2: CJK decision headers in the first few lines
    # (Portfolio Manager always states the rating near the top)
    # ------------------------------------------------------------------
    for line in lines[:5]:
        found = _find_rating_substring(line)
        if found:
            return found

    # ------------------------------------------------------------------
    # Pass 3: first rating word anywhere in the text (word-level split)
    # ------------------------------------------------------------------
    for line in lines:
        for word in line.lower().split():
            clean = word.strip("*:.,")
            if clean in _RATING_SET:
                return clean.capitalize()

    return default
