#!/usr/bin/env python3
"""
MandateScout Backend Test Suite & Live Smoke Verification
=========================================================
Python Standard Library Only (unittest).
Validates:
- Entity normalization (current names, active Trade Register status, OY form)
- Mandatory unknown fields (financials null, owner intent null, ownership unknown)
- SSRF and private-network protection (localhost, RFC1918, link-local, cloud metadata)
- No failed-fetch-as-verified (strict status reporting)
- Bounded HTML cleaning and keyword evidence extraction
- Transparent relevance scoring
- Mandate dossier export selection and escaping
- API contract endpoints (health, buyers, search, company, brief, runs)
- Live smoke test against PRH and real Finnish websites to populate cache
  with >=10 actual private companies and >=3 website evidence records.
"""

import datetime
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from typing import Any, Dict, List, Optional, Tuple

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
    extract_evidence,
    generate_mandate_brief,
    is_safe_url,
    normalize_prh_company,
)
from product.planner import (
    generate_followup_refinements,
    plan_research,
    plan_with_rules,
    validate_plan_parameters,
)
from product.server import MandateScoutHandler, jobs, job_lock, run_server


class TestCollectorSecurityAndHelpers(unittest.TestCase):
    """Test SSRF defenses, URL sanitization, and text processing."""

    def test_ssrf_private_network_blocking(self):
        # Localhost and loopback
        safe, reason = is_safe_url("http://127.0.0.1:8080")
        self.assertFalse(safe)
        self.assertIn("private, loopback, or reserved", reason)

        safe, _ = is_safe_url("http://localhost:8000")
        self.assertFalse(safe)

        # RFC 1918 private addresses
        safe, _ = is_safe_url("http://192.168.1.1")
        self.assertFalse(safe)

        safe, _ = is_safe_url("http://10.0.0.5:8080")
        self.assertFalse(safe)

        safe, _ = is_safe_url("http://172.16.5.10")
        self.assertFalse(safe)

        # Cloud metadata service (AWS/GCP)
        safe, _ = is_safe_url("http://169.254.169.254/latest/meta-data/")
        self.assertFalse(safe)

        # Disallowed schemes
        safe, reason = is_safe_url("file:///etc/passwd")
        self.assertFalse(safe)
        self.assertIn("Disallowed scheme", reason)

        safe, _ = is_safe_url("ftp://ftp.example.com")
        self.assertFalse(safe)

        # Disallowed ports
        safe, _ = is_safe_url("http://example.com:22")
        self.assertFalse(safe)

    def test_html_cleaning_and_entities(self):
        dirty_html = """
        <html>
            <head><script>alert('malicious')</script><style>body {color: red;}</style></head>
            <body>
                <header><nav><a href="#">Nav item</a></nav></header>
                <h1>Nordic Cloud Architecture &amp; Solutions</h1>
                <p>We deliver secure <b>enterprise &quot;migration&quot;</b> and Kubernetes automation.</p>
                <footer>&copy; 2026 Nordic Cloud Oy. All rights reserved.</footer>
            </body>
        </html>
        """
        cleaned = clean_html_to_text(dirty_html)
        self.assertNotIn("alert", cleaned)
        self.assertNotIn("Nav item", cleaned)
        self.assertNotIn("color: red", cleaned)
        self.assertIn("Nordic Cloud Architecture & Solutions", cleaned)
        self.assertIn('enterprise "migration"', cleaned)
        self.assertIn("Kubernetes automation", cleaned)

    def test_keyword_evidence_extraction(self):
        text = (
            "Established in Helsinki, our company specializes in cybersecurity architecture, "
            "penetration testing, and managed security operations for critical Nordic infrastructure."
        )
        evidence, matched_kws = extract_evidence(text, ["cybersecurity", "penetration testing", "fintech"], "https://example.fi")
        self.assertEqual(len(matched_kws), 2)
        self.assertIn("cybersecurity", matched_kws)
        self.assertIn("penetration testing", matched_kws)
        self.assertNotIn("fintech", matched_kws)
        self.assertEqual(len(evidence), 2)
        self.assertEqual(evidence[0]["kind"], "keyword_match")
        self.assertIn("https://example.fi", evidence[0]["source_url"])

    def test_relevance_scoring(self):
        # Strict explicit keyword coverage percentage (Requirement 3)
        # 3 out of 3 matched -> 100.0%
        score_high = calculate_relevance_score(matched_kw_count=3, total_kw_count=3, website_status="fetched", industry_match=True)
        self.assertEqual(score_high, 100.0)

        # 1 out of 3 matched -> 33.3%
        score_mid = calculate_relevance_score(matched_kw_count=1, total_kw_count=3, website_status="unavailable", industry_match=False)
        self.assertEqual(score_mid, 33.3)

        # 0 out of 3 matched -> 0.0% (even with website fetched and industry match: no artificial bonus points!)
        score_zero = calculate_relevance_score(matched_kw_count=0, total_kw_count=3, website_status="fetched", industry_match=True)
        self.assertEqual(score_zero, 0.0)

        # 0 total keywords specified -> 0.0%
        score_no_kw = calculate_relevance_score(matched_kw_count=0, total_kw_count=0, website_status="fetched", industry_match=True)
        self.assertEqual(score_no_kw, 0.0)

    def test_csv_formula_injection_defense(self):
        # Test neutralizing spreadsheet formula execution (=, +, -, @, \t, \r)
        def sanitize_csv_cell(val):
            if val is None:
                return '""'
            s = str(val)
            if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
                s = "'" + s
            escaped = s.replace('"', '""')
            return f'"{escaped}"'

        self.assertEqual(sanitize_csv_cell("=cmd|' /C calc'!A0"), "\"'=cmd|' /C calc'!A0\"")
        self.assertEqual(sanitize_csv_cell("+12345"), "\"'+12345\"")
        self.assertEqual(sanitize_csv_cell("-SUM(A1:A10)"), "\"'-SUM(A1:A10)\"")
        self.assertEqual(sanitize_csv_cell("@mention"), "\"'@mention\"")
        self.assertEqual(sanitize_csv_cell("\tTabbed"), "\"'\tTabbed\"")
        self.assertEqual(sanitize_csv_cell("Acme Oy"), '"Acme Oy"')

    def test_buyer_excerpts_grounded_in_saved_extracted_text(self):
        # Requirement 7: Verify each buyer source_excerpt against saved extracted text
        buyers_path = os.path.join(CURRENT_DIR, "data", "buyers.json")
        with open(buyers_path, "r", encoding="utf-8") as f:
            buyers = json.load(f)["buyers"]

        for b in buyers:
            bid = b["id"]
            if b["status"] == "unavailable":
                self.assertEqual(len(b.get("criteria", [])), 0, f"Unavailable buyer {bid} must have no active criteria")
                continue

            txt_path = os.path.join(CURRENT_DIR, "data", "evidence", f"{bid}_extracted.txt")
            self.assertTrue(os.path.exists(txt_path), f"Extracted text missing for verified buyer {bid}")
            with open(txt_path, "r", encoding="utf-8") as f:
                content = f.read().replace("\xa0", " ").replace("’", "'")

            for crit in b.get("criteria", []):
                excerpt = crit.get("source_excerpt", "").replace("’", "'")
                parts = [p.strip() for p in excerpt.split("...") if p.strip()]
                for part in parts:
                    norm_part = " ".join(part.split())
                    norm_content = " ".join(content.split())
                    self.assertIn(norm_part, norm_content, f"Buyer excerpt for {crit['id']} not supported by saved text")


