#!/usr/bin/env python3
"""
MandateScout HTTP Server
========================
Python standard library HTTP server running on 127.0.0.1:8787.
Serves the MandateScout REST API and static frontend assets from product/static/.
"""

import datetime
import http.server
import json
import mimetypes
import os
import sys
import threading
import time
import urllib.parse
import uuid
from typing import Any, Dict, List, Optional

# Ensure parent directory is on Python path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from product.collector import (
    CacheManager,
    execute_search,
    generate_mandate_brief,
)
from product.planner import plan_research

HOST = "127.0.0.1"
PORT = 8787
STATIC_DIR = os.path.join(CURRENT_DIR, "static")
DATA_DIR = os.path.join(CURRENT_DIR, "data")
CACHE_DIR = os.path.join(CURRENT_DIR, "cache")
BENCHMARKS_FILE = os.path.join(PROJECT_ROOT, "benchmarks", "results.json")

cache_manager = CacheManager(CACHE_DIR)

# In-memory async research job store and lock (max 1 concurrent research)
job_lock = threading.Lock()
jobs: Dict[str, Dict[str, Any]] = {}


def get_active_job_id() -> Optional[str]:
    """Returns the ID of currently active job, if any."""
    with job_lock:
        for jid, job in jobs.items():
            if job.get("status") in ("queued", "running"):
                return jid
    return None


def run_agent_research_worker(
    job_id: str,
    request_text: str,
    buyer_id: Optional[str],
    refresh: bool
):
    """
    Background worker thread executing bounded research lifecycle:
    1. Planning: invokes planner with bounds and parameter validation.
    2. PRH Search & Website Enrichment: invokes allowlisted execute_search.
    3. Metrics & Scoring: records measured stats and final status.
    """
    start_time = time.perf_counter()
    with job_lock:
        if job_id not in jobs:
            return
        jobs[job_id]["status"] = "running"
        jobs[job_id]["stage"] = "planning"
        jobs[job_id]["stage_message"] = "Constructing bounded research parameters..."
        jobs[job_id]["progress_pct"] = 15

    try:
        # Step 1: Planning
        plan = plan_research(request_text, buyer_id=buyer_id, data_dir=DATA_DIR)
        # Fix obsolete consultancy suggestions 62200 -> 62020, 70200 -> 70220
        if plan.get("industry_code") == "62200":
            plan["industry_code"] = "62020"
        elif plan.get("industry_code") == "70200":
            plan["industry_code"] = "70220"
        if "followup_refinements" in plan and isinstance(plan["followup_refinements"], list):
            plan["followup_refinements"] = [
                r.replace("62200", "62020").replace("70200", "70220")
                for r in plan["followup_refinements"]
            ]
        with job_lock:
            jobs[job_id]["plan"] = plan
            jobs[job_id]["stage"] = "prh_search"
            jobs[job_id]["stage_message"] = (
                f"Querying PRH Trade Register (query='{plan.get('query')}', "
                f"industry='{plan.get('industry_code')}')"
            )
            jobs[job_id]["progress_pct"] = 30

        def progress_cb(stage: str, pct: int, msg: str):
            with job_lock:
                if job_id in jobs:
                    jobs[job_id]["stage"] = stage
                    jobs[job_id]["progress_pct"] = pct
                    jobs[job_id]["stage_message"] = msg

        # Step 2: Allowlisted PRH & Website Retrieval
        results = execute_search(
            buyer_id=buyer_id,
            query=plan.get("query", ""),
            keywords=plan.get("keywords", []),
            industry_code=plan.get("industry_code", ""),
            limit=plan.get("limit", 10),
            refresh=refresh,
            cache_mgr=cache_manager,
            data_dir=DATA_DIR,
            progress_callback=progress_cb,
        )

        elapsed = round(time.perf_counter() - start_time, 2)
        stats = results.get("stats", {})
        stats["elapsed_seconds"] = elapsed
        stats["planner_mode"] = plan.get("planner_label", "Deterministic Rule-Based Request Planner (Safe Fallback)")

        # Backend colleague compatibility & tolerance for historical runs
        if "reviewed_companies" not in results:
            results["reviewed_companies"] = results.get("companies", [])
        if "scanned_companies" not in stats:
            stats["scanned_companies"] = results.get("total_candidates", len(results.get("companies", [])))
        if "reviewed_companies" not in stats:
            stats["reviewed_companies"] = len(results.get("reviewed_companies", []))

        results["stats"] = stats
        results["planner"] = plan
        # Persist original request and limit in saved results
        results["request"] = request_text
        results["original_request"] = request_text
        results["limit"] = plan.get("limit", 10)
        cache_manager.save_run(results["run_id"], results)

        with job_lock:
            jobs[job_id]["status"] = "completed"
            jobs[job_id]["stage"] = "completed"
            jobs[job_id]["stage_message"] = "Research completed successfully."
            jobs[job_id]["progress_pct"] = 100
            jobs[job_id]["results"] = results
            jobs[job_id]["stats"] = stats
            jobs[job_id]["elapsed_seconds"] = elapsed

    except Exception as e:
        elapsed = round(time.perf_counter() - start_time, 2)
        with job_lock:
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["stage"] = "failed"
            jobs[job_id]["stage_message"] = f"Research failed: {str(e)}"
            jobs[job_id]["progress_pct"] = 100
            jobs[job_id]["error"] = str(e)
            jobs[job_id]["elapsed_seconds"] = elapsed


