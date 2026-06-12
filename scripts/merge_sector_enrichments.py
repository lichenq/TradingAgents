#!/usr/bin/env python3
"""
Merge auto-generated sector mapping with rich manual enrichment.

Preserves all DangInvest→EastMoney links from build_sector_mapping.py while
adding EastMoney concepts, better search keywords, special themes (AI/robots),
and legacy alias mappings.
"""
import json, os, sys
import yaml

MAPPING_PATH = os.path.join(
    os.path.dirname(__file__), "..", "tradingagents", "data", "sector_mapping.yaml",
)

# ── Cross-reference aliases ─────────────────────────────────────
# Ensures old hardcoded names resolve correctly after auto-generation.
LEGACY_ALIASES = {
    # em_industry    → canonical
    "券商信托": ("eastmoney_industry", "证券"),
    "通讯行业": ("eastmoney_industry", "通信设备"),
    "通信行业": ("eastmoney_industry", "通信设备"),
    "电机": ("eastmoney_industry", "电气设备"),
    "航天航空": ("eastmoney_industry", "航空"),
    "材料行业": ("eastmoney_industry", "化工行业"),
    "材料": ("eastmoney_industry", "化工行业"),
    "机械设备": ("eastmoney_industry", "专用设备"),
    "消费电子": ("eastmoney_concept", "电子元件"),
    "白酒": ("eastmoney_concept", "酿酒行业"),
    "航天": ("eastmoney_concept", "航空"),
    "军工装备": ("eastmoney_industry", "航空"),
    "航空装备": ("eastmoney_industry", "航空"),
    "工业金属": ("eastmoney_industry", "有色金属"),
    "元件": ("eastmoney_industry", "电子元件"),
    "电池": ("eastmoney_industry", "电池"),
    "IT服务": ("eastmoney_industry", "软件服务"),
    "电网设备": ("eastmoney_industry", "电气设备"),
    "电力": ("eastmoney_industry", "电力行业"),
}

