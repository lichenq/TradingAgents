#!/usr/bin/env python3
"""
个股板块信息查询脚本
数据源：东方财富 HTTP API（多源兜底，Agent 下 curl 优先）

功能：
- 查询单只/多只股票所属的行业板块
- 查询单只/多只股票所属的概念板块
- 默认并行查询，速度快

依赖安装：pip install requests

用法示例：
  python3 fetch_sector_info.py 600519
  python3 fetch_sector_info.py 600519 000001 300750
  python3 fetch_sector_info.py --json 600519 000001
  python3 fetch_sector_info.py --batch-test
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from http_util import get_json, get_text

EM_STOCK_URL = "https://push2.eastmoney.com/api/qt/stock/get"
EM_COMPANY_URL = "https://emweb.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax"
EM_UT = "fa5fd1943c7b386f172d6893dbfba10b"
SINA_QUOTE_URL = "https://hq.sinajs.cn/list="
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="

DEFAULT_WORKERS = 8


def normalize_code(code: str) -> tuple:
    """标准化股票代码，返回 (市场代码, 纯代码)"""
    code = code.strip()
    if code.lower().startswith("sh"):
        return ("1", code[2:].zfill(6))
    elif code.lower().startswith("sz"):
        return ("0", code[2:].zfill(6))
    elif code.startswith("6"):
        return ("1", code.zfill(6))
    elif code.startswith(("0", "2", "3")):
        return ("0", code.zfill(6))
    elif "." in code:
        parts = code.split(".")
        if len(parts) == 2:
            if parts[0].upper() == "XSHG" or parts[1].upper() == "SH":
                return ("1", parts[1].zfill(6) if parts[1].isdigit() else parts[0].zfill(6))
            elif parts[0].upper() == "XSHE" or parts[1].upper() == "SZ":
                return ("0", parts[1].zfill(6) if parts[1].isdigit() else parts[0].zfill(6))
    return (None, code.zfill(6))


def _norm_exchange_code(code6: str, market: str) -> str:
    return ("sh" if market == "1" else "sz") + code6


def _fetch_push2_snapshot(secid: str, timeout: int) -> tuple[Optional[str], Optional[str]]:
    try:
        payload = get_json(
            EM_STOCK_URL,
            params={"secid": secid, "fields": "f57,f58,f127", "ut": EM_UT},
            timeout=timeout,
            headers={"Referer": "https://quote.eastmoney.com/"},
        )
        data = payload.get("data") or {}
        return data.get("f58"), data.get("f127")
    except Exception:
        return None, None


def _fetch_from_company_survey(norm: str, timeout: int) -> tuple[Optional[str], Optional[str]]:
    try:
        payload = get_json(
            EM_COMPANY_URL,
            params={"code": norm},
            timeout=timeout,
            headers={"Referer": "https://emweb.eastmoney.com/"},
        )
        jbzl = payload.get("jbzl") or {}
        return jbzl.get("agjc"), jbzl.get("sshy")
    except Exception:
        return None, None


def _fetch_name_sina(norm: str, timeout: int) -> Optional[str]:
    try:
        text = get_text(
            f"{SINA_QUOTE_URL}{norm}",
            timeout=timeout,
            headers={"Referer": "https://finance.sina.com.cn/"},
        )
        if '="' not in text:
            return None
        val = text.split('="')[1].rstrip('";')
        fields = val.split(",")
        return fields[0] if fields and fields[0] else None
    except Exception:
        return None


def _fetch_name_tencent(norm: str, timeout: int) -> Optional[str]:
    try:
        text = get_text(f"{TENCENT_QUOTE_URL}{norm}", timeout=timeout)
        for line in text.strip().split("\n"):
            if "~" not in line:
                continue
            parts = line.split("~")
            if len(parts) > 1 and parts[1]:
                return parts[1]
        return None
    except Exception:
        return None


def _fetch_name_industry_akshare(code6: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    try:
        import akshare as ak
    except ImportError:
        return None, None, "akshare not installed"
    try:
        info = ak.stock_individual_info_em(symbol=code6)
        if info is None or info.empty:
            return None, None, "akshare empty"
        name = None
        industry = None
        for item_key, target in (("股票简称", "name"), ("行业", "industry")):
            row = info[info["item"] == item_key]
            if not row.empty:
                val = row["value"].values[0]
                if target == "name":
                    name = val
                else:
                    industry = val
        return name, industry, None
    except Exception as exc:
        return None, None, str(exc)


def _apply_fallback(
    result: Dict,
    source: str,
    name: Optional[str],
    industry: Optional[str],
) -> None:
    if name and not result["name"]:
        result["name"] = name
    if industry and not result["industry"]:
        result["industry"] = industry
    if result["name"] or result["industry"]:
        result["source"] = source
        result["error"] = None


def get_sector_info_http(code6: str, market: str, timeout: int = 8, include_concepts: bool = True, retries: int = 2) -> Dict:
    """通过多源 HTTP 获取个股板块信息（emweb / 腾讯 / 新浪优先于 push2）"""
    result = {
        "code": code6,
        "name": None,
        "industry": None,
        "concepts": [],
        "source": "eastmoney",
        "error": None,
    }

    if market is None:
        market = "1" if code6.startswith("6") else "0"

    secid = f"{market}.{code6}"
    norm = _norm_exchange_code(code6, market)
    attempts: List[str] = []

    # 1) emweb 公司概况（Agent 下比 push2 更稳）
    cs_name, cs_industry = _fetch_from_company_survey(norm, timeout)
    if cs_name or cs_industry:
        _apply_fallback(result, "eastmoney(emweb)", cs_name, cs_industry)
    else:
        attempts.append("emweb: failed")

    # 2) push2 快照
    if not (result["name"] and result["industry"]):
        p_name, p_industry = _fetch_push2_snapshot(secid, timeout)
        if p_name or p_industry:
            _apply_fallback(result, "eastmoney(push2)", p_name, p_industry)
        else:
            attempts.append("push2: failed")

    # 3) 名称：新浪 / 腾讯
    if not result["name"]:
        sina_name = _fetch_name_sina(norm, timeout)
        if sina_name:
            prev = result["source"]
            _apply_fallback(
                result,
                f"{prev}+sina" if result.get("industry") and prev != "eastmoney" else "sina",
                sina_name,
                None,
            )
        else:
            attempts.append("sina: failed")

    if not result["name"]:
        tx_name = _fetch_name_tencent(norm, timeout)
        if tx_name:
            prev = result["source"]
            _apply_fallback(
                result,
                f"{prev}+tencent" if result.get("industry") and prev != "eastmoney" else "tencent",
                tx_name,
                None,
            )
        else:
            attempts.append("tencent: failed")

    # 4) akshare（仍走 push2，末级）
    if not (result["name"] and result["industry"]):
        ak_name, ak_industry, ak_err = _fetch_name_industry_akshare(code6)
        if ak_name or ak_industry:
            _apply_fallback(result, "eastmoney(akshare)", ak_name, ak_industry)
        elif ak_err:
            attempts.append(f"akshare: {ak_err}")

    # 概念板块（可选，仍走 push2）
    if include_concepts and not result.get("concepts"):
        for _ in range(retries + 1):
            try:
                payload = get_json(
                    "https://push2.eastmoney.com/api/qt/slist/get",
                    params={
                        "secid": secid,
                        "fields": "f12,f14",
                        "spt": "3",
                        "ut": EM_UT,
                    },
                    timeout=timeout,
                    headers={"Referer": "https://quote.eastmoney.com/"},
                )
                if payload.get("data") and payload["data"].get("diff"):
                    for item in payload["data"]["diff"]:
                        name = item.get("f14", "")
                        if name and name not in result["concepts"]:
                            result["concepts"].append(name)
                break
            except Exception:
                if _ < retries:
                    time.sleep(0.1 * (_ + 1))

    if not (result["name"] or result["industry"]) and attempts:
        result["error"] = "; ".join(attempts)

    return result


def get_sector_info(code: str, timeout: int = 8, include_concepts: bool = True) -> Dict:
    market, code6 = normalize_code(code)
    return get_sector_info_http(code6, market, timeout, include_concepts)


def batch_get_sector_info(codes: List[str], timeout: int = 8, max_workers: int = DEFAULT_WORKERS, include_concepts: bool = True) -> List[Dict]:
    if not codes:
        return []
    if len(codes) == 1:
        return [get_sector_info(codes[0], timeout, include_concepts)]

    results = []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(codes))) as executor:
        future_to_code = {
            executor.submit(get_sector_info, code, timeout, include_concepts): code
            for code in codes
        }
        for future in as_completed(future_to_code):
            code = future_to_code[future]
            try:
                results.append(future.result())
            except Exception as e:
                results.append({
                    "code": code,
                    "name": None,
                    "industry": None,
                    "concepts": [],
                    "source": "error",
                    "error": str(e),
                })

    code_order = {c: i for i, c in enumerate(codes)}
    results.sort(key=lambda x: code_order.get(x.get("code", ""), 999))
    return results


def print_single_result(result: Dict, output_json: bool = False):
    if output_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    code = result.get("code", "N/A")
    name = result.get("name") or "未知"
    industry = result.get("industry") or "未知"
    concepts = result.get("concepts", [])
    source = result.get("source", "未知")
    error = result.get("error")

    print(f"{'='*60}")
    print(f"  代码: {code}")
    print(f"  名称: {name}")
    print(f"  行业: {industry}")
    print(f"  概念板块 ({len(concepts)}个):")
    if concepts:
        for i, concept in enumerate(concepts, 1):
            print(f"    {i}. {concept}")
    else:
        print("    (暂无)")
    print(f"  数据源: {source}")
    if error:
        print(f"  错误: {error}")
    print(f"{'='*60}")


def print_batch_results(results: List[Dict], output_json: bool = False, show_elapsed: float = None):
    if output_json:
        output = {"data": results}
        if show_elapsed is not None:
            output["elapsed_seconds"] = round(show_elapsed, 2)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    print(f"\n{'='*80}")
    print(f"{'代码':<10} {'名称':<12} {'行业':<15} {'概念数':<6} {'数据源':<10}")
    print(f"{'-'*80}")

    success_count = 0
    for r in results:
        code = r.get("code", "N/A")
        name = r.get("name") or "未知"
        industry = r.get("industry") or "未知"
        concept_count = len(r.get("concepts", []))
        source = r.get("source", "未知")
        is_success = bool(r.get("name") or r.get("industry"))
        status = "✓" if is_success else "✗"
        print(f"{code:<10} {name:<12} {industry:<15} {concept_count:<6} {source:<10} {status}")
        if is_success:
            success_count += 1

    print(f"{'-'*80}")
    print(f"总计: {len(results)} 只, 成功: {success_count} 只, 失败: {len(results) - success_count} 只", end="")
    if show_elapsed is not None:
        print(f", 耗时: {show_elapsed:.2f}秒")
    else:
        print()
    print(f"{'='*80}\n")


TEST_CODES = [
    "600519", "601318", "600036", "601166", "601398", "601288", "600000", "601939", "601988", "600030",
    "601211", "600276", "600887", "601888", "600900", "601012", "600309", "601899", "600585", "600104",
    "000001", "000002", "000333", "000651", "000858", "000568", "000538", "000063",
    "300750", "300059", "300015", "300014", "300274", "300124", "300033", "300498",
    "688981", "688599", "688111",
]


def run_batch_test(max_workers: int = DEFAULT_WORKERS, include_concepts: bool = True) -> bool:
    test_codes = list(dict.fromkeys(TEST_CODES))
    print(f"\n{'='*60}")
    print(f"  批量测试: {len(test_codes)} 只股票")
    print(f"  并发数: {max_workers}")
    print(f"{'='*60}")

    start_time = time.time()
    results = batch_get_sector_info(test_codes, timeout=8, max_workers=max_workers, include_concepts=include_concepts)
    elapsed = time.time() - start_time
    print_batch_results(results, show_elapsed=elapsed)

    fail_count = sum(1 for r in results if not (r.get("industry") or r.get("name")))
    if fail_count > 0:
        print("失败股票:")
        for r in results:
            if not (r.get("industry") or r.get("name")):
                print(f"  - {r.get('code')}: {r.get('error', '未知错误')}")
        return False
    return True


def parse_codes_from_args(args) -> List[str]:
    codes = []
    for code in args.codes:
        if "," in code:
            codes.extend([c.strip() for c in code.split(",") if c.strip()])
        else:
            codes.append(code.strip())
    return codes


def main():
    parser = argparse.ArgumentParser(description="查询个股板块信息（行业 + 概念板块），默认并行查询")
    parser.add_argument("codes", nargs="*", help="股票代码")
    parser.add_argument("--batch-test", action="store_true", help="内置批量测试")
    parser.add_argument("--timeout", type=int, default=8, help="单只超时秒数")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="并发数")
    parser.add_argument("--no-concepts", action="store_true", help="不查概念")
    parser.add_argument("--json", action="store_true", dest="output_json", help="JSON 输出")
    args = parser.parse_args()
    include_concepts = not args.no_concepts

    if args.batch_test:
        sys.exit(0 if run_batch_test(max_workers=args.workers, include_concepts=include_concepts) else 1)

    codes = parse_codes_from_args(args)
    if not codes:
        parser.print_help()
        sys.exit(1)

    start_time = time.time()
    results = batch_get_sector_info(codes, timeout=args.timeout, max_workers=args.workers, include_concepts=include_concepts)
    elapsed = time.time() - start_time

    if len(results) == 1:
        print_single_result(results[0], output_json=args.output_json)
    else:
        print_batch_results(results, output_json=args.output_json, show_elapsed=elapsed)

    success = all(r.get("industry") or r.get("name") for r in results)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
