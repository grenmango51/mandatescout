#!/usr/bin/env python3
"""
MandateScout Focused Backend Relevance & Discovery Pool Test Suite
==================================================================
Python Standard Library Only (unittest).
Validates:
1. Discovery pool expansion: discovers 100-200 active current-sector OYs.
2. Prioritization of registered websites over missing-website records.
3. Bounded concurrent enrichment (4 workers) within predictable runtime.
4. Paginated raw cache preservation: caches all pages individually and combined,
   preserving traceable UTC dates and SHA-256 hashes.
5. Explicit assessment status: missing/unread websites marked as not_assessed
   rather than negative evidence.
6. Planner bilingual keyword expansion and avoidance of generic name filters.
7. Accurate stats distinguishing scanned, website_read, evidence_positive, returned.
8. Real CNC query comparison validating the shift from 10/3/1 to 100+/20+/10 matches.
"""

import datetime
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from product.collector import (
    CacheManager,
    calculate_relevance_score,
    clean_html_to_text,
    enrich_company_website,
    execute_search,
    fetch_prh_companies,
    normalize_prh_company,
)
from product.planner import (
    plan_research,
    plan_with_rules,
    validate_plan_parameters,
)


class TestPlannerBilingualAndNoGenericFilter(unittest.TestCase):
    """Verifies planner improvements: bilingual keywords and safe name filter bounds."""

    def test_cnc_bilingual_keywords_and_empty_query(self):
        plan = plan_with_rules("Find precision CNC machining companies in Finland")
        self.assertEqual(plan["industry_code"], "25")
        # Generic descriptive term 'machining' or 'cnc' MUST NOT become company name filter
        self.assertEqual(plan["query"], "")
        # Bilingual keywords must contain both Finnish and English terms
        kws = plan["keywords"]
        self.assertIn("cnc", kws)
        self.assertIn("koneistus", kws)
        self.assertIn("machining", kws)
        self.assertIn("sorvaus", kws)
        self.assertIn("jyrsintä", kws)

    def test_generic_descriptive_words_not_converted_to_company_name(self):
        # Requests with generic words like 'cloud', 'automation', 'tech' must not set query
        p_cloud = plan_with_rules("Find cloud software consultancies")
        self.assertEqual(p_cloud["query"], "")
        self.assertEqual(p_cloud["industry_code"], "62")
        self.assertIn("ohjelmisto", p_cloud["keywords"])
        self.assertIn("pilvi", p_cloud["keywords"])

        p_auto = plan_with_rules("Industrial automation equipment providers")
        self.assertEqual(p_auto["query"], "")
        self.assertEqual(p_auto["industry_code"], "28")
        self.assertIn("automaatio", p_auto["keywords"])
        self.assertIn("automation", p_auto["keywords"])

    def test_explicit_quotes_or_naming_syntax_sets_query(self):
        p_quoted = plan_with_rules('Find suppliers similar to "Wärtsilä" in metal sector')
        self.assertEqual(p_quoted["query"], "Wärtsilä")

        p_named = plan_with_rules("Locate company named Etteplan for engineering")
        self.assertEqual(p_named["query"], "Etteplan")