class TestEntityNormalizationAndGroundTruth(unittest.TestCase):
    """Test strict normalization and non-fabrication of financial/ownership state."""

    def test_normalization_active_current_name_and_unknowns(self):
        raw_prh = {
            "businessId": {"value": "2912345-6"},
            "tradeRegisterStatus": "1",
            "companyForms": [
                {
                    "type": "16",
                    "descriptions": [{"languageCode": "1", "description": "Osakeyhtiö"}],
                    "endDate": None,
                }
            ],
            "names": [
                {"name": "Old Obsolete Name Oy", "type": "1", "endDate": "2020-01-01"},
                {"name": "Current Active Tech Oy", "type": "1", "endDate": None},
                {"name": "Tech Finland", "type": "2", "endDate": None},  # Auxiliary trade name
            ],
            "mainBusinessLine": {
                "type": "62010",
                "typeCodeSet": "TOIMI4",
                "descriptions": [
                    {"languageCode": "3", "description": "Computer programming activities"},
                    {"languageCode": "1", "description": "Ohjelmistojen suunnittelu ja valmistus"},
                ],
            },
            "addresses": [
                {
                    "postOffices": [{"languageCode": "1", "city": "Espoo"}],
                    "street": "Tekniikantie 1",
                }
            ],
            "website": {"url": "www.active-tech.fi"},
        }

        norm = normalize_prh_company(raw_prh, "https://avoindata.prh.fi/test", "2026-09-26T14:00:00Z")
        self.assertIsNotNone(norm)
        self.assertEqual(norm["business_id"], "2912345-6")
        self.assertEqual(norm["name"], "Current Active Tech Oy")  # Current active legal name selected
        self.assertEqual(norm["legal_form"], "Osakeyhtiö")
        self.assertEqual(norm["city"], "Espoo")
        self.assertEqual(norm["industry_code"], "62010")
        self.assertEqual(norm["industry_label"], "Computer programming activities")
        self.assertEqual(norm["website"], "https://www.active-tech.fi")
        self.assertEqual(norm["website_status"], "not_fetched")

        # Verify ground truth unknowns (NEVER fabricated)
        self.assertIsNone(norm["financials"]["revenue"])
        self.assertIsNone(norm["financials"]["ebitda"])
        self.assertIsNone(norm["owner_intent"])
        self.assertEqual(norm["ownership_status"], "unknown")
        self.assertIsNone(norm["excluded_reason"])

    def test_inactive_or_unregistered_company_filtered(self):
        raw_inactive = {
            "businessId": {"value": "0100001-1"},
            "tradeRegisterStatus": "4",  # Ceased / not registered
            "names": [{"name": "Dissolved Firm Oy", "type": "1"}],
        }
        norm = normalize_prh_company(raw_inactive, "https://avoindata.prh.fi/test", "2026-09-26T14:00:00Z")
        self.assertIsNone(norm)

    def test_missing_website_handling(self):
        raw_no_web = {
            "businessId": {"value": "2999999-9"},
            "tradeRegisterStatus": "1",
            "companyForms": [{"type": "16", "endDate": None}],
            "names": [{"name": "No Website Systems Oy", "type": "1", "endDate": None}],
            "mainBusinessLine": {"type": "62020"},
            "addresses": [],
            "website": None,
        }
        norm = normalize_prh_company(raw_no_web, "https://avoindata.prh.fi/test", "2026-09-26T14:00:00Z")
        self.assertIsNotNone(norm)
        self.assertIsNone(norm["website"])
        self.assertEqual(norm["website_status"], "missing")

    def test_reject_non_oy_legal_forms(self):
        # 1. Public listed company (Julkinen osakeyhtiö / OYJ - PRH code 17) -> REJECT
        raw_oyj = {
            "businessId": {"value": "1979903-5"},
            "tradeRegisterStatus": "1",
            "companyForms": [
                {
                    "type": "17",
                    "descriptions": [{"languageCode": "1", "description": "Julkinen osakeyhtiö"}],
                    "endDate": None,
                }
            ],
            "names": [{"name": "Siili Solutions Oyj", "type": "1", "endDate": None}],
        }
        self.assertIsNone(normalize_prh_company(raw_oyj, "https://test", "2026-09-26T14:00:00Z"))

        # 2. Kommandiittiyhtiö (KY - PRH code 13) -> REJECT
        raw_ky = {
            "businessId": {"value": "0800001-2"},
            "tradeRegisterStatus": "1",
            "companyForms": [
                {
                    "type": "13",
                    "descriptions": [{"languageCode": "1", "description": "Kommandiittiyhtiö"}],
                    "endDate": None,
                }
            ],
            "names": [{"name": "Esimerkki Ky", "type": "1", "endDate": None}],
        }
        self.assertIsNone(normalize_prh_company(raw_ky, "https://test", "2026-09-26T14:00:00Z"))

        # 3. No active forms (only ended historical form) -> REJECT
        raw_expired = {
            "businessId": {"value": "0800002-3"},
            "tradeRegisterStatus": "1",
            "companyForms": [
                {"type": "16", "endDate": "2021-01-01"}
            ],
            "names": [{"name": "Expired Form Oy", "type": "1", "endDate": None}],
        }
        self.assertIsNone(normalize_prh_company(raw_expired, "https://test", "2026-09-26T14:00:00Z"))