# ── Enrichments ─────────────────────────────────────────────────
RICH = {
    "银行": {
        "eastmoney_concept": ["银行"],
        "keywords": ["银行", "银行股", "商业银行"],
    },
    "证券": {
        "eastmoney_concept": [],
        "keywords": ["证券 板块", "券商", "券商股"],
    },
    "通信设备": {
        "eastmoney_concept": ["5G", "6G", "光通信", "卫星通信"],
        "keywords": ["通信设备", "5G 板块", "光通信"],
    },
    "电子元件": {
        "eastmoney_concept": ["消费电子", "电子元件", "被动元件"],
        "keywords": ["元器件", "消费电子", "电子元件"],
    },
    "电气设备": {
        "eastmoney_concept": ["特高压", "智能电网", "充电桩"],
        "keywords": ["电气设备", "电机", "特高压", "智能电网"],
    },
    "航空": {
        "eastmoney_concept": ["航天", "航空航天", "大飞机", "军工"],
        "keywords": ["航空", "航天", "大飞机", "军工 航空"],
    },
    "化工原料": {
        "eastmoney_concept": ["化工", "新材料", "氟化工"],
        "keywords": ["化工", "化工原料", "新材料"],
    },
    "化工行业": {
        "eastmoney_concept": ["化工", "新材料", "氟化工"],
        "keywords": ["化工", "化工原料", "新材料"],
    },
    "半导体": {
        "eastmoney_concept": ["半导体", "国产芯片", "AI芯片", "芯片", "集成电路"],
        "keywords": ["半导体", "芯片", "集成电路", "国产芯片 自主可控"],
    },
    "软件服务": {
        "eastmoney_concept": ["软件服务", "信创"],
        "keywords": ["软件", "软件服务", "信创"],
    },
    "医疗保健": {
        "eastmoney_concept": ["医疗器械", "医疗"],
        "keywords": ["医疗", "医疗器械", "医疗保健"],
    },
    "化学制药": {
        "eastmoney_concept": ["化学制药", "创新药"],
        "keywords": ["化学制药", "创新药"],
    },
    "家用电器": {
        "eastmoney_concept": ["家用电器", "智能家居"],
        "keywords": ["家用电器", "家电", "智能家居"],
    },
    "生物制药": {
        "eastmoney_concept": ["生物医药", "生物疫苗"],
        "keywords": ["生物制药", "生物医药", "疫苗"],
    },
    "互联网": {
        "eastmoney_concept": ["互联网", "数字经济"],
        "keywords": ["互联网", "数字经济"],
    },
    "农药化肥": {
        "eastmoney_concept": ["农药", "化肥"],
        "keywords": ["农药", "化肥", "农药化肥"],
    },
    "环境保护": {
        "eastmoney_concept": ["环保", "碳中和", "污水处理"],
        "keywords": ["环保", "环境保护", "碳中和"],
    },
    "食品饮料": {
        "eastmoney_concept": ["食品", "预制菜"],
        "keywords": ["食品", "食品饮料", "预制菜"],
    },
    "建筑工程": {
        "eastmoney_concept": ["基建", "一带一路"],
        "keywords": ["建筑工程", "基建", "工程建设"],
    },
    "酿酒行业": {
        "eastmoney_concept": ["白酒"],
        "keywords": ["白酒", "白酒板块", "高端白酒"],
    },
    "房地产": {
        "eastmoney_concept": ["房地产", "租售同权", "物业管理"],
        "keywords": ["房地产", "地产", "楼市"],
    },
    "中成药": {
        "eastmoney_concept": ["中医药", "中药"],
        "keywords": ["中成药", "中药", "中医药"],
    },
    "小金属": {
        "eastmoney_concept": ["小金属", "稀土"],
        "keywords": ["小金属", "稀土", "有色金属"],
    },
    "纺织服装": {
        "eastmoney_concept": ["纺织服装", "服饰"],
        "keywords": ["服饰", "纺织服装"],
    },
    "有色金属": {
        "eastmoney_concept": ["有色金属"],
        "keywords": ["有色金属", "有色板块"],
    },
    "IT设备": {
        "eastmoney_concept": ["IT设备"],
        "keywords": ["IT设备", "计算机设备"],
    },
    "家居用品": {
        "eastmoney_concept": ["家居"],
        "keywords": ["家居", "家居用品"],
    },
    "文教休闲": {
        "eastmoney_concept": ["文教", "休闲"],
        "keywords": ["文教", "休闲"],
    },
    "汽车配件": {
        "eastmoney_concept": ["汽车零部件", "胎压监测"],
        "keywords": ["汽车配件", "汽车零部件", "汽配"],
    },
    "广告包装": {
        "eastmoney_concept": ["广告", "包装"],
        "keywords": ["广告", "包装"],
    },
    "塑料": {
        "eastmoney_concept": ["可降解塑料"],
        "keywords": ["塑料", "橡胶"],
    },
    "橡胶": {
        "eastmoney_concept": ["橡胶"],
        "keywords": ["橡胶", "橡胶制品"],
    },
    "房地产服务": {
        "eastmoney_concept": ["房地产服务"],
        "keywords": ["房产服务", "房地产服务"],
    },
    "煤炭开采": {
        "eastmoney_concept": ["煤炭"],
        "keywords": ["煤炭", "煤炭开采", "焦炭"],
    },
    "汽车整车": {
        "eastmoney_concept": ["新能源汽车", "汽车整车"],
        "keywords": ["汽车整车", "新能源汽车"],
    },
}