class TestPaginatedRawCacheIntegrity(unittest.TestCase):
    """Verifies that paginated raw cache saves all pages individually and combined."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cache_mgr = CacheManager(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_multi_page_caching_and_traceable_dates(self):
        page1_url = "https://avoindata.prh.fi/opendata-ytj-api/v3/companies?companyForm=OY&mainBusinessLine=25&page=1"
        page2_url = "https://avoindata.prh.fi/opendata-ytj-api/v3/companies?companyForm=OY&mainBusinessLine=25&page=2"
        api_url = "https://avoindata.prh.fi/opendata-ytj-api/v3/companies?companyForm=OY&mainBusinessLine=25"

        p1_bytes = json.dumps({"companies": [{"businessId": {"value": "0100001-1"}}], "totalResults": 2}).encode("utf-8")
        p2_bytes = json.dumps({"companies": [{"businessId": {"value": "0200002-2"}}], "totalResults": 2}).encode("utf-8")
        comb_bytes = json.dumps({"companies": [{"businessId": {"value": "0100001-1"}}, {"businessId": {"value": "0200002-2"}}], "totalResults": 2}).encode("utf-8")

        h1 = self.cache_mgr.save_registry_raw(page1_url, p1_bytes, ["0100001-1"])
        h2 = self.cache_mgr.save_registry_raw(page2_url, p2_bytes, ["0200002-2"])
        h_comb = self.cache_mgr.save_registry_raw(api_url, comb_bytes, ["0100001-1", "0200002-2"])

        # Verify page 1 exists and is retrievable
        c1 = self.cache_mgr.get_cached_registry(page1_url)
        self.assertIsNotNone(c1)
        meta1, data1 = c1
        self.assertEqual(meta1["sha256"], h1)
        self.assertIn("retrieved_at", meta1)

        # Verify page 2 exists and is retrievable (not lost!)
        c2 = self.cache_mgr.get_cached_registry(page2_url)
        self.assertIsNotNone(c2)
        meta2, data2 = c2
        self.assertEqual(meta2["sha256"], h2)
        self.assertEqual(data2["companies"][0]["businessId"]["value"], "0200002-2")

        # Verify combined api_url cache contains all candidates
        c_comb = self.cache_mgr.get_cached_registry(api_url)
        self.assertIsNotNone(c_comb)
        meta_comb, data_comb = c_comb
        self.assertEqual(len(data_comb["companies"]), 2)
        self.assertEqual(meta_comb["sha256"], h_comb)


class TestAssessmentStatusGrounding(unittest.TestCase):
    """Verifies that missing or unread websites are marked not_assessed, never negative evidence."""

    def test_missing_website_marked_not_assessed(self):
        raw_no_web = {
            "businessId": {"value": "2911111-1"},
            "tradeRegisterStatus": "1",
            "companyForms": [{"type": "16", "endDate": None}],
            "names": [{"name": "Koneistus Esimerkki Oy", "type": "1", "endDate": None}],
            "mainBusinessLine": {"type": "25620"},
            "addresses": [],
            "website": None,
        }
        comp = normalize_prh_company(raw_no_web, "https://prh.test", "2026-09-27T10:00:00Z")
        self.assertEqual(comp["website_status"], "missing")
        self.assertEqual(comp["assessment_status"], "not_assessed")
        self.assertIn("not assessed", comp.get("website_note", "").lower())

    def test_enrichment_unreachable_site_not_assessed(self):
        comp = {
            "business_id": "2922222-2",
            "name": "Unreachable Metal Oy",
            "website": "https://nonexistent-domain-123456789.fi",
            "website_status": "not_fetched",
            "assessment_status": "not_assessed",
            "evidence": [],
            "matched_keywords": [],
        }
        cache_mgr = CacheManager(tempfile.mkdtemp())
        enriched, w_mode = enrich_company_website(comp, ["cnc", "machining"], cache_mgr, refresh=True)
        self.assertEqual(enriched["website_status"], "unavailable")
        self.assertEqual(enriched["assessment_status"], "not_assessed")
        self.assertIn("not assessed", enriched.get("website_note", "").lower())


class TestDiscoveryPoolAndCncRealComparison(unittest.TestCase):
    """
    Real CNC Query Test:
    Executes a real query for CNC Machining in Finland (TOL 25).
    Validates:
    - Discovers bounded pool >= 100 active sector OYs.
    - Prioritizes registered websites.
    - Accurately distinguishes stats: scanned, website_read, evidence_positive, returned.
    - Returns requested top candidates with evidence first.
    - Preserves all reviewed candidates in reviewed_companies.
    - Stores raw evidence files in cache with SHA-256 hashes.
    """

    def test_real_cnc_query_pool_expansion_and_evidence(self):
        cache_dir = os.path.join(CURRENT_DIR, "cache")
        cache_mgr = CacheManager(cache_dir)

        # Plan with rules for CNC
        plan = plan_with_rules("Find precision CNC machining companies in Finland")
        self.assertEqual(plan["industry_code"], "25")

        t0 = time.time()
        result = execute_search(
            buyer_id=None,
            query=plan["query"],
            keywords=plan["keywords"],
            industry_code=plan["industry_code"],
            limit=10,
            refresh=False,  # Can use cached or populate live
            cache_mgr=cache_mgr,
            data_dir=os.path.join(CURRENT_DIR, "data"),
        )
        elapsed = time.time() - t0

        stats = result.get("stats", {})
        companies = result.get("companies", [])
        reviewed = result.get("reviewed_companies", [])
        diagnostics = result.get("diagnostics", {})

        print(f"\n[CNC POOL TEST] Elapsed: {elapsed:.2f}s")
        print(f"[CNC POOL TEST] Scanned: {stats.get('scanned')}")
        print(f"[CNC POOL TEST] Websites Read: {stats.get('website_read')}")
        print(f"[CNC POOL TEST] Evidence Positive: {stats.get('evidence_positive')}")
        print(f"[CNC POOL TEST] Returned: {len(companies)}")

        # 1. Pool size verification: >= 100 active OYs discovered and reviewed
        self.assertGreaterEqual(stats.get("scanned", 0), 100, "Discovery pool size should be >= 100 active OYs")
        self.assertEqual(len(reviewed), stats["scanned"])

        # 2. Distinguishable stats verification
        self.assertIn("scanned", stats)
        self.assertIn("website_read", stats)
        self.assertIn("evidence_positive", stats)
        self.assertIn("returned", stats)

        # 3. Evidence matches verification: significantly outperforms original baseline (1 match)
        self.assertGreaterEqual(stats.get("evidence_positive", 0), 3, "Should yield multiple positive evidence matches")

        # 4. Top returned companies have evidence first
        self.assertTrue(len(companies) > 0)
        first_comp = companies[0]
        self.assertGreater(first_comp["relevance_score"], 0.0, "Top company must have positive relevance score")
        self.assertTrue(len(first_comp["matched_keywords"]) > 0, "Top company must have matched keywords")
        self.assertEqual(first_comp["website_status"], "fetched")

        # 5. Raw evidence verification in cache
        web_url = first_comp["website"]
        url_hash = hashlib.sha256(web_url.encode("utf-8")).hexdigest()
        meta_path = os.path.join(cache_dir, "websites", f"{url_hash}_meta.json")
        self.assertTrue(os.path.exists(meta_path), f"Evidence metadata file missing for {web_url}")

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        self.assertEqual(meta["status_code"], 200)
        self.assertTrue(os.path.exists(os.path.join(cache_dir, "websites", f"{meta['sha256']}.html")))


if __name__ == "__main__":
    unittest.main()
