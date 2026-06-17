#!/usr/bin/env python3
"""Fetch EastMoney concept/industry board constituents and output as JSON.

Used by TradingAgents build_sector_mapping.py via run.sh (proxy-clean env).
"""
import json
import sys

import akshare as ak


def fetch_concept_stocks() -> dict:
    """Return {concept_name: [code6, ...]} for all EastMoney concept boards."""
    try:
        names_df = ak.stock_board_concept_name_em()
        col = "板块名称" if "板块名称" in names_df.columns else names_df.columns[0]
        names = names_df[col].tolist()
    except Exception as e:
        print(f"ERROR concept list: {e}", file=sys.stderr)
        return {}

    result = {}
    total = len(names)
    for i, name in enumerate(names):
        try:
            cons_df = ak.stock_board_concept_cons_em(symbol=name)
            code_col = next((c for c in ["代码", "code", "股票代码"] if c in cons_df.columns), None)
            if code_col is None:
                continue
            codes = []
            for val in cons_df[code_col]:
                s = str(val).strip()
                digits = "".join(ch for ch in s if ch.isdigit())
                if len(digits) == 6:
                    codes.append(digits)
            if codes:
                result[name] = codes
        except Exception:
            pass
        if (i + 1) % 100 == 0:
            print(f"  progress: {i+1}/{total}", file=sys.stderr)
    return result


def fetch_industry_stocks() -> dict:
    """Return {industry_name: [code6, ...]} for all EastMoney industry boards."""
    try:
        names_df = ak.stock_board_industry_name_em()
        col = "板块名称" if "板块名称" in names_df.columns else names_df.columns[0]
        names = names_df[col].tolist()
    except Exception as e:
        print(f"ERROR industry list: {e}", file=sys.stderr)
        return {}

    result = {}
    for name in names:
        try:
            cons_df = ak.stock_board_industry_cons_em(symbol=name)
            code_col = next((c for c in ["代码", "code", "股票代码"] if c in cons_df.columns), None)
            if code_col is None:
                continue
            codes = []
            for val in cons_df[code_col]:
                s = str(val).strip()
                digits = "".join(ch for ch in s if ch.isdigit())
                if len(digits) == 6:
                    codes.append(digits)
            if codes:
                result[name] = codes
        except Exception:
            pass
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Fetch board constituent stocks")
    parser.add_argument("--concept", action="store_true", help="Fetch concept boards")
    parser.add_argument("--industry", action="store_true", help="Fetch industry boards")
    args = parser.parse_args()

    if not args.concept and not args.industry:
        parser.print_help()
        sys.exit(1)

    output = {}
    if args.concept:
        print("Fetching concepts...", file=sys.stderr)
        output["concept"] = fetch_concept_stocks()
        print(f"  done: {len(output['concept'])} concepts", file=sys.stderr)
    if args.industry:
        print("Fetching industries...", file=sys.stderr)
        output["industry"] = fetch_industry_stocks()
        print(f"  done: {len(output['industry'])} industries", file=sys.stderr)

    print(json.dumps(output, ensure_ascii=False))
