#!/usr/bin/env python3
"""
Reproducible Benchmark Runner for MandateScout Collector
=========================================================
Runs bounded real-source experiments against Finnish PRH YTJ-API v3
and target websites under isolated cache (benchmarks/cache/).
Measures candidate volumes, retrieval latencies, website reachability,
keyword evidence hits, and corporate-change review flags.
"""

import datetime
import json
import os
import sys
import time
from typing import Any, Dict, List

# Ensure repository root is on Python path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from benchmarks.collector_snapshot import CacheManager, execute_search

BASE_BENCHMARK_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_BENCHMARK_DIR, "cache")
RESULTS_JSON_PATH = os.path.join(BASE_BENCHMARK_DIR, "results.json")

SCENARIOS = [
    {
        "label": "Cloud Software & IT Services (Cloud / Sector 62)",
        "query": "Cloud",
        "industry_code": "62",
        "keywords": [
            "cloud",
            "pilvipalvelut",
            "saas",
            "ohjelmisto",
            "software",
            "rajapinta",
            "integraatio",
        ],
        "analyst_choice": "Advisor-selected Finnish/English terminology for enterprise software and cloud hosting.",
        "limit": 15,
    },
    {
        "label": "Industrial Metal Manufacturing (Sector 25)",
        "query": "",
        "industry_code": "25",
        "keywords": [
            "koneistus",
            "ohutlevy",
            "metallirakenteet",
            "hitsaus",
            "machining",
            "sheet metal",
            "manufacturing",
        ],
        "analyst_choice": "Advisor-selected Finnish/English terminology for subcontract metal fabrication and CNC machining.",
        "limit": 15,
    },
    {
        "label": "Machinery & Industrial Equipment (Sector 28)",
        "query": "",
        "industry_code": "28",
        "keywords": [
            "automaatio",
            "koneet",
            "laitteet",
            "erikoiskoneet",
            "automation",
            "machinery",
            "equipment",
        ],
        "analyst_choice": "Advisor-selected Finnish/English terminology for OEM equipment fabrication and industrial automation.",
        "limit": 15,
    },
]

LIMITATIONS = [
    "PRH YTJ Open Data API v3 filters by companyForm (OY) and mainBusinessLine prefix, but does not provide financial metrics (revenue, EBITDA) or ownership rosters in free open tiers.",
    "Name search matches against registered company legal trade names only; it does not index full-text operational descriptions across the national registry.",
    "Website presence is dependent on official registry URL filings; missing or outdated registry URLs lead to unexamined candidates without reflecting real business viability.",
    "Keyword coverage measures public web prose alignment with advisor-defined search heuristics; it does NOT indicate acquisition suitability, transaction readiness, or commercial fitness.",
    "Corporate-change terms ('acquired by', 'yhdistivät voimansa', etc.) act strictly as advisory review triggers to prevent treating subsidiaries as independent targets, not as confirmed ownership status.",
    "Web fetching uses standard TLS with a strict 7-second timeout and 1 MB ceiling; bot-protection (Cloudflare/CAPTCHA), geo-blocking, or slow hosting may result in unreachability.",
]


