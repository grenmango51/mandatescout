# MandateScout — Backend Service & Provenance Engine

MandateScout is an M&A advisor research workbench backend for target identification and evidence assembly in the Finnish market.

Built exclusively using the **Python standard library** (zero third-party dependencies, zero paid APIs, zero credential requirements).

---

## 1. Quickstart & Execution

### Run the API Server
Start the HTTP server on `127.0.0.1:8787`:
```bash
python product/server.py
```
Or specify a custom port:
```bash
python product/server.py 8787
```

The server automatically serves:
* REST API endpoints under `/api/*`
* Static frontend files from `product/static/` (e.g. `index.html`, `app.js`, `style.css`)
* Path-traversal protected static asset delivery with MIME type deduction

### Run the Test Suite & Live Smoke Test
Execute full unit testing, SSRF security validation, and live PRH/website smoke retrieval:
```bash
python product/test_backend.py
```

---

## 2. API Contract Specification

### `GET /api/health`
* **Response `200`:** `{"ok": true}`

### `GET /api/buyers`
* **Response `200`:** `{"buyers": [...]}`
* Reads strategic buyer criteria from `product/data/buyers.json` if available.
* If absent, tolerates missing file and gracefully returns `{"buyers": []}` without crashing or fabricating fake profiles.

### `POST /api/search`
* **Request Body:**
  ```json
  {
    "buyer_id": "buyer-id-or-null",
    "query": "Cloud",
    "keywords": ["cloud", "saas", "software"],
    "industry_code": "62",
    "limit": 10,
    "refresh": false
  }
  ```
* **Response `200`:**
  ```json
  {
    "run_id": "run_20260926_145749_f78b35",
    "queried_at": "2026-09-26T14:57:49.123456Z",
    "source_mode": "live | cached",
    "elapsed_ms": 1420,
    "query": "Cloud",
    "total_candidates": 148,
    "companies": [
      {
        "business_id": "1740275-1",
        "name": "Cloud Center Finland Oy",
        "legal_form": "Osakeyhtiö",
        "status": "Active (Trade Register: Registered)",
        "industry_code": "62010",
        "industry_label": "Computer programming activities",
        "website": "https://www.cloudcenter.fi",
        "city": "LAHTI",
        "registry_url": "https://avoindata.prh.fi/opendata-ytj-api/v3/companies?businessId=1740275-1",
        "registry_retrieved_at": "2026-09-26T14:57:49Z",
        "website_status": "fetched",
        "website_retrieved_at": "2026-09-26T14:57:51Z",
        "website_source_url": "https://www.cloudcenter.fi",
        "evidence": [
          {
            "criterion": "Official Registration",
            "excerpt": "Officially registered Finnish Osakeyhtiö in LAHTI with primary business line 62010.",
            "source_url": "https://avoindata.prh.fi/opendata-ytj-api/v3/companies?businessId=1740275-1",
            "kind": "source_fact"
          },
          {
            "criterion": "Keyword match: 'cloud'",
            "excerpt": "...asiakkaillemme turvalliset cloud ratkaisut ja palvelut...",
            "source_url": "https://www.cloudcenter.fi",
            "kind": "keyword_match"
          }
        ],
        "matched_keywords": ["cloud"],
        "missing_criteria": ["saas"],
        "relevance_score": 68.6,
        "financials": {"revenue": null, "ebitda": null},
        "owner_intent": null,
        "ownership_status": "unknown",
        "excluded_reason": null
      }
    ],
    "warnings": [
      "Query term 'Cloud' was matched against PRH registered trade names and auxiliary names. Note: Registry name search does not scan free-text operational descriptions across the entire Finnish registry."
    ]
  }
  ```

### `GET /api/company?business_id={bid}`
* **Response `200`:** `{"company": {...}}`
* **Response `404`:** `{"error": "Company '...' not found in active cache or past runs"}`

