#!/usr/bin/env python3
"""Map market news headlines to canonical sectors (prediction layer)."""
from __future__ import annotations

import os
import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from tradingagents.dataflows.sector_mapping import (
    all_canonical_names,
    get_match_names,
    get_search_keywords,
)

# 全文丢弃的泛词（不入索引）
STOP_KEYWORDS = frozenset({
    "板块", "行业", "政策", "龙头", "业绩", "估值", "景气", "公司", "股份", "集团",
    "市场", "投资", "发展", "中国", "经济", "增长", "数据", "技术", "产业",
    "服务", "设备", "科技", "智能", "金融", "材料",
})

# 仅出现在正文时视为噪音（标题命中仍有效）
WEAK_IN_CONTENT = frozenset({
    "银行", "证券", "保险", "基金", "通信", "汽车", "能源", "金属", "化工",
    "医疗", "医药", "食品", "消费", "地产", "建筑", "机械", "电子", "电力",
    "钢铁", "煤炭", "农业", "养殖", "物流", "传媒", "教育", "软件", "互联网",
    "制造", "工业", "商业", "贸易", "运输", "旅游", "酒店", "零售", "家居",
})

# 短词但允许在正文匹配
STRONG_SHORT = frozenset({
    "AI", "5G", "芯片", "电池", "锂电", "光伏", "军工", "稀土", "钨", "锂",
    "铜", "金", "银", "油", "煤", "钢", "铝", "镍", "钴",
})

NEWS_LIMIT = int(os.environ.get("PREMARKET_NEWS_LIMIT", "40"))
MAX_PREDICTED = int(os.environ.get("PREMARKET_NEWS_TOP", "5"))
MAX_SECTORS_PER_ARTICLE = int(os.environ.get("PREMARKET_NEWS_MAX_SECTORS_PER_ARTICLE", "2"))
MIN_CONTENT_KEYWORD_LEN = int(os.environ.get("PREMARKET_NEWS_MIN_CONTENT_KW", "3"))
MAX_HEADLINE_LEN = 36


def _item_blob(item: dict[str, Any]) -> str:
    title = item.get("title") or ""
    content = item.get("content") or ""
    return f"{title} {content}"


def _headline(item: dict[str, Any]) -> str:
    title = (item.get("title") or "").strip()
    if title:
        return title
    content = (item.get("content") or "").strip()
    content = re.sub(r"^【.*?】", "", content).strip()
    if len(content) > MAX_HEADLINE_LEN:
        return content[:MAX_HEADLINE_LEN] + "…"
    return content


def _keyword_matches(kw: str, title: str, content: str) -> bool:
    """Title hits are trusted; content-only hits need stronger keywords."""
    if not kw:
        return False
    in_title = kw in title
    in_content = kw in content
    if in_title:
        return True
    if not in_content:
        return False
    if kw in WEAK_IN_CONTENT:
        return False
    if kw in STRONG_SHORT:
        return True
    if len(kw) < MIN_CONTENT_KEYWORD_LEN:
        return False
    return True


def _sector_keywords() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for canon in all_canonical_names():
        kws: set[str] = set()
        for kw in get_search_keywords(canon):
            kw = (kw or "").strip()
            if len(kw) >= 2 and kw not in STOP_KEYWORDS:
                kws.add(kw)
        for alias in get_match_names(canon):
            alias = (alias or "").strip()
            if len(alias) >= 2 and alias not in STOP_KEYWORDS:
                kws.add(alias)
        if kws:
            out[canon] = sorted(kws, key=len, reverse=True)
    return out


def match_news_to_sectors(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    keywords = _sector_keywords()
    hits: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_article: dict[str, set[int]] = defaultdict(set)

    for item in items:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        content = (item.get("content") or "").strip()
        if not title and not content:
            continue
        article_id = item.get("id")
        pub = item.get("published_at") or ""
        headline = _headline(item)

        article_matches: list[tuple[str, str, bool, int]] = []
        for canon, kws in keywords.items():
            matched_kw = None
            in_title = False
            for kw in kws:
                if _keyword_matches(kw, title, content):
                    matched_kw = kw
                    in_title = kw in title
                    break
            if matched_kw:
                article_matches.append((canon, matched_kw, in_title, len(matched_kw)))

        article_matches.sort(key=lambda x: (x[2], x[3]), reverse=True)
        for canon, matched_kw, in_title, _ in article_matches[:MAX_SECTORS_PER_ARTICLE]:
            if article_id is not None and article_id in seen_article[canon]:
                continue
            if article_id is not None:
                seen_article[canon].add(article_id)
            hits[canon].append({
                "keyword": matched_kw,
                "headline": headline,
                "published_at": pub,
                "in_title": in_title,
            })
    return hits


def rank_predicted_sectors(hits: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for canon, articles in hits.items():
        if not articles:
            continue
        title_hits = sum(1 for a in articles if a.get("in_title"))
        score = len(articles) + title_hits * 0.5
        ranked.append({
            "industry": canon,
            "score": round(score, 1),
            "article_count": len(articles),
            "title_hits": title_hits,
            "top_keyword": articles[0].get("keyword"),
            "headlines": [a.get("headline", "") for a in articles[:2]],
        })
    ranked.sort(
        key=lambda x: (x["score"], x["article_count"], max(len(h) for h in x["headlines"])),
        reverse=True,
    )
    return ranked[:MAX_PREDICTED]


def ahead_of_fund_flow(
    predicted: list[dict[str, Any]],
    fund_flow_top: list[str],
    *,
    top_n: int = 8,
) -> list[str]:
    flow_set = set(fund_flow_top[:top_n])
    return [p["industry"] for p in predicted if p["industry"] not in flow_set]


def build_watch_if(predicted: list[dict[str, Any]], ahead: list[str]) -> str:
    if not predicted:
        return ""
    names = "/".join(p["industry"] for p in predicted[:3])
    if ahead:
        return f"新闻催化→优先观察{'/'.join(ahead[:3])}，待9:35资金确认"
    return f"新闻催化→关注{names}，与当前资金流方向一致"


def build_news_catalyst(
    items: list[dict[str, Any]],
    *,
    fund_flow_industries: list[str] | None = None,
) -> dict[str, Any]:
    hits = match_news_to_sectors(items)
    predicted = rank_predicted_sectors(hits)
    flow = fund_flow_industries or []
    ahead = ahead_of_fund_flow(predicted, flow)
    return {
        "ok": True,
        "news_scan_count": len(items),
        "predicted_sectors": predicted,
        "ahead_of_fund_flow": ahead,
        "watch_if": build_watch_if(predicted, ahead),
    }


def catalyst_confirmed(
    prev_catalyst: dict[str, Any] | None,
    delta: dict[str, Any],
) -> list[str]:
    if not prev_catalyst:
        return []
    predicted = {
        p.get("industry")
        for p in (prev_catalyst.get("predicted_sectors") or [])
        if p.get("industry")
    }
    if not predicted:
        return []
    confirmed: list[str] = []
    for x in delta.get("rank_up") or []:
        ind = x.get("industry")
        if ind in predicted and ind not in confirmed:
            confirmed.append(ind)
    for ind in delta.get("new_in_top") or []:
        if ind in predicted and ind not in confirmed:
            confirmed.append(ind)
    return confirmed