def run_benchmarks() -> Dict[str, Any]:
    print("=" * 70)
    print("Starting MandateScout Isolated Benchmark Run")
    print(f"Timestamp: {datetime.datetime.now(datetime.timezone.utc).isoformat()}")
    print(f"Isolated Cache Directory: {CACHE_DIR}")
    print(f"Scenarios: {len(SCENARIOS)}")
    print("=" * 70)

    cache_mgr = CacheManager(CACHE_DIR)
    bench_start_time = time.perf_counter()

    runs_output: List[Dict[str, Any]] = []
    all_companies_by_bid: Dict[str, Dict[str, Any]] = {}
    run_records: List[Dict[str, Any]] = []

    for idx, sc in enumerate(SCENARIOS, 1):
        print(f"\n[{idx}/{len(SCENARIOS)}] Executing: {sc['label']}")
        print(f"  Query: '{sc['query']}' | Industry Code: '{sc['industry_code']}' | Limit: {sc['limit']}")
        print(f"  Analyst Choice: {sc['analyst_choice']}")
        print(f"  Keywords: {', '.join(sc['keywords'])}")

        run_start = time.perf_counter()
        result = execute_search(
            buyer_id=None,
            query=sc["query"],
            keywords=sc["keywords"],
            industry_code=sc["industry_code"],
            limit=sc["limit"],
            refresh=True,
            cache_mgr=cache_mgr,
        )
        run_elapsed = round(time.perf_counter() - run_start, 2)

        comps = result.get("companies", [])
        total_candidates = result.get("total_candidates", 0)
        returned_companies = len(comps)

        fetched_websites = sum(1 for c in comps if c.get("website_status") == "fetched")
        keyword_evidence_comps = sum(1 for c in comps if len(c.get("matched_keywords", [])) > 0)
        review_flags = sum(1 for c in comps if c.get("excluded_reason") is not None)

        print(f"  -> Elapsed: {run_elapsed}s | Total Candidates: {total_candidates} | Returned: {returned_companies}")
        print(f"  -> Fetched Websites: {fetched_websites} | Keyword Matches: {keyword_evidence_comps} | Review Flags: {review_flags}")
        print(f"  -> Run ID: {result.get('run_id')}")

        runs_output.append({
            "label": sc["label"],
            "query": sc["query"],
            "industry_code": sc["industry_code"],
            "elapsed_seconds": run_elapsed,
            "total_candidates": total_candidates,
            "returned_companies": returned_companies,
            "fetched_websites": fetched_websites,
            "keyword_evidence_companies": keyword_evidence_comps,
            "review_flags": review_flags,
            "run_id": result.get("run_id"),
        })

        run_records.append(result)

        for c in comps:
            bid = c["business_id"]
            # If seen before, record overlap; retain enriched version with more evidence if needed
            if bid not in all_companies_by_bid:
                all_companies_by_bid[bid] = c
            else:
                # Merge matched keywords / evidence if duplicate
                existing = all_companies_by_bid[bid]
                combined_kws = sorted(list(set(existing.get("matched_keywords", []) + c.get("matched_keywords", []))))
                existing["matched_keywords"] = combined_kws
                if c.get("excluded_reason") and not existing.get("excluded_reason"):
                    existing["excluded_reason"] = c.get("excluded_reason")

    total_bench_elapsed = round(time.perf_counter() - bench_start_time, 2)

    # Compute deduplicated totals across all runs by business_id
    unique_bids = list(all_companies_by_bid.keys())
    total_returned_deduped = len(unique_bids)
    total_fetched_deduped = sum(
        1 for bid in unique_bids if all_companies_by_bid[bid].get("website_status") == "fetched"
    )
    total_kw_evidence_deduped = sum(
        1 for bid in unique_bids if len(all_companies_by_bid[bid].get("matched_keywords", [])) > 0
    )
    total_review_flags_deduped = sum(
        1 for bid in unique_bids if all_companies_by_bid[bid].get("excluded_reason") is not None
    )

    totals = {
        "returned_companies": total_returned_deduped,
        "fetched_websites": total_fetched_deduped,
        "keyword_evidence_companies": total_kw_evidence_deduped,
        "review_flags": total_review_flags_deduped,
        "elapsed_seconds": total_bench_elapsed,
    }

    results_data = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": (
            "Bounded live empirical benchmark querying Finnish PRH YTJ-API v3 and live public company "
            "websites across 3 distinct industrial sectors (Cloud IT/62, Fabricated Metal/25, Machinery/28). "
            "Enforces normal TLS, active OY entity validation, refresh=True, bounded safe HTTP fetching, "
            "SHA-256 cryptographic provenance hashing, and isolated cache storage in benchmarks/cache."
        ),
        "runs": runs_output,
        "totals": totals,
        "limitations": LIMITATIONS,
    }

    # Write results.json exactly matching required schema
    with open(RESULTS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(results_data, f, indent=2, ensure_ascii=False)
    print(f"\nSaved benchmark results to {RESULTS_JSON_PATH}")

    # Summary report
    print("\n" + "=" * 70)
    print("BENCHMARK TOTALS (DEDUPLICATED BY BUSINESS ID)")
    print(f"Total Unique Returned Companies: {totals['returned_companies']}")
    print(f"Total Unique Fetched Websites:   {totals['fetched_websites']}")
    print(f"Total Unique Keyword Matches:    {totals['keyword_evidence_companies']}")
    print(f"Total Unique Review Flags:       {totals['review_flags']}")
    print(f"Total Wall-Clock Elapsed Time:   {totals['elapsed_seconds']}s")
    print("=" * 70)

    # Print candidate sample details for audit inspection
    print("\n--- SAMPLE AUDIT CANDIDATES ---")
    sample_count = 0
    for bid, c in all_companies_by_bid.items():
        evidence = c.get("evidence", [])
        web_ev = [e for e in evidence if e.get("kind") != "source_fact"]
        print(f"\nBusiness ID: {bid} | Name: {c['name']}")
        print(f"  Industry: {c['industry_code']} - {c['industry_label']}")
        print(f"  Website: {c.get('website')} | Status: {c.get('website_status')}")
        print(f"  Retrieved At: {c.get('website_retrieved_at') or c.get('registry_retrieved_at')}")
        print(f"  Matched Keywords: {c.get('matched_keywords')}")
        print(f"  Excluded/Review Reason: {c.get('excluded_reason')}")
        for ev in web_ev[:2]:
            print(f"  Snippet ({ev.get('criterion')}): {ev.get('excerpt')}")
        sample_count += 1
        if sample_count >= 10:
            break

    return results_data


if __name__ == "__main__":
    run_benchmarks()