class MandateScoutHandler(http.server.BaseHTTPRequestHandler):
    """
    Handles API endpoints and static file distribution.
    """

    server_version = "MandateScout/1.0"

    def _set_cors_headers(self):
        self.send_header("Vary", "Origin")

    def _send_json(self, status_code: int, data: Any):
        payload = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(payload)

    def _send_error(self, status_code: int, message: str, details: Optional[str] = None):
        err_body: Dict[str, Any] = {"error": message}
        if details:
            err_body["details"] = details
        self._send_json(status_code, err_body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        query_params = urllib.parse.parse_qs(parsed.query)

        # 1. API: Health Check
        if path == "/api/health":
            self._send_json(200, {"ok": True})
            return

        # 2. API: Buyers Thesis & Criteria
        if path == "/api/buyers":
            buyers_file = os.path.join(DATA_DIR, "buyers.json")
            if os.path.exists(buyers_file):
                try:
                    with open(buyers_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        self._send_json(200, data)
                        return
                except Exception as e:
                    self._send_error(500, "Failed to read buyers database", str(e))
                    return
            else:
                # Tolerated: return empty buyers list without fabrication
                self._send_json(200, {"buyers": []})
                return

        # 3. API: Company by Business ID
        if path == "/api/company":
            bid = query_params.get("business_id", [None])[0]
            if not bid:
                self._send_error(400, "Missing required 'business_id' query parameter")
                return

            comp = cache_manager.get_company(bid.strip())
            if comp:
                self._send_json(200, {"company": comp})
            else:
                self._send_error(404, f"Company '{bid}' not found in active cache or past runs")
            return

        # 4. API: List Past Runs
        if path == "/api/runs":
            runs = cache_manager.list_runs()
            self._send_json(200, {"runs": runs})
            return

        # 5. API: Get Specific Run (for repeatability)
        if path == "/api/run":
            run_id = query_params.get("run_id", [None])[0]
            if not run_id:
                self._send_error(400, "Missing required 'run_id' query parameter")
                return

            run_data = cache_manager.get_run(run_id.strip())
            if run_data:
                # Tolerant of missing fields on historical runs
                if "reviewed_companies" not in run_data:
                    run_data["reviewed_companies"] = run_data.get("companies", [])
                if "stats" in run_data and isinstance(run_data["stats"], dict):
                    if "scanned_companies" not in run_data["stats"]:
                        run_data["stats"]["scanned_companies"] = run_data.get("total_candidates", len(run_data.get("companies", [])))
                    if "reviewed_companies" not in run_data["stats"]:
                        run_data["stats"]["reviewed_companies"] = len(run_data.get("reviewed_companies", []))
                # Prevent stale planner claim if planner was not used
                if not run_data.get("planner"):
                    run_data["planner"] = None
                    if "stats" in run_data and isinstance(run_data["stats"], dict):
                        pm = run_data["stats"].get("planner_mode")
                        if not pm or "Planner" in pm:
                            run_data["stats"]["planner_mode"] = "None (Direct Search)"
                self._send_json(200, run_data)
            else:
                self._send_error(404, f"Run '{run_id}' not found in saved runs")
            return

        # 6. API: Read-Only Empirical Benchmarks
        if path == "/api/benchmark":
            if os.path.exists(BENCHMARKS_FILE):
                try:
                    with open(BENCHMARKS_FILE, "r", encoding="utf-8") as f:
                        benchmark_data = json.load(f)
                    self._send_json(200, {"status": "available", "benchmark": benchmark_data})
                    return
                except Exception as e:
                    self._send_json(200, {"status": "error", "message": f"Failed to read benchmark file: {e}", "benchmark": None})
                    return
            else:
                self._send_json(200, {
                    "status": "pending",
                    "message": "Benchmark experiment results not yet generated by benchmark worker.",
                    "benchmark": None
                })
                return

        # 7. API: Agent Async Job Status
        if path == "/api/agent/job":
            job_id = query_params.get("job_id", [None])[0]
            if not job_id:
                self._send_error(400, "Missing required 'job_id' parameter")
                return
            with job_lock:
                job = jobs.get(job_id)
            if job:
                self._send_json(200, job)
            else:
                self._send_error(404, f"Job '{job_id}' not found")
            return

        # 8. API: Agent Recent Jobs
        if path == "/api/agent/jobs":
            with job_lock:
                job_list = [
                    {
                        "job_id": jid,
                        "created_at": j.get("created_at"),
                        "status": j.get("status"),
                        "stage": j.get("stage"),
                        "progress_pct": j.get("progress_pct"),
                        "elapsed_seconds": j.get("elapsed_seconds"),
                        "query": j.get("plan", {}).get("query") if j.get("plan") else None,
                    }
                    for jid, j in sorted(jobs.items(), key=lambda x: x[1].get("created_at", ""), reverse=True)
                ]
            self._send_json(200, {"jobs": job_list[:10]})
            return

        # 9. Static Files Serving
        if path.startswith("/api/"):
            self._send_error(404, f"API endpoint '{path}' not found")
            return

        self._serve_static(path)

    def do_POST(self):
        port = self.server.server_address[1]
        allowed_origins = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
        origin = self.headers.get("Origin")
        if origin and origin not in allowed_origins:
            self._send_error(403, "Research requests must originate from this local app")
            return
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            self._send_error(415, "Content-Type must be application/json")
            return
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path

        # Read JSON body safely
        content_length = self.headers.get("Content-Length")
        if not content_length:
            self._send_error(400, "Missing Content-Length header")
            return

        try:
            length = int(content_length)
            if length < 0 or length > 2 * 1024 * 1024:  # 2MB limit
                self._send_error(413, "Payload too large")
                return
            raw_body = self.rfile.read(length)
            body = json.loads(raw_body.decode("utf-8"))
            if not isinstance(body, dict):
                self._send_error(400, "Request body must be a JSON object")
                return
        except Exception as e:
            self._send_error(400, "Invalid JSON request body", str(e))
            return

        # 1. API: Search Candidates
        if path == "/api/search":
            query = str(body.get("query", "")).strip()
            keywords = body.get("keywords", [])
            if not isinstance(keywords, list):
                keywords = []
            industry_code = str(body.get("industry_code", "")).strip()
            # Fix obsolete consultancy suggestions 62200 -> 62020, 70200 -> 70220
            if industry_code == "62200":
                industry_code = "62020"
            elif industry_code == "70200":
                industry_code = "70220"

            buyer_id = body.get("buyer_id")
            limit = body.get("limit", 10)
            refresh = bool(body.get("refresh", False))

            try:
                limit = int(limit)
            except Exception:
                limit = 10

            req_text = body.get("request") or body.get("original_request")
            if not req_text:
                parts = []
                if query:
                    parts.append(f"query: {query}")
                if industry_code:
                    parts.append(f"industry: {industry_code}")
                if keywords:
                    parts.append(f"keywords: {', '.join(keywords)}")
                req_text = " / ".join(parts) if parts else "Direct search"

            try:
                results = execute_search(
                    buyer_id=buyer_id,
                    query=query,
                    keywords=keywords,
                    industry_code=industry_code,
                    limit=limit,
                    refresh=refresh,
                    cache_mgr=cache_manager,
                    data_dir=DATA_DIR,
                )
                # Persist original request and limit in saved results server
                results["request"] = req_text
                results["original_request"] = req_text
                results["limit"] = limit

                # Backend colleague compatibility & tolerance
                if "reviewed_companies" not in results:
                    results["reviewed_companies"] = results.get("companies", [])
                stats = results.get("stats", {})
                if "scanned_companies" not in stats:
                    stats["scanned_companies"] = results.get("total_candidates", len(results.get("companies", [])))
                if "reviewed_companies" not in stats:
                    stats["reviewed_companies"] = len(results.get("reviewed_companies", []))
                stats["planner_mode"] = "None (Direct Search)"
                results["stats"] = stats
                cache_manager.save_run(results["run_id"], results)

                self._send_json(200, results)
            except Exception as e:
                self._send_error(500, "Search execution failed", str(e))
            return

        # 2. API: Generate Dossier Brief
        if path == "/api/brief":
            run_id = body.get("run_id")
            if not run_id:
                self._send_error(400, "Missing required 'run_id' in brief request")
                return

            business_ids = body.get("business_ids", [])
            buyer_id = body.get("buyer_id")
            notes = body.get("notes", "")

            try:
                brief = generate_mandate_brief(
                    run_id=run_id,
                    business_ids=business_ids,
                    buyer_id=buyer_id,
                    notes=notes,
                    cache_mgr=cache_manager,
                    data_dir=DATA_DIR,
                )
                self._send_json(200, brief)
            except ValueError as e:
                self._send_error(404, str(e))
            except Exception as e:
                self._send_error(500, "Failed to compile brief dossier", str(e))
            return

        # 3. API: Async Agent Research Job (Max 1 Concurrent Research)
        if path == "/api/agent/research":
            req_text = str(body.get("request", "")).strip()
            if not req_text or len(req_text) > 2000:
                self._send_error(400, "Research request must contain 1 to 2000 characters")
                return
            buyer_id = body.get("buyer_id")
            refresh = bool(body.get("refresh", False))

            active_id = get_active_job_id()
            if active_id:
                self._send_json(409, {
                    "error": "Concurrent research limit reached (max 1). An active research job is already in progress.",
                    "active_job_id": active_id
                })
                return

            job_id = f"job_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
            now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

            new_job = {
                "job_id": job_id,
                "created_at": now_iso,
                "request": req_text,
                "buyer_id": buyer_id,
                "refresh": refresh,
                "status": "queued",
                "stage": "planning",
                "stage_message": "Job queued for research planner...",
                "progress_pct": 5,
                "plan": None,
                "results": None,
                "stats": None,
                "error": None,
                "elapsed_seconds": 0.0,
            }

            with job_lock:
                jobs[job_id] = new_job

            worker = threading.Thread(
                target=run_agent_research_worker,
                args=(job_id, req_text, buyer_id, refresh),
                daemon=True,
            )
            worker.start()

            self._send_json(202, {
                "job_id": job_id,
                "status": "queued",
                "created_at": now_iso,
                "message": "Research job queued and processing asynchronously."
            })
            return

        self._send_error(404, f"API endpoint '{path}' not found")

    def _serve_static(self, request_path: str):
        """
        Safely serves static assets from product/static/ with path traversal protection.
        """
        # Normalize request path
        cleaned = request_path.lstrip("/")
        if not cleaned or cleaned == "":
            cleaned = "index.html"
        elif cleaned.startswith("static/"):
            cleaned = cleaned[7:]

        # Secure path construction
        target_path = os.path.abspath(os.path.join(STATIC_DIR, cleaned))
        norm_static = os.path.abspath(STATIC_DIR)

        # Path traversal prevention
        if not target_path.startswith(norm_static):
            self._send_error(403, "Access denied: Path traversal outside static directory is forbidden")
            return

        if not os.path.exists(target_path) or os.path.isdir(target_path):
            if cleaned == "index.html":
                # Clean fallback if frontend agent has not placed index.html yet
                fallback_html = (
                    "<!DOCTYPE html><html><head><title>MandateScout Backend</title>"
                    "<style>body{font-family:sans-serif;padding:40px;line-height:1.6;max-width:800px;margin:auto}</style>"
                    "</head><body><h1>MandateScout Backend Active</h1>"
                    "<p>API services are running on <code>127.0.0.1:8787</code>.</p>"
                    "<ul>"
                    "<li><code>GET /api/health</code>: Health Check</li>"
                    "<li><code>GET /api/buyers</code>: Buyer Acquisition Theses</li>"
                    "<li><code>POST /api/search</code>: Live PRH &amp; Website Evidence Search</li>"
                    "<li><code>GET /api/company?business_id=...</code>: Company Detail</li>"
                    "<li><code>POST /api/brief</code>: Export Grounded Dossier</li>"
                    "<li><code>GET /api/runs</code>: Query Run History</li>"
                    "</ul>"
                    "<p>Frontend UI is loading from <code>product/static/index.html</code>.</p>"
                    "</body></html>"
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(fallback_html)))
                self._set_cors_headers()
                self.end_headers()
                self.wfile.write(fallback_html)
                return
            else:
                self._send_error(404, f"Static asset '{cleaned}' not found")
                return

        mime_type, _ = mimetypes.guess_type(target_path)
        if not mime_type:
            mime_type = "application/octet-stream"

        try:
            with open(target_path, "rb") as f:
                content = f.read()

            self.send_response(200)
            self.send_header("Content-Type", f"{mime_type}; charset=utf-8" if "text" in mime_type or "javascript" in mime_type or "json" in mime_type else mime_type)
            self.send_header("Content-Length", str(len(content)))
            self._set_cors_headers()
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self._send_error(500, "Failed to read static file", str(e))

    def log_message(self, format, *args):
        # Format logs concisely
        sys.stderr.write(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {format % args}\n")


def run_server(host: str = HOST, port: int = PORT):
    server_address = (host, port)
    httpd = http.server.HTTPServer(server_address, MandateScoutHandler)
    print(f"MandateScout Backend serving on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        httpd.server_close()


if __name__ == "__main__":
    port = PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    run_server(port=port)
