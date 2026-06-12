#!/usr/bin/env python3
"""Aggregate sector rotation: fund flow + limit-up leaders + board picks + TA pullback → JSON."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import premarket_news_catalyst as news_catalyst  # noqa: E402

try:
    import premarket_forecast  # noqa: E402
except ImportError:
    premarket_forecast = None  # type: ignore[assignment]

try:
    import premarket_llm  # noqa: E402
except ImportError:
    premarket_llm = None  # type: ignore[assignment]

from tradingagents.agents.utils.rating import parse_rating  # noqa: E402
from tradingagents.dataflows.trade_date import resolve_default_trade_date  # noqa: E402
from tradingagents.graph.storage import query_report_flexible  # noqa: E402

from tradingagents.dataflows.sector_mapping import (
    get_danginvest_boards,
    get_eastmoney_concepts,
    get_eastmoney_industries,
    get_match_names,
)

A_SHARE = Path.home() / ".cursor/skills/a-share-data/run.sh"
LIMIT_UP_POOL_TOP = int(os.environ.get("PREMARKET_LIMIT_UP_TOP", "500"))
LIMIT_UP_CHG = float(os.environ.get("PREMARKET_LIMIT_UP_CHG", "9.5"))
BOARD_PICKS_PER_SECTOR = int(os.environ.get("PREMARKET_BOARD_PICKS", "3"))
TA_SCAN_MAX = int(os.environ.get("PREMARKET_TA_SCAN_MAX", "12"))
RESULTS_DIR = Path(os.environ.get("TRADINGAGENTS_RESULTS_DIR", str(ROOT / "results")))


def _trade_date() -> str:
    return resolve_default_trade_date()


def _attach_report_ratings(picks: list[dict]) -> list[dict]:
    if not picks:
        return picks
    trade_date = _trade_date()
    enriched: list[dict] = []
    for p in picks:
        row = dict(p)
        code = row.get("code") or ""
        db_row = query_report_flexible(RESULTS_DIR, code, trade_date)
        if db_row:
            text = (
                db_row.get("final_trade_decision")
                or db_row.get("trader_investment_plan")
                or db_row.get("investment_plan")
                or ""
            )
            rating = parse_rating(str(text), default="")
            if rating:
                row["deep_rating"] = rating
            row["has_deep_report"] = True
        enriched.append(row)
    return enriched


def _parse_json(stdout: str) -> object:
    lines = [ln for ln in stdout.splitlines() if ln.strip() and not ln.strip().startswith("%")]
    for i in range(len(lines)):
        chunk = "\n".join(lines[i:])
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            continue
    raise ValueError(f"No JSON in output: {stdout[:200]!r}")


def _run(script: str, *args: str) -> object:
    env = os.environ.copy()
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(k, None)
    env["NO_PROXY"] = "*"
    cmd = [str(A_SHARE), script, *args]
    out = subprocess.check_output(cmd, env=env, stderr=subprocess.STDOUT, text=True)
    return _parse_json(out)


def _normalize_code(val: object) -> str:
    digits = "".join(ch for ch in str(val or "") if ch.isdigit())
    if len(digits) < 6:
        return ""
    return digits[-6:].zfill(6)


def _stock_row(row: dict) -> dict:
    return {
        "code": row.get("代码") or row.get("code"),
        "name": row.get("名称") or row.get("name"),
        "change_pct": row.get("涨跌幅") or row.get("change_pct"),
    }


def _limit_up_for_sector(industry: str, by_industry: dict[str, list]) -> list[dict]:
    seen: set[str] = set()
    leaders: list[dict] = []
    for alias in get_match_names(industry):
        for s in by_industry.get(alias, []):
            code = str(s.get("code") or "")
            if not code or code in seen:
                continue
            seen.add(code)
            leaders.append(s)
    leaders.sort(key=lambda x: float(x.get("change_pct") or 0), reverse=True)
    return leaders[:5]


def _parse_consecutive(rows: list) -> list[dict]:
    out = []
    for row in rows:
        boards = row.get("昨日连板数") or row.get("consecutive") or 0
        try:
            boards = int(boards)
        except (TypeError, ValueError):
            boards = 0
        if boards < 1:
            continue
        pct = float(row.get("涨跌幅") or row.get("change_pct") or 0)
        out.append({
            "code": row.get("代码") or row.get("code"),
            "name": row.get("名称") or row.get("name"),
            "industry": row.get("所属行业") or row.get("industry"),
            "yesterday_boards": boards,
            "change_pct": pct,
        })
    out.sort(key=lambda x: (x["yesterday_boards"], x["change_pct"]), reverse=True)
    return out[:15]


def _fetch_em_board_rows(board_name: str, *, board_type: str) -> list[dict]:
    import akshare as ak

    try:
        if board_type == "concept":
            df = ak.stock_board_concept_cons_em(symbol=board_name)
        else:
            df = ak.stock_board_industry_cons_em(symbol=board_name)
    except Exception:
        return []
    if df is None or df.empty:
        return []

    rows: list[dict] = []
    for _, row in df.iterrows():
        code = _normalize_code(row.get("代码"))
        if not code:
            continue
        try:
            chg = float(row.get("涨跌幅") or 0)
        except (TypeError, ValueError):
            chg = 0.0
        rows.append({
            "code": code,
            "name": str(row.get("名称") or "").strip(),
            "change_pct": round(chg, 2),
        })
    rows.sort(key=lambda x: x["change_pct"], reverse=True)
    return rows


def _board_name_candidates(industry: str) -> list[str]:
    names: list[str] = []
    for n in get_eastmoney_industries(industry) + get_eastmoney_concepts(industry) + get_danginvest_boards(industry):
        n = (n or "").strip()
        if n and n not in names:
            names.append(n)
    if industry not in names:
        names.insert(0, industry)
    return names


def _board_picks_for_sector(industry: str, limit_up_codes: set[str], limit: int = BOARD_PICKS_PER_SECTOR) -> list[dict]:
    picks: list[dict] = []
    seen: set[str] = set()
    for name in _board_name_candidates(industry):
        if len(picks) >= limit:
            break
        for board_type in ("industry", "concept"):
            for row in _fetch_em_board_rows(name, board_type=board_type):
                code = row["code"]
                if code in seen or code in limit_up_codes:
                    continue
                if row["change_pct"] >= LIMIT_UP_CHG:
                    continue
                seen.add(code)
                picks.append(row)
                if len(picks) >= limit:
                    break
            if len(picks) >= limit:
                break
    picks.sort(key=lambda x: x["change_pct"], reverse=True)
    return picks[:limit]


def _ta_pullback_hits(codes: list[str]) -> dict[str, dict]:
    if not codes:
        return {}
    strategy_dir = Path.home() / ".cursor/skills/a-share-strategy-mainboard-multi-swing-defensive/scripts"
    if not strategy_dir.is_dir():
        return {}
    if str(strategy_dir) not in sys.path:
        sys.path.insert(0, str(strategy_dir))

    from paper_trading.market_data import MarketDataProvider  # noqa: WPS433
    from strategy_lab import strategy_params  # noqa: WPS433
    from strategy_lab.strategies import trend_pullback  # noqa: WPS433

    provider = MarketDataProvider()
    slow = int(strategy_params.TREND_PULLBACK_PARAMS.get("slow", 20))
    min_bars = max(slow + 3, 30)
    hits: dict[str, dict] = {}

    def scan(code: str) -> tuple[str, dict | None]:
        try:
            df = provider.get_history(code, count=120)
            if df is None or len(df) < min_bars:
                return code, None
            enriched = trend_pullback(df, strategy_params.TREND_PULLBACK_PARAMS)
            if enriched is None or len(enriched) < 2:
                return code, None
            prev = enriched.iloc[-2]
            last = enriched.iloc[-1]
            if bool(prev.get("entry")) or bool(last.get("entry")):
                bar = prev if bool(prev.get("entry")) else last
                return code, {
                    "close": round(float(bar["close"]), 2),
                    "score": round(float(bar.get("score", 0)), 4),
                }
        except Exception:
            return code, None
        return code, None

    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(scan, c): c for c in codes[:TA_SCAN_MAX]}
        for fut in as_completed(futs):
            code, meta = fut.result()
            if meta:
                hits[code] = meta
    return hits


def diff_summaries(prev: dict, curr: dict) -> dict:
    prev_ranks = {s["industry"]: s.get("rank") for s in prev.get("top_sectors_by_fund_flow", [])}
    curr_ranks = {s["industry"]: s.get("rank") for s in curr.get("top_sectors_by_fund_flow", [])}
    new_top = [ind for ind in curr_ranks if ind not in prev_ranks]
    strengthened = []
    weakened = []
    for ind, rank in curr_ranks.items():
        old = prev_ranks.get(ind)
        if old is not None and rank < old:
            strengthened.append({"industry": ind, "from": old, "to": rank})
        elif old is not None and rank > old:
            weakened.append({"industry": ind, "from": old, "to": rank})
    exit_top = [ind for ind in prev_ranks if ind not in curr_ranks]
    delta = {
        "new_in_top": new_top,
        "rank_up": strengthened,
        "rank_down": weakened,
        "exit_top": exit_top,
    }
    delta["narrative"] = _rotation_narrative(delta)
    return delta


def _rotation_narrative(delta: dict) -> str:
    from_parts = (delta.get("exit_top") or [])[:2]
    if not from_parts:
        from_parts = [x["industry"] for x in (delta.get("rank_down") or [])[:2]]
    to_parts = (delta.get("new_in_top") or [])[:2]
    if not to_parts:
        to_parts = [x["industry"] for x in (delta.get("rank_up") or [])[:2]]
    if from_parts and to_parts:
        return f"{'/'.join(from_parts)}→{'/'.join(to_parts)}"
    if to_parts:
        return f"→{'/'.join(to_parts)}"
    if from_parts:
        return f"{'/'.join(from_parts)}→"
    return ""


def build_summary(*, previous_snapshot: dict | None = None) -> dict:
    fund = _run("fetch_industry_fund_flow.py", "--limit", "12", "--json")
    items = fund.get("items", fund) if isinstance(fund, dict) else fund

    limit_stats = _run("fetch_realtime.py", "--limit-stats", "--json")
    market_limit_up = limit_stats.get("涨停数量") if isinstance(limit_stats, dict) else None

    limit_up = _run(
        "fetch_realtime.py", "--limit-up-pool", "--top", str(LIMIT_UP_POOL_TOP), "--json",
    )
    if not isinstance(limit_up, list):
        limit_up = limit_up.get("data", []) if isinstance(limit_up, dict) else []

    consecutive_raw = _run("fetch_realtime.py", "--consecutive-limit", "--json")
    if not isinstance(consecutive_raw, list):
        consecutive_raw = consecutive_raw.get("data", []) if isinstance(consecutive_raw, dict) else []

    by_industry: dict[str, list] = defaultdict(list)
    limit_up_codes: set[str] = set()
    for row in limit_up:
        code = _normalize_code(row.get("代码") or row.get("code"))
        if code:
            limit_up_codes.add(code)
        ind = row.get("所属行业") or row.get("industry") or "未知"
        by_industry[ind].append(_stock_row(row))

    hot_industries = Counter({ind: len(stocks) for ind, stocks in by_industry.items()}).most_common(8)

    sectors = []
    board_codes: list[str] = []
    for it in items[:8]:
        ind = it.get("industry", "")
        board_picks = _attach_report_ratings(_board_picks_for_sector(ind, limit_up_codes))
        board_codes.extend(p["code"] for p in board_picks)
        sectors.append({
            "industry": ind,
            "main_net_inflow_yi": it.get("main_net_inflow_yi"),
            "change_pct": it.get("change_pct"),
            "rank": it.get("rank"),
            "limit_up_leaders": _limit_up_for_sector(ind, by_industry),
            "board_picks": board_picks,
            "ta_pullback": [],
        })

    ta_hits = _ta_pullback_hits(list(dict.fromkeys(board_codes)))
    for s in sectors:
        s["ta_pullback"] = [
            {**p, **ta_hits[p["code"]], "signal": "trend_pullback"}
            for p in s.get("board_picks", [])
            if p["code"] in ta_hits
        ]

    consecutive = _parse_consecutive(consecutive_raw)

    flow_inds = [it.get("industry", "") for it in items[:8]]
    news_items = _fetch_market_news()
    news_layer = _build_news_layer(flow_inds, news_items)

    result = {
        "ok": True,
        "market_limit_up_count": market_limit_up,
        "limit_up_pool_size": len(limit_up),
        "limit_up_pool_sample_size": len(limit_up),
        "top_sectors_by_fund_flow": sectors,
        "limit_up_clusters": [
            {"industry": ind, "count": cnt, "stocks": by_industry[ind][:5]}
            for ind, cnt in hot_industries
        ],
        "consecutive_limit_leaders": consecutive,
        "news_catalyst": news_layer,
    }

    if premarket_forecast:
        raw_fc = premarket_forecast.load_forecast_raw(RESULTS_DIR)
        result["sector_rotation_forecast"] = premarket_forecast.attach_forecast(sectors, raw_fc)

    if premarket_llm and premarket_llm.should_run_llm(previous_snapshot=previous_snapshot):
        insight = premarket_llm.build_insight(result, news_items)
        result["llm_insight"] = insight
        if insight.get("ok"):
            result["news_catalyst"] = premarket_llm.enrich_news_catalyst(news_layer, insight)
    elif premarket_llm and previous_snapshot:
        premarket_llm.reuse_insight_from_previous(result, previous_snapshot, news_layer)

    return result


def _fetch_market_news() -> list[dict]:
    payload = _run(
        "fetch_realtime.py",
        "--market-news",
        "--news-limit",
        str(news_catalyst.NEWS_LIMIT),
        "--json",
    )
    return payload.get("data", []) if isinstance(payload, dict) else []


def _build_news_layer(fund_flow_industries: list[str], items: list[dict] | None = None) -> dict:
    try:
        if items is None:
            items = _fetch_market_news()
        return news_catalyst.build_news_catalyst(items, fund_flow_industries=fund_flow_industries)
    except Exception as exc:
        return {"ok": False, "predicted_sectors": [], "ahead_of_fund_flow": [], "watch_if": "", "error": str(exc)[:200]}


def print_summary(data: dict) -> None:
    mc = data.get("market_limit_up_count")
    pool = data.get("limit_up_pool_size") or data.get("limit_up_pool_sample_size", 0)
    if mc is not None:
        print(f"涨停 {mc} 家（股池 {pool} 只）")
    delta = data.get("delta_vs_previous") or {}
    if delta.get("narrative"):
        print(f"轮动：{delta['narrative']}")
    cat = data.get("news_catalyst") or {}
    if cat.get("predicted_sectors"):
        print("--- news catalyst ---")
        for p in cat["predicted_sectors"][:5]:
            hl = (p.get("headlines") or [""])[0]
            print(f"  {p.get('industry')} ({p.get('article_count')}条) {hl}")
        if cat.get("ahead_of_fund_flow"):
            print(f"  前瞻: {'/'.join(cat['ahead_of_fund_flow'][:3])}")
        if cat.get("watch_if"):
            print(f"  IF: {cat['watch_if']}")
        for p in cat.get("llm_predicted") or []:
            print(f"  LLM: {p.get('industry')} — {p.get('reason')}")
    if data.get("sector_rotation_forecast", {}).get("highlights"):
        print("--- sector forecast ---")
        for h in data["sector_rotation_forecast"]["highlights"][:3]:
            print(f"  {h.get('industry')} {h.get('category_label')} {h.get('probability')}")
    insight = data.get("llm_insight") or {}
    if insight.get("brief"):
        print(f"AI要点: {insight['brief']}")
    deep = data.get("deep_curation") or {}
    if deep.get("portfolio_summary"):
        print(f"深度精选: {deep['portfolio_summary']}")
    if data.get("catalyst_confirmed"):
        print(f"催化确认: {'/'.join(data['catalyst_confirmed'])}")
    print("--- sector rotation ---")
    for s in data.get("top_sectors_by_fund_flow", []):
        leaders = ",".join(x.get("name", "") for x in s.get("limit_up_leaders", [])) or "-"
        picks = ",".join(
            f"{x.get('name')}({x.get('change_pct')}%"
            f"{('[' + x.get('deep_rating') + ']') if x.get('deep_rating') else ''})"
            for x in s.get("board_picks", [])
        ) or "-"
        ta = ",".join(x.get("name", "") for x in s.get("ta_pullback", [])) or "-"
        print(f"{s.get('rank')}. {s.get('industry')} 流入{s.get('main_net_inflow_yi')}亿 "
              f"+{s.get('change_pct')}% 龙头:{leaders} 强股:{picks} 回踩:{ta}")
    cons = data.get("consecutive_limit_leaders", [])
    if cons:
        print("--- consecutive limit (potential movers) ---")
        for x in cons[:8]:
            print(f"{x.get('name')} {x.get('code')} {x.get('yesterday_boards')}连板 "
                  f"{x.get('change_pct'):+.1f}% [{x.get('industry')}]")


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "--compare":
        prev = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        curr = build_summary(previous_snapshot=prev)
        delta = diff_summaries(prev, curr)
        curr["delta_vs_previous"] = delta
        confirmed = news_catalyst.catalyst_confirmed(prev.get("news_catalyst"), delta)
        if confirmed:
            curr["catalyst_confirmed"] = confirmed
        json.dump(curr, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        if delta.get("narrative") or delta.get("rank_up") or delta.get("rank_down"):
            out = sys.stderr
            print("--- theme delta ---", file=out)
            if delta.get("narrative"):
                print(f"轮动 {delta['narrative']}", file=out)
            for x in delta.get("rank_up", []):
                print(f"↑ {x['industry']} #{x['from']} → #{x['to']}", file=out)
            for x in delta.get("rank_down", []):
                print(f"↓ {x['industry']} #{x['from']} → #{x['to']}", file=out)
            for ind in delta.get("new_in_top", []):
                print(f"+ 新进入TOP: {ind}", file=out)
            for ind in delta.get("exit_top", []):
                print(f"- 退出TOP: {ind}", file=out)
            if confirmed:
                print(f"催化确认: {'/'.join(confirmed)}", file=out)
        return

    if len(sys.argv) >= 2 and sys.argv[1] == "--print":
        data = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        print_summary(data)
        return

    data = build_summary()
    json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
