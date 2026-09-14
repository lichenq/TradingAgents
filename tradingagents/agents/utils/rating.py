"""Shared 5-tier rating vocabulary and a deterministic heuristic parser.

Rating semantics follow ``position_context`` in config (default ``empty`` = flat;
see ``agents.utils.position_context``). The same five-tier scale is used by:
- The Research Manager (investment plan recommendation)
- The Portfolio Manager (final position decision)
- The signal processor (rating extracted for downstream consumers)
- The memory log (rating tag stored alongside each decision entry)

Centralising it here avoids drift between those call sites.

``extract_rating`` returns ``None`` when no rating can be found, so the graph can
surface an explicit ``REVIEW`` signal instead of a fabricated ``Hold`` (#1170).
``parse_rating`` keeps the legacy silent-default behaviour for callers (e.g. the
memory log) that need a rating string regardless.
"""

from __future__ import annotations

import re
import unicodedata

# Canonical, ordered 5-tier scale (most bullish to most bearish).
RATINGS_5_TIER: tuple[str, ...] = (
    "Buy", "Overweight", "Hold", "Underweight", "Sell",
)

# Signal emitted when the model's decision has no recognizable rating. It is not
# a tradeable position: it flags output that needs a human/re-run rather than
# silently degrading to Hold. Callers that map the signal onto the 5-tier enum
# (e.g. ``PortfolioRating(signal)``) should guard with ``is_review`` first.
RATING_REVIEW = "REVIEW"

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

# A line counts as CJK (and thus eligible for substring matching) only when it
# actually contains CJK characters; otherwise English prose like "The buyer
# was holding shares." would match "buy" inside "buyer".
_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")


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


# Standalone 5-tier word anywhere (word boundaries so "Buyer"/"Holding" don't match).
_RATING_WORD_RE = re.compile(
    r"\b(" + "|".join(RATINGS_5_TIER) + r")\b", re.IGNORECASE
)


def extract_rating(text: str) -> str | None:
    """Extract a 5-tier rating from prose, or ``None`` if none is present.

    Three-pass strategy on the NFKC-normalized text (so fullwidth punctuation like
    ``Rating：Overweight`` is matched the same as ASCII):
    1. An explicit "Rating: X" label (tolerant of markdown bold).
    2. On CJK-heavy text, scan the first 5 lines for rating words embedded
       in decision headers like "最终交易决策：Underweight".
    3. The first standalone 5-tier rating word found anywhere.
    """
    if not text:
        return None
    norm = unicodedata.normalize("NFKC", text)
    lines = norm.splitlines()

    # Pass 1: explicit English "Rating: X" label
    for line in lines:
        m = _RATING_LABEL_RE.search(line)
        if m and m.group(1).lower() in _RATING_SET:
            return m.group(1).capitalize()

    # Pass 2: CJK decision headers in the first few lines
    # (Portfolio Manager always states the rating near the top)
    for line in lines[:5]:
        if not _CJK_CHAR_RE.search(line):
            continue
        found = _find_rating_substring(line)
        if found:
            return found

    # Pass 3: first standalone rating word anywhere in the text
    m = _RATING_WORD_RE.search(norm)
    if m:
        return m.group(1).capitalize()

    return None


def parse_rating(text: str, default: str = "Hold") -> str:
    """Extract a 5-tier rating, falling back to ``default`` when none is found.

    Legacy convenience wrapper: it always returns a rating string, so an
    unparseable decision silently becomes ``default`` (``Hold``). Callers that
    must distinguish "no rating" from a real Hold should use
    :func:`extract_rating` (or the graph's REVIEW-surfacing signal) instead.
    """
    rating = extract_rating(text)
    return rating if rating is not None else default


def is_review(signal: str) -> bool:
    """Whether a signal is the non-tradeable REVIEW sentinel (#1170)."""
    return signal == RATING_REVIEW
