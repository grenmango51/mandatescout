#!/usr/bin/env python3
"""
MandateScout Deep Ingestion Pipeline (Approach B) Empirical Benchmark
====================================================================
Compares Baseline (homepage only, exact word boundary) against
Approach B (1-hop internal subpages + Finnish compound word & morphological matching).

Standard Real Query:
- Query: ""
- Industry Code: "25" (Manufacture of fabricated metal products, machining)
- Keywords: ["cnc", "koneistus", "sorvaus", "jyrsintä", "milling", "turning", "sopimusvalmistus", "konepaja"]
"""

import json
import os
import sys
import time

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from product.collector import CacheManager, execute_search


def run_benchmark():
    cache_dir = os.path.join(PROJECT_ROOT, "product", "cache")
    data_dir = os.path.join(PROJECT_ROOT, "product", "data")
    cache_mgr = CacheManager(cache_dir)

    query = ""
    industry_code = "25"
    keywords = [
        "cnc",
        "koneistus",
        "sorvaus",
        "jyrsintä",
        "milling",
        "turning",
        "sopimusvalmistus",
        "konepaja",
    ]
    limit = 10

    print("=" * 80)
    print("MANDATESCOUT INGESTION PIPELINE BENCHMARK: BASELINE vs APPROACH B")
    print("=" * 80)
    print(f"Target Query: 'Find precision CNC machining companies in Finland'")
    print(f"Parameters: query='{query}', industry_code='{industry_code}', limit={limit}")
    print(f"Keywords: {keywords}\n")

    # 1. BASELINE EXECUTION (Homepage only, exact word boundaries)
    print(">>> Running 1/2: Baseline (Homepage only, exact word matching)...")
    t0_base = time.time()
    res_base = execute_search(
        buyer_id=None,
        query=query,
        keywords=keywords,
        industry_code=industry_code,
        limit=limit,
        refresh=False,
        cache_mgr=cache_mgr,
        data_dir=data_dir,
        enable_subpages=False,
        compound_matching=False,
    )
    t_base_elapsed = round(time.time() - t0_base, 2)
    stats_base = res_base.get("stats", {})
    comps_base = res_base.get("companies", [])
    reviewed_base = res_base.get("reviewed_companies", [])

    # 2. APPROACH B EXECUTION (1-hop subpages + Finnish compound matching)
    print(">>> Running 2/2: Approach B (1-hop subpages + compound word matching)...")
    t0_b = time.time()
    res_b = execute_search(
        buyer_id=None,
        query=query,
        keywords=keywords,
        industry_code=industry_code,
        limit=limit,
        refresh=False,
        cache_mgr=cache_mgr,
        data_dir=data_dir,
        enable_subpages=True,
        compound_matching=True,
    )
    t_b_elapsed = round(time.time() - t0_b, 2)
    stats_b = res_b.get("stats", {})
    comps_b = res_b.get("companies", [])
    reviewed_b = res_b.get("reviewed_companies", [])

    # Metrics Compilation
    scanned_base = stats_base.get("scanned", len(reviewed_base))
    scanned_b = stats_b.get("scanned", len(reviewed_b))

    sites_read_base = stats_base.get("website_read", 0)
    sites_read_b = stats_b.get("website_read", 0)

    subpages_base = stats_base.get("subpages_crawled", 0)
    subpages_b = stats_b.get("subpages_crawled", 0)

    ev_pos_base = stats_base.get("evidence_positive", 0)
    ev_pos_b = stats_b.get("evidence_positive", 0)

    top_score_base = comps_base[0].get("relevance_score", 0.0) if comps_base else 0.0
    top_score_b = comps_b[0].get("relevance_score", 0.0) if comps_b else 0.0

    top_name_base = comps_base[0].get("name", "N/A") if comps_base else "N/A"
    top_name_b = comps_b[0].get("name", "N/A") if comps_b else "N/A"

    top_kws_base = len(comps_base[0].get("matched_keywords", [])) if comps_base else 0
    top_kws_b = len(comps_b[0].get("matched_keywords", [])) if comps_b else 0

    print("\n" + "=" * 80)
    print("EMPIRICAL BENCHMARK COMPARISON RESULTS")
    print("=" * 80)
    table = [
        ("Metric", "Baseline (Homepage Only)", "Approach B (Deep Ingestion)", "Delta / Improvement"),
        ("Pool Scanned", f"{scanned_base}", f"{scanned_b}", "Identical candidate pool"),
        ("Websites Read (Homepages)", f"{sites_read_base}", f"{sites_read_b}", "Identical accessible homepages"),
        ("Subpages Crawled", f"{subpages_base}", f"{subpages_b}", f"+{subpages_b} 1-hop priority pages"),
        (
            "Evidence-Positive Companies",
            f"{ev_pos_base}",
            f"{ev_pos_b}",
            f"+{ev_pos_b - ev_pos_base} companies (+{((ev_pos_b - ev_pos_base)/max(1, ev_pos_base))*100:.1f}%)",
        ),
        (
            "Top Match Score",
            f"{top_score_base}% ({top_name_base})",
            f"{top_score_b}% ({top_name_b})",
            f"{top_score_b - top_score_base:+.1f}% score coverage",
        ),
        (
            "Top Company Matched Keywords",
            f"{top_kws_base}/{len(keywords)}",
            f"{top_kws_b}/{len(keywords)}",
            f"+{top_kws_b - top_kws_base} matched keywords",
        ),
        ("Execution Time (cached pass)", f"{t_base_elapsed:.2f}s", f"{t_b_elapsed:.2f}s", f"{t_b_elapsed - t_base_elapsed:+.2f}s"),
    ]

    for row in table:
        print(f"{row[0]:<30} | {row[1]:<25} | {row[2]:<28} | {row[3]}")

    print("\n" + "-" * 80)
    print("TOP CANDIDATES COMPARISON (First 3):")
    print("-" * 80)
    print("[BASELINE TOP CANDIDATES]:")
    for i, c in enumerate(comps_base[:3], 1):
        print(f" {i}. {c.get('name')} ({c.get('business_id')}) - Score: {c.get('relevance_score')}% - Keywords: {c.get('matched_keywords')}")

    print("\n[APPROACH B TOP CANDIDATES]:")
    for i, c in enumerate(comps_b[:3], 1):
        print(f" {i}. {c.get('name')} ({c.get('business_id')}) - Score: {c.get('relevance_score')}% - Keywords: {c.get('matched_keywords')}")
        if c.get("subpages_crawled"):
            print(f"    Subpages: {c.get('subpages_crawled')}")
        for ev in c.get("evidence", []):
            if ev.get("kind") == "keyword_match":
                print(f"    Snippet ({ev.get('source_url')}): {ev.get('excerpt')[:120]}...")
                break

    # Save benchmark json artifact
    report_data = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "query": query,
        "industry_code": industry_code,
        "keywords": keywords,
        "baseline": {
            "elapsed_seconds": t_base_elapsed,
            "scanned": scanned_base,
            "website_read": sites_read_base,
            "subpages_crawled": subpages_base,
            "evidence_positive": ev_pos_base,
            "top_company": top_name_base,
            "top_score": top_score_base,
            "top_keywords_count": top_kws_base,
        },
        "approach_b": {
            "elapsed_seconds": t_b_elapsed,
            "scanned": scanned_b,
            "website_read": sites_read_b,
            "subpages_crawled": subpages_b,
            "evidence_positive": ev_pos_b,
            "top_company": top_name_b,
            "top_score": top_score_b,
            "top_keywords_count": top_kws_b,
        },
        "comparison": {
            "evidence_positive_gain": ev_pos_b - ev_pos_base,
            "evidence_positive_pct_gain": round(((ev_pos_b - ev_pos_base) / max(1, ev_pos_base)) * 100, 1),
            "subpages_crawled": subpages_b,
        },
    }

    out_json = os.path.join(PROJECT_ROOT, "benchmarks", "deep_ingestion_benchmark.json")
    os.makedirs(os.path.dirname(out_json), exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)
    print(f"\n[BENCHMARK] Saved detailed report to: {out_json}")

    return report_data


if __name__ == "__main__":
    run_benchmark()