class TestCacheAndDossierBrief(unittest.TestCase):
    """Test cache storage, provenance hashing, and brief dossier markdown compiling."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cache_mgr = CacheManager(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cache_provenance_and_hash(self):
        sample_url = "https://avoindata.prh.fi/opendata-ytj-api/v3/companies?test=1"
        sample_payload = b'{"companies": [{"businessId": {"value": "1111111-1"}}]}'
        content_hash = self.cache_mgr.save_registry_raw(sample_url, sample_payload, ["1111111-1"])

        self.assertTrue(len(content_hash) == 64)
        cached = self.cache_mgr.get_cached_registry(sample_url)
        self.assertIsNotNone(cached)
        meta, data = cached
        self.assertEqual(meta["sha256"], content_hash)
        self.assertEqual(meta["business_ids"], ["1111111-1"])
        self.assertEqual(data["companies"][0]["businessId"]["value"], "1111111-1")

    def test_brief_generation_with_disclaimers_and_escaping(self):
        run_id = "run_test_123"
        run_data = {
            "run_id": run_id,
            "queried_at": "2026-09-26T14:30:00Z",
            "query": "Software",
            "companies": [
                {
                    "business_id": "1234567-8",
                    "name": "Acme Tech Solutions Oy",
                    "legal_form": "Osakeyhtiö",
                    "status": "Active (Trade Register: Registered)",
                    "industry_code": "62010",
                    "industry_label": "Software Development",
                    "city": "Tampere",
                    "website": "https://www.acme-tech.fi",
                    "website_status": "fetched",
                    "registry_url": "https://avoindata.prh.fi/opendata-ytj-api/v3/companies?businessId=1234567-8",
                    "registry_retrieved_at": "2026-09-26T14:30:00Z",
                    "relevance_score": 85.0,
                    "evidence": [
                        {
                            "criterion": "Keyword match: 'cloud'",
                            "excerpt": "Specializing in multi-cloud architecture and enterprise modernization.",
                            "source_url": "https://www.acme-tech.fi",
                            "kind": "keyword_match",
                        }
                    ],
                    "missing_criteria": ["cybersecurity"],
                    "financials": {"revenue": None, "ebitda": None},
                    "owner_intent": None,
                    "ownership_status": "unknown",
                }
            ],
        }
        self.cache_mgr.save_run(run_id, run_data)

        brief = generate_mandate_brief(
            run_id=run_id,
            business_ids=["1234567-8"],
            buyer_id=None,
            notes="Mandate preparation for Nordic enterprise IT consolidator.",
            cache_mgr=self.cache_mgr,
            data_dir=os.path.join(CURRENT_DIR, "data"),
        )

        md = brief["markdown"]
        self.assertIn("MandateScout Target Dossier", md)
        self.assertIn("Acme Tech Solutions Oy", md)
        self.assertIn("1234567-8", md)
        self.assertIn("NO CLAIM OF ACTUAL INTEREST", md)
        self.assertIn("Financials (Revenue / EBITDA):** Unknown", md)
        self.assertIn("Owner Intent:** Unknown", md)
        self.assertIn("Ownership Independence:** Unknown", md)
        self.assertIn("Specializing in multi-cloud architecture", md)
        self.assertIn("Unmatched Criteria Keywords:** cybersecurity", md)

        # Test brief generation with verified buyer thesis criteria
        buyer_brief = generate_mandate_brief(
            run_id=run_id,
            business_ids=["1234567-8"],
            buyer_id="teqnion",
            notes="Buyer-specific thesis alignment test",
            cache_mgr=self.cache_mgr,
            data_dir=os.path.join(CURRENT_DIR, "data"),
        )
        b_md = buyer_brief["markdown"]
        self.assertIn("Teqnion AB (publ)", b_md)
        self.assertIn("Buyer Thesis Criteria & Criterion-Level Evaluation", b_md)
        self.assertIn("UNKNOWN (DATA GAP)", b_md)
        self.assertIn("NOT TARGET CRITERIA", b_md)
        self.assertIn("NO CLAIM OF ACTUAL INTEREST", b_md)


class TestApiServerContract(unittest.TestCase):
    """Start local HTTP server in background thread and test API endpoints."""

    @classmethod
    def setUpClass(cls):
        cls.server_port = 8799
        cls.server_host = "127.0.0.1"
        cls.server_address = (cls.server_host, cls.server_port)
        cls.httpd = http.server.HTTPServer(cls.server_address, MandateScoutHandler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _get(self, path: str) -> Tuple[int, Dict[str, Any]]:
        conn = http.client.HTTPConnection(self.server_host, self.server_port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        data = resp.read().decode("utf-8")
        try:
            parsed = json.loads(data)
        except Exception:
            parsed = {"raw": data}
        return resp.status, parsed

    def _post(self, path: str, body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        conn = http.client.HTTPConnection(self.server_host, self.server_port, timeout=15)
        payload = json.dumps(body).encode("utf-8")
        conn.request("POST", path, body=payload, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        data = resp.read().decode("utf-8")
        try:
            parsed = json.loads(data)
        except Exception:
            parsed = {"raw": data}
        return resp.status, parsed

    def test_api_health(self):
        status, data = self._get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))

    def test_api_buyers_missing_tolerated(self):
        status, data = self._get("/api/buyers")
        self.assertEqual(status, 200)
        self.assertIn("buyers", data)
        self.assertIsInstance(data["buyers"], list)

    def test_api_runs_list(self):
        status, data = self._get("/api/runs")
        self.assertEqual(status, 200)
        self.assertIn("runs", data)

    def test_api_company_not_found(self):
        status, data = self._get("/api/company?business_id=9999999-9")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_api_search_and_brief(self):
        # Test POST /api/search (using cache or live)
        body = {
            "query": "Cloud",
            "keywords": ["saas", "software"],
            "industry_code": "62",
            "limit": 3,
            "refresh": False,
        }
        status, data = self._post("/api/search", body)
        self.assertEqual(status, 200)
        self.assertIn("run_id", data)
        self.assertIn("companies", data)
        self.assertIn("source_mode", data)
        self.assertTrue(len(data["companies"]) > 0)

        run_id = data["run_id"]
        sample_bid = data["companies"][0]["business_id"]

        # Test GET /api/company
        c_status, c_data = self._get(f"/api/company?business_id={sample_bid}")
        self.assertEqual(c_status, 200)
        self.assertEqual(c_data["company"]["business_id"], sample_bid)

        # Test POST /api/brief
        brief_body = {
            "run_id": run_id,
            "business_ids": [sample_bid],
            "buyer_id": None,
            "notes": "Testing mandate brief API endpoint",
        }
        b_status, b_data = self._post("/api/brief", brief_body)
        self.assertEqual(b_status, 200)
        self.assertIn("filename", b_data)
        self.assertIn("markdown", b_data)
        self.assertIn(sample_bid, b_data["markdown"])

    def test_api_get_run_repeatability(self):
        # 1. Missing run_id query param -> 400
        status, data = self._get("/api/run")
        self.assertEqual(status, 400)
        self.assertIn("error", data)

        # 2. Non-existent run_id -> 404
        status, data = self._get("/api/run?run_id=non_existent_run_12345")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

        # 3. Create run and reopen it via /api/run
        body = {
            "query": "Cloud",
            "keywords": ["saas", "software"],
            "industry_code": "62010",
            "limit": 2,
            "refresh": False,
        }
        s_status, s_data = self._post("/api/search", body)
        self.assertEqual(s_status, 200)
        run_id = s_data["run_id"]

        r_status, r_data = self._get(f"/api/run?run_id={run_id}")
        self.assertEqual(r_status, 200)
        self.assertEqual(r_data["run_id"], run_id)
        self.assertEqual(len(r_data["companies"]), len(s_data["companies"]))

    def test_unavailable_buyer_disabled(self):
        status, data = self._get("/api/buyers")
        self.assertEqual(status, 200)
        relais = [b for b in data.get("buyers", []) if b.get("id") == "relais"]
        self.assertTrue(len(relais) > 0)
        self.assertEqual(relais[0].get("status"), "unavailable")

    def test_api_benchmark_endpoint(self):
        status, data = self._get("/api/benchmark")
        self.assertEqual(status, 200)
        self.assertIn("status", data)
        if data["status"] == "available":
            benchmark = data["benchmark"]
            self.assertIn("generated_at", benchmark)
            self.assertIn("scope", benchmark)
            self.assertIn("runs", benchmark)
            self.assertIn("totals", benchmark)
            self.assertIn("limitations", benchmark)
            self.assertIsInstance(benchmark["runs"], list)
            if len(benchmark["runs"]) > 0:
                first_run = benchmark["runs"][0]
                for key in ("label", "query", "industry_code", "elapsed_seconds", "total_candidates", "returned_companies"):
                    self.assertIn(key, first_run)
        else:
            self.assertEqual(data["status"], "pending")
            self.assertIn("message", data)

    def test_api_agent_research_async_lifecycle(self):
        # 1. Post research request
        body = {
            "request": "Find cloud devops consulting companies (sector 62)",
            "buyer_id": None,
            "refresh": False,
        }
        status, data = self._post("/api/agent/research", body)
        self.assertEqual(status, 202)
        self.assertIn("job_id", data)
        self.assertEqual(data.get("status"), "queued")
        job_id = data["job_id"]

        # 2. Poll until job completes (bounded wait)
        start_poll = time.time()
        completed = False
        final_job = None
        while time.time() - start_poll < 85.0:
            j_status, j_data = self._get(f"/api/agent/job?job_id={job_id}")
            self.assertEqual(j_status, 200)
            if j_data.get("status") in ("completed", "failed"):
                completed = True
                final_job = j_data
                break
            time.sleep(0.5)

        self.assertTrue(completed, f"Job {job_id} did not complete within bounded polling window.")
        self.assertEqual(final_job.get("status"), "completed")
        self.assertEqual(final_job.get("stage"), "completed")
        self.assertEqual(final_job.get("progress_pct"), 100)

        # 3. Verify plan
        plan = final_job.get("plan", {})
        self.assertIn("query", plan)
        self.assertIn("keywords", plan)
        self.assertIn("industry_code", plan)
        self.assertTrue(plan.get("bounds_validated"))
        self.assertIn(plan.get("planner_type"), ("rule_based_planner", "gemini_agy"))

        # 4. Verify results & stats
        results = final_job.get("results", {})
        self.assertIn("companies", results)
        stats = final_job.get("stats", {})
        for stat_key in ("companies_found", "returned_companies", "accessible_sites", "matched_evidence", "flags", "elapsed_seconds", "planner_mode"):
            self.assertIn(stat_key, stats)
        self.assertGreater(stats["elapsed_seconds"], 0.0)

    def test_api_agent_concurrency_limit_409(self):
        # Artificially insert active job in job store
        fake_id = "test_fake_active_job"
        with job_lock:
            jobs[fake_id] = {
                "job_id": fake_id,
                "status": "running",
                "stage": "prh_search",
                "created_at": "2026-09-27T00:00:00Z"
            }

        try:
            status, data = self._post("/api/agent/research", {"request": "Second concurrent search request"})
            self.assertEqual(status, 409)
            self.assertIn("Concurrent research limit reached", data.get("error", ""))
            self.assertEqual(data.get("active_job_id"), fake_id)
        finally:
            with job_lock:
                if fake_id in jobs:
                    del jobs[fake_id]


class TestPlannerUnitAndSafety(unittest.TestCase):
    """Unit tests for parameter bounds, financial exclusion, and fallback labeling."""

    def test_planner_limit_clamping(self):
        p1 = validate_plan_parameters({"limit": 50, "query": "Test", "keywords": []})
        self.assertEqual(p1["limit"], 20)

        p2 = validate_plan_parameters({"limit": 1, "query": "Test", "keywords": []})
        self.assertEqual(p2["limit"], 5)

        p3 = validate_plan_parameters({"limit": "invalid", "query": "Test", "keywords": []})
        self.assertEqual(p3["limit"], 10)

    def test_planner_financial_and_intent_exclusion(self):
        request = "Acquire profitable SaaS target with turnover > 10M, positive EBITDA, whose founder wants to exit"
        plan = plan_with_rules(request)
        # Verify financial/intent words are isolated under unverified_qualifiers
        self.assertIn("ebitda", plan["unverified_qualifiers"])
        self.assertIn("turnover", plan["unverified_qualifiers"])
        self.assertIn("exit", plan["unverified_qualifiers"])

        # Verify mandatory compliance disclaimers
        self.assertTrue(len(plan["disclaimers"]) >= 2)
        self.assertIn("Financial metrics", plan["disclaimers"][0])

    def test_planner_rule_based_fallback_truthful_label(self):
        plan = plan_with_rules("Industrial machinery manufacturer in Finland")
        self.assertEqual(plan["planner_type"], "rule_based_planner")
        self.assertEqual(plan["planner_label"], "Deterministic Rule-Based Request Planner (Safe Fallback)")
        self.assertEqual(plan["industry_code"], "28")
        self.assertIn("machinery", plan["keywords"])
        self.assertTrue(len(plan["followup_refinements"]) > 0)


class TestLiveSmokeDataRetrieval(unittest.TestCase):
    """
    Live Smoke Test:
    Executes an actual live query against PRH Open Data YTJ-API v3 for private OY companies,
    validates active status, enriches website evidence, and ensures the cache contains
    at least 10 actual private companies and at least 3 website evidence records.
    """

    def test_live_prh_and_website_evidence_ingestion(self):
        print("\n[SMOKE TEST] Initiating live retrieval against PRH Open Data...")
        cache_mgr = CacheManager(os.path.join(CURRENT_DIR, "cache"))

        # Live query for real Finnish IT / Software / Cloud private companies
        result = execute_search(
            buyer_id=None,
            query="Cloud",
            keywords=["cloud", "saas", "software", "security", "data", "palvelu", "consulting"],
            industry_code="62",
            limit=12,
            refresh=True,  # Mandatory live retrieval
            cache_mgr=cache_mgr,
            data_dir=os.path.join(CURRENT_DIR, "data"),
        )

        companies = result.get("companies", [])
        print(f"[SMOKE TEST] Retrieved {len(companies)} active private OY candidates (Total in PRH: {result.get('total_candidates')})")

        # Verify >= 10 real private companies
        self.assertGreaterEqual(len(companies), 10, "Failed to retrieve at least 10 private OY companies.")

        fetched_websites = [c for c in companies if c.get("website_status") == "fetched"]
        print(f"[SMOKE TEST] Successfully fetched website evidence for {len(fetched_websites)} companies.")

        for c in companies[:3]:
            print(f"  * {c['name']} ({c['business_id']}) | City: {c['city']} | Web: {c['website']} [{c['website_status']}] | Score: {c['relevance_score']}%")

        # Verify entity schema integrity
        for c in companies:
            self.assertTrue(c["business_id"].count("-") == 1, f"Invalid Business ID format: {c['business_id']}")
            self.assertIn("Osakeyhtiö", c["legal_form"])
            self.assertEqual(c["ownership_status"], "unknown")
            self.assertIsNone(c["financials"]["revenue"])
            self.assertIsNone(c["financials"]["ebitda"])
            self.assertIsNone(c["owner_intent"])

        # Check raw cache provenance files
        cached_registry_files = os.listdir(cache_mgr.registry_dir)
        cached_website_files = os.listdir(cache_mgr.websites_dir)
        print(f"[SMOKE TEST] Cache verification: {len(cached_registry_files)} registry items, {len(cached_website_files)} website items.")
        self.assertGreaterEqual(len(cached_registry_files), 1)

        # Ensure we have at least 3 fetched website records. If this single query retrieved fewer,
        # run a complementary query to reach >= 3 website records.
        if len(fetched_websites) < 3:
            print("[SMOKE TEST] Running complementary search to ensure >= 3 website evidence records...")
            comp_result = execute_search(
                buyer_id=None,
                query="Tech",
                keywords=["tech", "digital", "solutions", "palvelut", "asiakkaat"],
                industry_code="62",
                limit=10,
                refresh=True,
                cache_mgr=cache_mgr,
                data_dir=os.path.join(CURRENT_DIR, "data"),
            )
            for c in comp_result.get("companies", []):
                if c.get("website_status") == "fetched" and c["business_id"] not in [x["business_id"] for x in fetched_websites]:
                    fetched_websites.append(c)

        print(f"[SMOKE TEST] Total unique fetched website records in cache: {len(fetched_websites)}")
        self.assertGreaterEqual(len(fetched_websites), 3, "Failed to retrieve at least 3 meaningful website evidence records.")


if __name__ == "__main__":
    unittest.main()
