#!/usr/bin/env python3
"""
UI Resiliency, Static Assets, and API Integration Regression Tests
==================================================================
Tests MandateScout server fixes:
1. Obsolete consultancy code remapping (62200 -> 62020, 70200 -> 70220).
2. Saved run request & limit persistence.
3. Tolerance of missing fields on historical runs (reviewed_companies, scanned_companies).
4. Prevention of stale planner claims on direct search runs.
5. Safe static asset serving and path traversal protection.
6. Async research concurrency protection (409 with active_job_id).
"""

import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from typing import Any, Dict, Tuple

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from product.collector import CacheManager
from product.server import (
    MandateScoutHandler,
    cache_manager,
    get_active_job_id,
    job_lock,
    jobs,
    run_agent_research_worker,
)


class TestUiFixesAndServerContract(unittest.TestCase):
    """Focused regression test suite for server fixes and UI contract."""

    @classmethod
    def setUpClass(cls):
        # Bind to port 8798 to avoid conflicting with other running test suites
        cls.server_port = 8798
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

    def setUp(self):
        # Clear jobs between tests
        with job_lock:
            jobs.clear()

    def _get(self, path: str) -> Tuple[int, bytes, Dict[str, str]]:
        conn = http.client.HTTPConnection(self.server_host, self.server_port, timeout=5)
        conn.request("GET", path)
        res = conn.getresponse()
        data = res.read()
        headers = dict(res.getheaders())
        conn.close()
        return res.status, data, headers

    def _get_json(self, path: str) -> Tuple[int, Dict[str, Any]]:
        status, data, _ = self._get(path)
        try:
            parsed = json.loads(data.decode("utf-8"))
        except Exception:
            parsed = {}
        return status, parsed

    def _post_json(self, path: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        conn = http.client.HTTPConnection(self.server_host, self.server_port, timeout=10)
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
            "Origin": f"http://127.0.0.1:{self.server_port}",
        }
        conn.request("POST", path, body=body, headers=headers)
        res = conn.getresponse()
        data = res.read()
        conn.close()
        try:
            parsed = json.loads(data.decode("utf-8"))
        except Exception:
            parsed = {}
        return res.status, parsed

    # 1. Static Asset Serving Tests
    def test_serve_index_html_at_root(self):
        status, data, headers = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        self.assertIn(b"MandateScout", data)
        self.assertIn(b"btn-view-evidence", data)
        self.assertIn(b"search-details", data)

    def test_serve_static_app_js(self):
        status, data, headers = self._get("/static/app.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers.get("Content-Type", ""))
        self.assertIn(b"apiFetch", data)
        self.assertIn(b"SESSION_JOB_KEY", data)

    def test_serve_static_styles_css(self):
        status, data, headers = self._get("/static/styles.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers.get("Content-Type", ""))
        self.assertIn(b"search-details", data)
        self.assertIn(b"coverage-toggle", data)

    def test_static_path_traversal_protection(self):
        # Attempting to read server.py outside static directory
        status, _, _ = self._get("/../server.py")
        self.assertIn(status, [403, 404])

        status, _, _ = self._get("/static/../../server.py")
        self.assertIn(status, [403, 404])

    # 2. Obsolete Consultancy Code Remapping (62200 -> 62020, 70200 -> 70220)
    def test_direct_search_remaps_obsolete_codes(self):
        # Verify 62200 remapped to 62020 on /api/search
        status, resp = self._post_json(
            "/api/search",
            {"query": "Consulting", "industry_code": "62200", "limit": 2}
        )
        self.assertEqual(status, 200)
        self.assertEqual(resp.get("industry_code"), "62020")

        # Verify 70200 remapped to 70220 on /api/search
        status, resp = self._post_json(
            "/api/search",
            {"query": "Advisory", "industry_code": "70200", "limit": 2}
        )
        self.assertEqual(status, 200)
        self.assertEqual(resp.get("industry_code"), "70220")

    def test_worker_remaps_obsolete_codes_and_refinements(self):
        # Direct verification of worker code remapping logic
        test_job_id = "test_remap_job"
        with job_lock:
            jobs[test_job_id] = {
                "job_id": test_job_id,
                "status": "queued",
                "request": "IT consultancy",
                "buyer_id": None,
                "refresh": False,
            }

        # Run worker with request that evokes IT consultancy
        run_agent_research_worker(test_job_id, "IT consultancy services in Helsinki", None, False)

        with job_lock:
            job = jobs[test_job_id]

        self.assertEqual(job["status"], "completed")
        plan = job.get("plan", {})
        self.assertNotEqual(plan.get("industry_code"), "62200")
        if plan.get("industry_code") in ["62020", "70220"]:
            self.assertIn(plan.get("industry_code"), ["62020", "70220"])
        # Check followup refinements
        for ref in plan.get("followup_refinements", []):
            self.assertNotIn("62200", ref)
            self.assertNotIn("70200", ref)

    # 3. Saved Run Request and Limit Persistence
    def test_search_persists_request_and_limit(self):
        custom_request = "B2B SaaS Helsinki high growth"
        status, resp = self._post_json(
            "/api/search",
            {
                "query": "Software",
                "industry_code": "62020",
                "keywords": ["saas", "cloud"],
                "limit": 5,
                "request": custom_request
            }
        )
        self.assertEqual(status, 200)
        run_id = resp.get("run_id")
        self.assertTrue(run_id)
        self.assertEqual(resp.get("request"), custom_request)
        self.assertEqual(resp.get("limit"), 5)

        # Retrieve saved run via /api/run and verify persistence
        status, saved = self._get_json(f"/api/run?run_id={run_id}")
        self.assertEqual(status, 200)
        self.assertEqual(saved.get("request"), custom_request)
        self.assertEqual(saved.get("limit"), 5)

    # 4. Tolerance of Missing Fields on Historical Runs in GET /api/run
    def test_historical_run_tolerance_missing_fields(self):
        # Create an artificial historical run lacking reviewed_companies and scanned_companies
        hist_run_id = "hist_run_legacy_12345"
        legacy_data = {
            "run_id": hist_run_id,
            "queried_at": "2025-01-01T12:00:00Z",
            "source_mode": "cached",
            "query": "Legacy Oy",
            "industry_code": "62020",
            "total_candidates": 3,
            "companies": [
                {"business_id": "1111111-1", "name": "Alpha Oy", "status": "Active", "relevance_score": 1.0},
                {"business_id": "2222222-2", "name": "Beta Oy", "status": "Active", "relevance_score": 0.5},
            ],
            # Deliberately missing reviewed_companies
            "stats": {
                "elapsed_seconds": 1.2,
                # Deliberately missing scanned_companies and reviewed_companies
            }
        }
        cache_manager.save_run(hist_run_id, legacy_data)

        status, resp = self._get_json(f"/api/run?run_id={hist_run_id}")
        self.assertEqual(status, 200)
        # Should gracefully backfill reviewed_companies from companies
        self.assertIn("reviewed_companies", resp)
        self.assertEqual(len(resp["reviewed_companies"]), 2)
        # Should gracefully backfill scanned_companies and reviewed_companies in stats
        self.assertIn("scanned_companies", resp["stats"])
        self.assertEqual(resp["stats"]["scanned_companies"], 3)
        self.assertIn("reviewed_companies", resp["stats"])
        self.assertEqual(resp["stats"]["reviewed_companies"], 2)

    # 5. Stale Planner Claim Prevention
    def test_direct_search_no_stale_planner_claim(self):
        status, resp = self._post_json(
            "/api/search",
            {"query": "Consulting", "industry_code": "62020", "limit": 2}
        )
        self.assertEqual(status, 200)
        run_id = resp.get("run_id")

        # GET /api/run
        status, run_data = self._get_json(f"/api/run?run_id={run_id}")
        self.assertEqual(status, 200)
        self.assertIsNone(run_data.get("planner"))
        self.assertEqual(run_data.get("stats", {}).get("planner_mode"), "None (Direct Search)")

    # 6. Concurrency Protection & 409 Active Job Reconnection
    def test_concurrent_research_returns_409_with_active_job_id(self):
        active_id = "job_mock_running_999"
        with job_lock:
            jobs[active_id] = {
                "job_id": active_id,
                "status": "running",
                "stage": "prh_search",
                "progress_pct": 50,
                "created_at": "2026-09-27T10:00:00Z"
            }

        # Attempting another research request should return 409 Conflict with active_job_id
        status, resp = self._post_json(
            "/api/agent/research",
            {"request": "Another query while one is running"}
        )
        self.assertEqual(status, 409)
        self.assertEqual(resp.get("active_job_id"), active_id)

        # GET /api/agent/job can retrieve this active job
        status, job_data = self._get_json(f"/api/agent/job?job_id={active_id}")
        self.assertEqual(status, 200)
        self.assertEqual(job_data.get("job_id"), active_id)
        self.assertEqual(job_data.get("status"), "running")


if __name__ == "__main__":
    unittest.main()
