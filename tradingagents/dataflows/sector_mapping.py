"""Runtime sector-mapping lookup — single source of truth for cross-source name alignment.

Loads ``sector_mapping.yaml`` once and provides O(1) lookups by canonical name
or by any known alias (东财行业, 东财概念, DangInvest board).

Usage::

    from tradingagents.dataflows.sector_mapping import SectorMapping

    # Normalize any name to its canonical form
    canonical = SectorMapping.resolve("券商信托")       # → "证券"
    canonical = SectorMapping.resolve("人形机器人")      # → "人形机器人"

    # Get search keywords for news filtering
    keywords = SectorMapping.get_search_keywords("半导体")
    # → ["半导体", "芯片", "集成电路", "国产芯片 自主可控"]

    # Get DangInvest board name(s) for fund-flow / boards-summary lookups
    boards = SectorMapping.get_danginvest_boards("电气设备")
    # → ["电气设备"]

    # Get search keywords for raw query list expansion
    expanded = SectorMapping.expand_queries(["A股 半导体 板块 政策", "A股 银行 板块"])
    # → ["A股 半导体 板块 政策", "A股 芯片 板块 政策", ..., "A股 银行 板块"]
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Set

import yaml

_MAPPING_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "sector_mapping.yaml"
)

# ── Internal lookup structures (lazily built) ──────────────────────────
_RAW: List[dict] | None = None                        # raw parsed YAML rows
_BY_CANONICAL: Dict[str, dict] = {}                   # canonical → row
_BY_ALIAS: Dict[str, str] = {}                        # any known name → canonical
_KEYWORDS_CACHE: Dict[str, List[str]] = {}            # canonical → keywords


def _build() -> None:
    """Parse YAML once and populate index maps."""
    global _RAW, _BY_CANONICAL, _BY_ALIAS, _KEYWORDS_CACHE
    if _RAW is not None:
        return

    path = _MAPPING_PATH
    if not os.path.isfile(path):
        _RAW = []
        return

    with open(path, "r", encoding="utf-8") as f:
        _RAW = yaml.safe_load(f) or []

    for row in _RAW:
        canonical = (row.get("canonical") or "").strip()
        if not canonical:
            continue
        _BY_CANONICAL[canonical] = row

        # Index from every alias in source mappings
        src = row.get("source") or {}
        for key in ("eastmoney_industry", "eastmoney_concept", "danginvest_board"):
            names = src.get(key) or []
            if isinstance(names, str):
                names = [names]
            for name in names:
                name = name.strip()
                if name:
                    _BY_ALIAS[name] = canonical

        # Self-referential alias (the canonical name itself)
        _BY_ALIAS[canonical] = canonical

        # Precompute keyword list
        kw = row.get("search_keywords") or []
        _KEYWORDS_CACHE[canonical] = [k.strip() for k in kw if k.strip()]

    # Build reverse alias: DangInvest board → canonical
    # (needed when we have a DangInvest groupLabel and want canonical)
    for row in _RAW:
        src = row.get("source") or {}
        for board_name in (src.get("danginvest_board") or []):
            if board_name.strip():
                _BY_ALIAS[board_name.strip()] = row["canonical"]


def ensure_loaded() -> None:
    """Forcibly load the mapping (idempotent). Called automatically by all public APIs."""
    _build()


# ── Public API ─────────────────────────────────────────────────────────


def resolve(name: str) -> str:
    """Map any known sector/industry/concept name to its **canonical** form.

    Args:
        name: A sector name from any source (东财行业, 概念, DangInvest, or canonical).

    Returns:
        The canonical name if found, or the original ``name`` unchanged.
    """
    _build()
    name = (name or "").strip()
    if not name:
        return ""
    return _BY_ALIAS.get(name, name)


def resolve_or_none(name: str) -> Optional[str]:
    """Like :func:`resolve` but returns ``None`` when no mapping exists."""
    _build()
    name = (name or "").strip()
    if not name:
        return None
    return _BY_ALIAS.get(name)


def get_canonical_for_danginvest(board_name: str) -> Optional[str]:
    """Return canonical sector name for a DangInvest ``groupLabel``."""
    _build()
    name = (board_name or "").strip()
    return _BY_ALIAS.get(name)


def get_search_keywords(canonical: str) -> List[str]:
    """Return the search keyword list for a canonical sector name.

    Falls back to ``[canonical]`` if unknown.
    """
    _build()
    canonical = resolve(canonical)
    return _KEYWORDS_CACHE.get(canonical, [canonical])


def get_danginvest_boards(canonical: str) -> List[str]:
    """Return DangInvest board name(s) for a canonical sector."""
    _build()
    canonical = resolve(canonical)
    row = _BY_CANONICAL.get(canonical)
    if not row:
        return [canonical]
    src = row.get("source") or {}
    boards = src.get("danginvest_board") or []
    if isinstance(boards, str):
        return [boards]
    return boards if boards else [canonical]


def get_eastmoney_industries(canonical: str) -> List[str]:
    """Return EastMoney 行业 names for a canonical sector."""
    _build()
    canonical = resolve(canonical)
    row = _BY_CANONICAL.get(canonical)
    if not row:
        return [canonical]
    src = row.get("source") or {}
    inds = src.get("eastmoney_industry") or []
    return inds if isinstance(inds, list) else [inds]


def get_eastmoney_concepts(canonical: str) -> List[str]:
    """Return EastMoney 概念板块 names for a canonical sector."""
    _build()
    canonical = resolve(canonical)
    row = _BY_CANONICAL.get(canonical)
    if not row:
        return []
    src = row.get("source") or {}
    concepts = src.get("eastmoney_concept") or []
    return concepts if isinstance(concepts, list) else [concepts]


def all_canonical_names() -> List[str]:
    """Return every canonical sector name in the mapping."""
    _build()
    return list(_BY_CANONICAL.keys())


def expand_queries(queries: List[str]) -> List[str]:
    """Expand a raw query list by replacing known sector names with all synonyms.

    For each query that contains a known sector name, generate additional queries
    that substitute related alias terms.

    Example::

        expand_queries(["A股 半导体 板块 政策"])
        # → ["A股 半导体 板块 政策", "A股 芯片 板块 政策",
        #     "A股 集成电路 板块 政策", ...]
    """
    _build()
    seen: Set[str] = set()
    expanded: List[str] = []

    # Build a reverse map: canonical → set of all known names (for substitution)
    canon_to_names: Dict[str, Set[str]] = {}
    for row in _RAW or []:
        c = (row.get("canonical") or "").strip()
        if not c:
            continue
        names: Set[str] = {c}
        src = row.get("source") or {}
        for key in ("eastmoney_industry", "eastmoney_concept", "danginvest_board"):
            for n in (src.get(key) or []):
                if n.strip():
                    names.add(n.strip())
        for kw in (row.get("search_keywords") or []):
            kw_s = kw.strip()
            if kw_s and len(kw_s) <= 8:
                names.add(kw_s)
        canon_to_names[c] = names

    for q in queries:
        q = (q or "").strip()
        if not q or q in seen:
            continue
        seen.add(q)
        expanded.append(q)

        # Try to find a known canonical name inside this query
        for canon, synonyms in canon_to_names.items():
            # Check if any synonym appears in the query
            found = None
            for s in sorted(synonyms, key=len, reverse=True):
                if s and s in q:
                    found = s
                    break
            if not found:
                continue
            # Generate alternative queries substituting other synonyms
            for alt in synonyms:
                if alt == found or not alt:
                    continue
                new_q = q.replace(found, alt, 1)
                if new_q not in seen:
                    seen.add(new_q)
                    expanded.append(new_q)
                    if len(expanded) >= 50:  # safety cap
                        break
            break  # one sector per query is enough

    return expanded
