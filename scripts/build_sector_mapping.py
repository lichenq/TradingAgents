#!/usr/bin/env python3
"""
Build the sector mapping table from constituent-stock overlap analysis.

Strategy: for each DangInvest board, probe its top-5 stocks via
``fetch_sector_info.py`` (emweb, works reliably) to discover the corresponding
EastMoney industry and concept names. Then compute cross-source links and
cluster them.

Pipeline:
  1. Load cached DangInvest board constituent stocks (already fetched)
  2. For each board, take top-5 stocks and probe their EastMoney sector info
  3. Aggregate results per board via majority vote
  4. Compute overlap links across source names
  5. Cluster related entities into theme groups
  6. (Optional) Call LLM to name clusters and generate search keywords
  7. Output ``tradingagents/data/sector_mapping.yaml``

Usage::

    # Normal run — use cached probe data if available
    python scripts/build_sector_mapping.py

    # Force re-probe all boards
    python scripts/build_sector_mapping.py --force-refresh

    # Skip the LLM naming step (use algorithmic default names)
    python scripts/build_sector_mapping.py --skip-llm

    # Save intermediate probe matrix for inspection
    python scripts/build_sector_mapping.py --save-matrix
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Set, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Paths ──────────────────────────────────────────────────────────────

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", ".cache", "sector_mapping")
CACHE_DANGINVEST = os.path.join(CACHE_DIR, "danginvest_board_stocks.json")
CACHE_PROBE = os.path.join(CACHE_DIR, "board_em_probe.json")
CACHE_MATRIX = os.path.join(CACHE_DIR, "overlap_matrix.json")

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "tradingagents", "data")
OUTPUT_YAML = os.path.join(OUTPUT_DIR, "sector_mapping.yaml")

# ── Thresholds ─────────────────────────────────────────────────────────

PROBE_TOP_N = 5                    # top-N stocks per DangInvest board
MAJORITY_MIN = 0.5                 # minimum share for majority-vote acceptance
MIN_COVERAGE = 0.25                # cross-source coverage threshold


# ══════════════════════════════════════════════════════════════════════
#  Layer 1: Data Loading
# ══════════════════════════════════════════════════════════════════════


def _run_sector_script(code: str) -> dict | None:
    """Run fetch_sector_info.py — returns parsed JSON or None."""
    runner = os.path.expanduser("~/.cursor/skills/a-share-data/run.sh")
    if not os.path.isfile(runner):
        return None
    env = dict(os.environ)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
              "http_proxy", "https_proxy", "all_proxy"):
        env.pop(k, None)
    env["NO_PROXY"] = "*"
    try:
        result = subprocess.run(
            [runner, "fetch_sector_info.py", "--json", code],
            capture_output=True, text=True, timeout=20,
            env=env,
        )
        if result.returncode == 0 and result.stdout:
            return json.loads(result.stdout)
    except Exception:
        pass
    return None


def load_danginvest_stocks() -> Dict[str, List[str]]:
    """Load cached DangInvest board constituents."""
    if not os.path.isfile(CACHE_DANGINVEST):
        print("  ERROR: DangInvest cache not found. Run with --fetch-danginvest first.")
        print(f"  Expected: {CACHE_DANGINVEST}")
        sys.exit(1)
    with open(CACHE_DANGINVEST) as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if isinstance(v, list) and len(v) > 0}


def probe_boards(
    board_stocks: Dict[str, List[str]],
    max_workers: int = 8,
    force: bool = False,
) -> Dict[str, Any]:
    """Probe each DangInvest board's top-N stocks for EastMoney sector info.

    Returns a dict keyed by DangInvest board name::

        {
          "半导体": {
            "probed": {"688981": {"industry": "半导体", "concepts": ["国产芯片", ...]}, ...},
            "industry_votes": {"半导体": 3},
            "concept_votes": {"国产芯片": 2, ...},
            "dominant_industry": "半导体",
            "dominant_concepts": ["国产芯片", "AI芯片"],
          },
          ...
        }
    """
    if not force and os.path.isfile(CACHE_PROBE):
        print(f"  Using cached probe data ({CACHE_PROBE})")
        with open(CACHE_PROBE) as f:
            return json.load(f)

    print(f"  Probing {len(board_stocks)} boards (top-{PROBE_TOP_N} stocks each)...")
    # Build a deduplicated task list: (board_name, stock_code)
    tasks: List[Tuple[str, str]] = []
    for board, stocks in board_stocks.items():
        for code in stocks[:PROBE_TOP_N]:
            tasks.append((board, code))

    # Deduplicate stock codes across boards
    code_set: Set[str] = {code for _, code in tasks}
    print(f"    {len(tasks)} probe tasks, {len(code_set)} unique stocks")

    # Fetch sector info for each unique stock
    code_cache: Dict[str, dict | None] = {}
    start = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        fut_map = {pool.submit(_run_sector_script, code): code for code in code_set}
        done = 0
        for fut in as_completed(fut_map):
            done += 1
            code = fut_map[fut]
            try:
                code_cache[code] = fut.result()
            except Exception:
                code_cache[code] = None
            if done % 100 == 0:
                elapsed = time.time() - start
                print(f"    ... {done}/{len(code_set)} stocks, {elapsed:.1f}s")

    elapsed = time.time() - start
    success = sum(1 for v in code_cache.values() if v)
    print(f"    Fetched {success}/{len(code_set)} stocks in {elapsed:.1f}s")

    # Aggregate per board
    result: Dict[str, Any] = {}
    for board, stocks in board_stocks.items():
        probed: Dict[str, dict] = {}
        ind_votes: Counter[str] = Counter()
        concept_votes: Counter[str] = Counter()
        for code in stocks[:PROBE_TOP_N]:
            payload = code_cache.get(code)
            if payload:
                probed[code] = payload
                ind = (payload.get("industry") or "").strip()
                if ind:
                    ind_votes[ind] += 1
                for c in (payload.get("concepts") or []):
                    if c.strip():
                        concept_votes[c.strip()] += 1

        dominant_ind = ind_votes.most_common(1)[0][0] if ind_votes else ""
        # Pick concepts that appear in at least 2 stocks or are dominant
        total = max(len(stocks[:PROBE_TOP_N]), 1)
        dominant_concepts = [
            c for c, cnt in concept_votes.most_common()
            if cnt >= 2 or (cnt / total >= 0.3 and cnt > 0)
        ][:8]

        result[board] = {
            "probed": probed,
            "industry_votes": dict(ind_votes),
            "concept_votes": dict(concept_votes),
            "dominant_industry": dominant_ind,
            "dominant_concepts": dominant_concepts,
        }

    # Cache
    os.makedirs(os.path.dirname(CACHE_PROBE), exist_ok=True)
    with open(CACHE_PROBE, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


# ══════════════════════════════════════════════════════════════════════
#  Layer 2: Overlap / Link Construction
# ══════════════════════════════════════════════════════════════════════


def build_links(probe_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build cross-source links from probe data.

    Each DangInvest board gets linked to its dominant EastMoney industry name
    and top concept names.
    """
    links: List[Dict[str, Any]] = []

    for board_name, board_data in probe_result.items():
        dominant_ind = board_data.get("dominant_industry", "")
        if dominant_ind:
            a_to_b = 1.0  # by construction: top-N probe decided on this
            b_to_a = 1.0
            links.append({
                "source": f"danginvest_board:{board_name}",
                "target": f"eastmoney_industry:{dominant_ind}",
                "source_name": board_name,
                "target_name": dominant_ind,
                "source_type": "danginvest_board",
                "target_type": "eastmoney_industry",
                "jaccard": 1.0,
                "a_to_b": a_to_b,
                "b_to_a": b_to_a,
                "shared": 0,  # not computed at probe level
                "probe_votes": board_data["industry_votes"].get(dominant_ind, 0),
                "probe_total": sum(board_data["industry_votes"].values()),
            })

        for concept in board_data.get("dominant_concepts", []):
            links.append({
                "source": f"danginvest_board:{board_name}",
                "target": f"eastmoney_concept:{concept}",
                "source_name": board_name,
                "target_name": concept,
                "source_type": "danginvest_board",
                "target_type": "eastmoney_concept",
                "jaccard": 1.0,
                "a_to_b": 1.0,
                "b_to_a": 1.0,
                "shared": 0,
                "probe_votes": board_data["concept_votes"].get(concept, 0),
                "probe_total": sum(board_data["concept_votes"].values()),
            })

    print(f"  Built {len(links)} cross-source links from probe data")
    return links