# ── Special themes (concept-level, NOT covered by DangInvest boards) ──
SPECIAL = [
    {
        "canonical": "人工智能",
        "source": {
            "eastmoney_industry": ["软件开发", "互联网服务"],
            "eastmoney_concept": ["人工智能", "AI", "AIGC", "大模型", "ChatGPT", "算力"],
            "danginvest_board": [],
        },
        "search_keywords": ["人工智能", "AI", "大模型", "算力", "AIGC"],
        "overlap_evidence": {},
    },
    {
        "canonical": "人形机器人",
        "source": {
            "eastmoney_industry": ["自动化设备"],
            "eastmoney_concept": ["人形机器人", "具身智能", "机器人"],
            "danginvest_board": [],
        },
        "search_keywords": ["人形机器人", "具身智能", "机器人 产业链", "人形机器人 供应链"],
        "overlap_evidence": {},
    },
    {
        "canonical": "新能源汽车",
        "source": {
            "eastmoney_industry": ["汽车整车"],
            "eastmoney_concept": ["新能源汽车", "锂电池", "充电桩", "特斯拉", "固态电池"],
            "danginvest_board": [],
        },
        "search_keywords": ["新能源汽车", "新能源车", "电动汽车", "锂电池", "固态电池"],
        "overlap_evidence": {},
    },
    {
        "canonical": "光伏",
        "source": {
            "eastmoney_industry": ["光伏设备"],
            "eastmoney_concept": ["光伏", "太阳能", "HJT", "钙钛矿", "TOPCon"],
            "danginvest_board": [],
        },
        "search_keywords": ["光伏", "太阳能", "HJT 电池", "光伏产业链"],
        "overlap_evidence": {},
    },
    {
        "canonical": "医药",
        "source": {
            "eastmoney_industry": ["医药制造", "医疗行业"],
            "eastmoney_concept": ["创新药", "CXO", "生物疫苗", "中医药", "医疗器械"],
            "danginvest_board": ["医疗保健", "化学制药", "生物制药"],
        },
        "search_keywords": ["医药", "创新药", "CXO 板块", "医疗器械"],
        "overlap_evidence": {},
    },
    {
        "canonical": "数据中心",
        "source": {
            "eastmoney_industry": ["通信服务"],
            "eastmoney_concept": ["数据中心", "云计算", "东数西算", "算力", "IDC"],
            "danginvest_board": [],
        },
        "search_keywords": ["数据中心", "IDC", "云计算", "东数西算"],
        "overlap_evidence": {},
    },
    {
        "canonical": "低空经济",
        "source": {
            "eastmoney_industry": [],
            "eastmoney_concept": ["低空经济", "eVTOL", "飞行汽车", "无人机"],
            "danginvest_board": [],
        },
        "search_keywords": ["低空经济", "eVTOL", "飞行汽车", "无人机 产业"],
        "overlap_evidence": {},
    },
]


def main():
    with open(MAPPING_PATH) as f:
        data = yaml.safe_load(f) or []

    by_canon = {}
    for row in data:
        c = (row.get("canonical") or "").strip()
        if c:
            by_canon[c] = row

    # 1. Apply enrichments
    enriched = 0
    for canon, enrich in RICH.items():
        if canon in by_canon:
            row = by_canon[canon]
            src = row.setdefault("source", {})
            if not src.get("eastmoney_concept"):
                src["eastmoney_concept"] = enrich.get("eastmoney_concept", [])
            row["search_keywords"] = enrich["keywords"]
            enriched += 1
    print(f"  Enriched {enriched} entries")

    # 2. Apply legacy aliases
    aliases_applied = 0
    for legacy_name, (key_type, target_canon) in LEGACY_ALIASES.items():
        if target_canon not in by_canon:
            continue
        row = by_canon[target_canon]
        src = row.setdefault("source", {})
        existing = src.get(key_type) or []
        if isinstance(existing, str):
            existing = [existing]
        if legacy_name not in existing:
            existing.append(legacy_name)
            src[key_type] = existing
            aliases_applied += 1
    print(f"  Applied {aliases_applied} legacy alias mappings")

    # 3. Add special themes
    existing_canonicals = set(by_canon.keys())
    added = 0
    for theme in SPECIAL:
        c = theme["canonical"]
        if c not in existing_canonicals:
            data.append(theme)
            existing_canonicals.add(c)
            added += 1
        else:
            # Merge concepts into existing entry
            row = by_canon[c]
            src = row.setdefault("source", {})
            theme_src = theme.get("source", {})
            tc = theme_src.get("eastmoney_concept", [])
            existing_tc = src.get("eastmoney_concept") or []
            if isinstance(existing_tc, str):
                existing_tc = [existing_tc]
            for t in tc:
                if t not in existing_tc:
                    existing_tc.append(t)
            if existing_tc:
                src["eastmoney_concept"] = existing_tc
            row["search_keywords"] = theme.get("search_keywords", row.get("search_keywords", [c]))
    print(f"  Added {added} special theme entries")

    # Write
    with open(MAPPING_PATH, "w") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"  Written to {MAPPING_PATH} ({len(data)} total entries)")


if __name__ == "__main__":
    main()