### `POST /api/brief`
* **Request Body:**
  ```json
  {
    "run_id": "run_20260926_145749_f78b35",
    "business_ids": ["1740275-1"],
    "buyer_id": null,
    "notes": "Preparation for Nordic strategic acquirer mandate."
  }
  ```
* **Response `200`:**
  ```json
  {
    "filename": "mandate_dossier_run_20260926_145749_f78b35.md",
    "markdown": "# MandateScout Target Dossier..."
  }
  ```

### `GET /api/runs`
* **Response `200`:**
  ```json
  {
    "runs": [
      {
        "run_id": "run_20260926_145749_f78b35",
        "queried_at": "2026-09-26T14:57:49Z",
        "query": "Cloud",
        "count": 12,
        "source_mode": "live"
      }
    ]
  }
  ```

---

## 3. Data Pipeline & Provenance Architecture

```
[ Advisor Request ]
        │
        ├──> [ PRH YTJ-Api v3 ] (avoindata.prh.fi/opendata-ytj-api/v3/companies)
        │         │ Filter: companyForm=OY & tradeRegisterStatus=1 (active private OY)
        │         └──> Store raw JSON + SHA-256 hash in product/cache/registry/
        │
        └──> [ Website Evidence Fetcher ]
                  │ SSRF Validation (DNS check, block private/loopback/cloud metadata)
                  │ Normal TLS (ssl.create_default_context)
                  │ Max 1 MB stream, 7s timeout, polite delay
                  └──> Store raw HTML + SHA-256 hash in product/cache/websites/
                            │
                            └──> Clean HTML text & extract keyword snippets
```

* **Cache Directories:**
  * `product/cache/registry/`: `{sha256}.json` (raw API response) and `{url_hash}_meta.json` (URL, retrieval timestamp, business IDs, SHA-256 hash).
  * `product/cache/websites/`: `{sha256}.html` (raw captured page), `{sha256}_meta.json` (URL, final URL after safe redirects, HTTP status, timestamp, clean text).
  * `product/cache/runs/`: `{run_id}.json` (complete immutable record of search runs).

---

## 4. Security & Safety Defenses

1. **SSRF & Private Network Mitigation:**
   * Validates target hostnames via `socket.getaddrinfo`.
   * Rejects loopback (`127.0.0.0/8`, `::1`), private ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), link-local (`169.254.0.0/16`), multicast, and cloud metadata endpoints (`169.254.169.254`, `metadata.google.internal`).
   * Custom `SafeRedirectHandler` enforces the same SSRF validations on all HTTP redirect hops (max 3 hops).
2. **Resource Exhaustion Bounds:**
   * Response payload capped at 1 MB per website page.
   * Hard request timeout of 7 seconds.
3. **Strict Path Traversal Protection:**
   * Static file handler resolves canonical absolute paths and ensures all requests reside strictly inside `product/static/`.

---

## 5. Ground Truth & Market Scope Limitations

1. **Ownership Independence is Unknown:**
   * Registration as an `Osakeyhtiö (OY)` in the Finnish Trade Register indicates a private limited company, but does **not** prove independent ownership, founder-majority control, or absence of institutional backing.
   * `ownership_status` is explicitly set to `"unknown"`.
2. **Financial Data is Null:**
   * The public PRH Open Data API does not expose revenue, profit, or EBITDA figures without separate commercial or XBRL filings.
   * `financials: {"revenue": null, "ebitda": null}` is preserved as `null` and never fabricated.
3. **Owner Intent is Unknown:**
   * Public registers cannot determine whether owners are receptive to acquisition inquiries.
   * `owner_intent` is preserved as `null`.
4. **Scope of Registry Name Matching vs Full-Market Keyword Scan:**
   * PRH `/companies?name=...` matches registered legal and auxiliary trade names. It does **not** perform full-text indexing over companies' operational activities across the entire registry.
   * Transparent warnings are attached to all search responses to prevent misleading claims about whole-market discovery.
