"""Runtime functional-peer discovery (Serenity-style theme + segment mapping)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from tradingagents.dataflows.sector_mapping import (
    get_danginvest_boards,
    resolve,
    resolve_or_none,
)
from tradingagents.market import normalize_a_share_code

logger = logging.getLogger(__name__)

# 宽基/指数类概念，不宜作为功能同业来源
_GENERIC_CONCEPTS = frozenset({
    "沪股通", "深股通", "融资融券", "转融券标的", "MSCI概念", "MSCI中国",
    "标普道琼斯A股", "富时罗素", "证金持股", "国企改革", "央企国企改革",
    "深成500", "中证500", "沪深300", "创业板综", "深证成指", "上证180",
    "上证380", "AH股", "H股", "B股", "ST板块", "参股券商", "参股银行",
    "参股保险", "参股新三板", "一带一路", "西部大开发", "乡村振兴",
    "预盈预增", "预亏预减", "高送转", "股权转让", "资产重组",
})

# 环节关键词 → 展示标签（按优先级匹配）
_SEGMENT_RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("谐波减速器", ("谐波", "减速器")),
    ("RV减速器", ("RV减速", "RV 减速")),
    ("行星滚柱丝杠", ("滚柱丝杠", "行星滚柱", "滚珠丝杠")),
    ("直线执行器", ("直线执行", "线性执行")),
    ("灵巧手", ("灵巧手", "末端执行器")),
    ("先进封装", ("先进封装", "Chiplet", "2.5D", "3D封装", "封装测试")),
    ("封测", ("封测", "封装测试", "集成电路封测")),
    ("半导体设备", ("半导体设备", "刻蚀", "薄膜沉积", "光刻")),
    ("晶圆代工", ("晶圆代工", "代工")),
    ("AI芯片设计", ("AI芯片", "GPU", "NPU", "芯片设计")),
)

_BROAD_CONCEPTS = frozenset({
    "机器人", "人工智能", "数字经济", "物联网", "工业互联网", "国产芯片",
    "芯片概念", "半导体", "专精特新", "高端装备",
})


def _fetch_sector_with_concepts(ticker: str, *, timeout: int = 20) -> Optional[Dict[str, Any]]:
    from tradingagents.dataflows.a_share_runner import run_script

    code6 = normalize_a_share_code(ticker)
    ok, _raw, data = run_script(
        "fetch_sector_info.py",
        ["--json", code6],
        timeout=timeout,
    )
    if not ok or not isinstance(data, dict):
        return None
    if "results" in data and isinstance(data["results"], list) and data["results"]:
        first = data["results"][0]
        return first if isinstance(first, dict) else None
    if "industry" in data or "name" in data or "concepts" in data:
        return data
    return None


def _score_concept(concept: str, industry: str) -> float:
    concept = (concept or "").strip()
    if not concept or concept in _GENERIC_CONCEPTS:
        return -1.0
    score = 5.0
    if resolve_or_none(concept):
        score += 4.0
    if concept in _BROAD_CONCEPTS:
        score -= 2.0
    # 更具体的概念优先（但不过度奖励超长名称）
    score += min(len(concept), 12) * 0.15
    if industry and concept in industry:
        score += 1.0
    return score


def pick_theme_concept(
    concepts: List[str],
    industry: str = "",
) -> Tuple[Optional[str], Optional[str]]:
    """Return (best_concept, canonical_theme) or (None, None)."""
    scored: List[Tuple[float, str]] = []
    for c in concepts or []:
        s = _score_concept(c, industry)
        if s >= 0:
            scored.append((s, c))
    if not scored:
        return None, None
    scored.sort(key=lambda x: (-x[0], x[1]))
    best = scored[0][1]
    canonical = resolve_or_none(best) or resolve(industry) or best
    return best, canonical


def infer_functional_segment(
    *,
    industry: str = "",
    concepts: Optional[List[str]] = None,
    canonical_theme: str = "",
) -> str:
    blob = " ".join(filter(None, [industry, canonical_theme, *(concepts or [])]))
    for label, keys in _SEGMENT_RULES:
        for k in keys:
            if k in blob:
                return label
    if industry:
        return industry
    if canonical_theme:
        return canonical_theme
    return "未分类"


def _fetch_board_constituents(group_key: str, *, limit: int = 12) -> List[str]:
    from tradingagents.dataflows.a_share_runner import run_script

    if not group_key:
        return []
    ok, _raw, board_detail = run_script(
        "fetch_realtime.py",
        [
            "--boards-detail",
            "--boards-group-key",
            group_key,
            "--boards-items-limit",
            str(max(limit, 15)),
            "--json",
        ],
        timeout=25,
    )
    if not ok or not isinstance(board_detail, dict):
        return []

    items = (board_detail.get("data") or {}).get("items") or []
    codes: List[str] = []
    for item in items:
        code = item.get("code") or ""
        code6 = "".join(ch for ch in code if ch.isdigit())[-6:]
        if code6 and len(code6) == 6:
            codes.append(code6)
    return codes


def _board_keys_for_theme(canonical: str, concept: str, industry: str) -> List[str]:
    keys: List[str] = []
    for src in (canonical, concept, industry):
        src = (src or "").strip()
        if not src:
            continue
        boards = get_danginvest_boards(src)
        if boards:
            keys.extend(boards)
        elif src not in keys:
            keys.append(src)
    # dedupe preserve order
    seen: set[str] = set()
    out: List[str] = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def discover_functional_peers(
    ticker: str,
    *,
    limit: int = 4,
) -> Tuple[List[str], Dict[str, Any]]:
    """
    Discover functional peer codes + association metadata for verified_market_facts.

    Priority: concept-board constituents → industry-board constituents.
    """
    my_code6 = normalize_a_share_code(ticker)
    sector = _fetch_sector_with_concepts(ticker) or {}
    industry = (sector.get("industry") or "").strip()
    name = (sector.get("name") or "").strip()
    concepts = [c.strip() for c in (sector.get("concepts") or []) if c and c.strip()]

    best_concept, canonical = pick_theme_concept(concepts, industry)
    segment = infer_functional_segment(
        industry=industry,
        concepts=concepts,
        canonical_theme=canonical or "",
    )

    concept_peers: List[str] = []
    industry_peers: List[str] = []
    peer_source = ""

    if best_concept or canonical:
        for key in _board_keys_for_theme(canonical or "", best_concept or "", ""):
            concept_peers = _fetch_board_constituents(key, limit=limit + 2)
            if concept_peers:
                peer_source = f"concept:{best_concept or key}"
                break

    if industry:
        resolved = resolve(industry)
        for key in _board_keys_for_theme(resolved, "", industry):
            industry_peers = _fetch_board_constituents(key, limit=limit + 2)
            if industry_peers:
                if not peer_source:
                    peer_source = f"industry:{industry}"
                break

    merged: List[str] = []
    seen: set[str] = {my_code6}
    for code in concept_peers + industry_peers:
        if code not in seen:
            seen.add(code)
            merged.append(code)
        if len(merged) >= limit:
            break

    association: Dict[str, Any] = {
        "name": name,
        "industry": industry,
        "theme": canonical or industry or "",
        "best_concept": best_concept or "",
        "segment": segment,
        "peer_source": peer_source,
        "concept_peers": [c for c in concept_peers if c != my_code6][:limit],
        "industry_peers": [c for c in industry_peers if c != my_code6][:limit],
        "all_concepts": concepts[:15],
    }
    return merged, association


def format_association_markdown(association: Dict[str, Any]) -> str:
    if not association:
        return ""
    lines = [
        "### 动态关联（Serenity 预取，辩论引用功能同业须以此为准）",
        "",
    ]
    theme = association.get("theme") or ""
    segment = association.get("segment") or ""
    if theme:
        lines.append(f"- **主题**: {theme}")
    if segment:
        lines.append(f"- **功能环节**: {segment}")
    src = association.get("peer_source") or ""
    if src:
        lines.append(f"- **同业来源**: {src}")
    best = association.get("best_concept") or ""
    if best:
        lines.append(f"- **锚定概念**: {best}")

    cp = association.get("concept_peers") or []
    ip = association.get("industry_peers") or []
    if cp:
        lines.append(f"- **同概念成分股（功能同业候选）**: {', '.join(cp)}")
    if ip and ip != cp:
        lines.append(f"- **同行业成分股（弱可比）**: {', '.join(ip)}")

    lines.extend([
        "",
        "**可比性纪律**：",
        "- 同业对照表仅含同概念/同板块成分股；辩论中引用表外标的对标须说明商业模式可比性，否则 PM 应降权。",
        "- 禁止将 Fabless/晶圆代工/设备商与封测/零部件/材料商直接比 PE 得出「估值洼地」。",
        "- 市占率、核心客户供货须 L1/L2 证据；L3/L4 仅作观察，不得支撑 Buy/Overweight。",
        "- 「卡脖子」逻辑须证明高替代成本；否则不得作为估值溢价主因。",
    ])
    return "\n".join(lines)