# ══════════════════════════════════════════════════════════════════════
#  Layer 3: Clustering
# ══════════════════════════════════════════════════════════════════════


def cluster_entities(links: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cluster related sector entities into theme groups using union-find."""
    parent: Dict[str, str] = {}
    rank: Dict[str, int] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        rx, ry = find(x), find(y)
        if rx == ry:
            return
        if rank.get(rx, 0) < rank.get(ry, 0):
            parent[rx] = ry
        elif rank.get(rx, 0) > rank.get(ry, 0):
            parent[ry] = rx
        else:
            parent[ry] = rx
            rank[rx] = rank.get(rx, 0) + 1

    for link in links:
        for key in ("source", "target"):
            if key not in parent:
                parent[link[key]] = link[key]
                rank[link[key]] = 0

    for link in links:
        union(link["source"], link["target"])

    groups: Dict[str, List[Dict]] = defaultdict(list)
    for link in links:
        root = find(link["source"])
        groups[root].append(link)

    result = []
    for root, members in groups.items():
        entities: Dict[str, Dict[str, str]] = {}
        for m in members:
            for key in ("source", "target"):
                uid_key = f"{key}_name"
                typ_key = f"{key}_type"
                if uid_key in m and typ_key in m:
                    uid = f"{m[typ_key]}:{m[uid_key]}"
                    if uid not in entities:
                        entities[uid] = {"type": m[typ_key], "name": m[uid_key]}

        name_counts: Counter[str] = Counter()
        for m in members:
            name_counts[m["source_name"]] += 1
            name_counts[m["target_name"]] += 1
        most_common = max(name_counts, key=name_counts.get) if name_counts else "unknown"

        result.append({
            "canonical_guess": most_common,
            "entities": list(entities.values()),
            "links": [
                {
                    "a": m["source_name"],
                    "b": m["target_name"],
                    "probe_votes": m.get("probe_votes", 0),
                    "probe_total": m.get("probe_total", 0),
                }
                for m in sorted(members, key=lambda x: x.get("probe_votes", 0), reverse=True)
            ],
            "evidence": {
                "max_votes": max(m.get("probe_votes", 0) for m in members),
                "total_links": len(members),
            },
        })

    result.sort(key=lambda x: x["evidence"]["max_votes"], reverse=True)
    return result


# ══════════════════════════════════════════════════════════════════════
#  Layer 4: LLM Naming
# ══════════════════════════════════════════════════════════════════════


def llm_name_clusters(clusters: List[Dict], skip: bool = False) -> List[Dict]:
    """Call LLM once to name each cluster and generate search keywords."""
    if skip or not clusters:
        for c in clusters:
            c["canonical"] = c["canonical_guess"]
            c["search_keywords"] = [c["canonical_guess"]]
        return clusters

    try:
        from openai import OpenAI

        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("TRADINGAGENTS_OPENAI_API_KEY", "")
        client_kwargs: dict = {}
        if api_key:
            client_kwargs["api_key"] = api_key
        client = OpenAI(**client_kwargs)

        cluster_text = ""
        for i, c in enumerate(clusters):
            entities = [e["name"] for e in c["entities"]]
            inds = [e["name"] for e in c["entities"] if e["type"] == "eastmoney_industry"]
            concepts = [e["name"] for e in c["entities"] if e["type"] == "eastmoney_concept"]
            boards = [e["name"] for e in c["entities"] if e["type"] == "danginvest_board"]
            cluster_text += f"\nCluster {i+1}:\n"
            cluster_text += f"  DangInvest boards: {', '.join(boards)}\n"
            if inds:
                cluster_text += f"  EastMoney 行业: {', '.join(inds)}\n"
            if concepts:
                cluster_text += f"  EastMoney 概念: {', '.join(concepts)}\n"
            cluster_text += f"  Probe votes: {c['evidence']['max_votes']}/{PROBE_TOP_N}\n"

        prompt = f"""You are building a sector/industry mapping table for A-share stock analysis.
Below are clusters of related sector names from different data sources.
For each cluster:
1. Choose a canonical Chinese sector name (short, standard market term)
2. Suggest 2-4 Chinese search keywords for news filtering

Reply ONLY with a JSON array:
[
  {{"canonical": "证券", "search_keywords": ["证券 板块", "券商", "券商股"]}},
  ...
]

Clusters:
{cluster_text}
"""
        print("\n  Calling LLM to name clusters...")
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or "[]"
        nlp_output = json.loads(content)
        items = nlp_output if isinstance(nlp_output, list) else nlp_output.get("clusters", [])
        for i, item in enumerate(items):
            if i < len(clusters):
                clusters[i]["canonical"] = item.get("canonical", clusters[i]["canonical_guess"])
                clusters[i]["search_keywords"] = item.get("search_keywords", [clusters[i]["canonical_guess"]])

    except Exception as e:
        print(f"  WARNING: LLM naming failed ({e}), using default names")
        for c in clusters:
            c["canonical"] = c["canonical_guess"]
            c["search_keywords"] = [c["canonical_guess"]]

    return clusters


# ══════════════════════════════════════════════════════════════════════
#  Layer 5: YAML Output
# ══════════════════════════════════════════════════════════════════════


def clusters_to_yaml(clusters: List[Dict]) -> str:
    """Format cluster data into YAML mapping file content."""
    lines = [
        "# Sector Mapping Table — auto-generated by scripts/build_sector_mapping.py",
        "#",
        "# canonical:           规范名称",
        "# source:",
        "#   eastmoney_industry:   东财 行业 分类",
        "#   eastmoney_concept:    东财 概念板块",
        "#   danginvest_board:     DangInvest 板块 groupLabel",
        "# search_keywords:       新闻/事件搜索关键词",
        "# overlap_evidence:      跨源探针证据（top-N 股票多数投票）",
        "",
    ]

    for c in clusters:
        canonical = c.get("canonical", c.get("canonical_guess", "unknown"))
        lines.append(f"- canonical: \"{canonical}\"")

        lines.append("  source:")
        em_inds = sorted({e["name"] for e in c.get("entities", []) if e["type"] == "eastmoney_industry"})
        em_concepts = sorted({e["name"] for e in c.get("entities", []) if e["type"] == "eastmoney_concept"})
        di_boards = sorted({e["name"] for e in c.get("entities", []) if e["type"] == "danginvest_board"})

        lines.append(f"    eastmoney_industry: {json.dumps(em_inds, ensure_ascii=False)}")
        lines.append(f"    eastmoney_concept: {json.dumps(em_concepts, ensure_ascii=False)}")
        lines.append(f"    danginvest_board: {json.dumps(di_boards, ensure_ascii=False)}")

        keywords = c.get("search_keywords", [canonical])
        lines.append(f"  search_keywords:")
        for kw in keywords:
            lines.append(f"    - \"{kw}\"")

        lines.append("  overlap_evidence:")
        for link in c.get("links", []):
            votes = link.get("probe_votes", 0)
            total = link.get("probe_total", 0)
            lines.append(f"    \"{link['a']}->{link['b']}\": \"probe votes {votes}/{total}\"")

        lines.append("")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="Build sector mapping table from DangInvest top-N stock probing",
    )
    parser.add_argument("--force-refresh", action="store_true",
                        help="Re-probe all boards (ignore cached probe data)")
    parser.add_argument("--skip-llm", action="store_true",
                        help="Skip LLM naming step")
    parser.add_argument("--save-matrix", action="store_true",
                        help="Save intermediate data for inspection")
    args = parser.parse_args()

    print("=" * 60)
    print("  Sector Mapping Builder (top-N probe strategy)")
    print("=" * 60)

    # Step 1: Load DangInvest stocks
    print("\n--- Step 1: Loading DangInvest board constituents ---")
    board_stocks = load_danginvest_stocks()
    print(f"  {len(board_stocks)} boards loaded from cache")

    # Step 2: Probe each board's top-N stocks for EastMoney info
    print("\n--- Step 2: Probing EastMoney sector info for top-N stocks ---")
    probe_result = probe_boards(board_stocks, force=args.force_refresh)

    # Stats
    ind_mapped = sum(1 for v in probe_result.values() if v.get("dominant_industry"))
    concept_mapped = sum(1 for v in probe_result.values() if v.get("dominant_concepts"))
    print(f"  Boards with industry mapping: {ind_mapped}/{len(probe_result)}")
    print(f"  Boards with concept mapping: {concept_mapped}/{len(probe_result)}")

    if args.save_matrix:
        with open(CACHE_MATRIX, "w") as f:
            json.dump(probe_result, f, ensure_ascii=False, indent=2)
        print(f"  Saved probe data to {CACHE_MATRIX}")

    # Step 3: Build links
    print("\n--- Step 3: Building cross-source links ---")
    links = build_links(probe_result)

    # Step 4: Cluster
    print("\n--- Step 4: Clustering entities ---")
    clusters = cluster_entities(links)
    print(f"  Formed {len(clusters)} clusters")
    for c in clusters:
        entities_str = ", ".join(e["name"] for e in c.get("entities", []))
        print(f"  [{c['canonical_guess']}] {entities_str}")

    # Step 5: LLM naming
    print("\n--- Step 5: LLM naming ---")
    clusters = llm_name_clusters(clusters, skip=args.skip_llm)

    # Step 6: Write YAML
    print("\n--- Step 6: Writing output ---")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    yaml_content = clusters_to_yaml(clusters)
    # Merge with existing mapping if it exists
    yaml_path = OUTPUT_YAML
    existing = ""
    if os.path.isfile(yaml_path):
        with open(yaml_path) as f:
            existing = f.read()
    # Write new (overwrite on purpose)
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write(yaml_content)
    print(f"  Written to {yaml_path} ({len(clusters)} clusters)")

    print("\nDone.\n")


if __name__ == "__main__":
    main()
