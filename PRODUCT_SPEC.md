# MandateScout — real-data advisor workbench

Decision 26 September 2026 ~17:50 EEST. Replaces synthetic OwnerBridge.

One user: Mergero advisor preparing an evidence-backed opportunity for a prospective acquirer. Input: a public buyer thesis or explicit advisor keywords. Output: a shortlist of real Finnish entities with source evidence, gaps and downloadable brief for a mandate conversation. No participants/network required. Target discovery supports execution too; do not claim it creates signed mandates.

## Verified foundation
Parent successfully queried https://avoindata.prh.fi/opendata-ytj-api/v3/companies?name=Siili&companyForm=OYJ using normal TLS. Returned real entity 1979903-5, legal names, mainBusinessLine.type=62100, website.url=www.siili.fi and tradeRegisterStatus=1. Current taxonomy is TOIMI4, registration date 2026; do not label blindly TOL2008. This listed firm is a connector check, NOT an off-market target.

Research scripts are untrusted drafts: data/fetch_sources.py disables TLS and falls back to hardcoded signal snippets on failure. Do not reuse those behaviors or treat sample_signals as verified. Buyer thesis files need fresh source verification.

## Architecture and ownership
Python standard-library backend on 127.0.0.1:8787 serving static HTML/CSS/JS. No paid API, credentials, build tooling or native GPT subagents. Direct Gemini tasks with deterministic monitors.

Backend owner: product/server.py, product/collector.py, product/test_backend.py, product/README.md, product/requirements.txt if needed, product/cache/ only.
Frontend owner: product/static/ only.
Buyer evidence owner: product/data/buyers.json, product/data/evidence/, research/VERIFIED_FINDINGS.md only.
No agent modifies another's paths or prior prototype.

## API contract
GET /api/health -> {ok:true}
GET /api/buyers -> {buyers:[{id,name,source_url,retrieved_at,criteria:[{id,label,kind,source_excerpt,source_url}],keywords:[string],industry_codes:[string],status:'verified'|'unavailable'}]}
POST /api/search body {buyer_id:string|null,query:string,keywords:[string],industry_code:string,limit:number(1..20),refresh:boolean}
-> {run_id,queried_at,source_mode:'live'|'cached'|'mixed',elapsed_ms,query,total_candidates,companies:[Company],warnings:[string]}
Company {business_id,name,legal_form,status,industry_code,industry_label,website,city,registry_url,registry_retrieved_at,website_status:'fetched'|'unavailable'|'missing'|'not_fetched',website_retrieved_at,website_source_url,evidence:[{criterion,excerpt,source_url,kind:'source_fact'|'keyword_match'}],matched_keywords:[string],missing_criteria:[string],relevance_score:number,financials:{revenue:null,ebitda:null},owner_intent:null,ownership_status:'unknown',excluded_reason:null|string}
GET /api/company?business_id=... -> {company:Company} for last runs/cache, 404 if none.
POST /api/brief body {run_id,business_ids:[string],buyer_id,notes:string} -> {filename,markdown:string}. Build grounded dossier from stored results, no outbound messages or fabricated claims.
GET /api/runs -> {runs:[{run_id,queried_at,query,count,source_mode}]} optional if time.
Error -> {error:string,details?:string}, HTTP 4xx/5xx; never return demo/fake fallback results.

## Core behavior
Live PRH search by company name/keyword or validated official industry filter. Prefer active private OY for discovery, distinguish OYJ and known acquired examples. Do not equate OY with independent ownership. Normalize current names using type=1 and no endDate. Preserve current taxonomy identifiers. Exact Business ID is entity key. No invented source data. Save raw registry response and fetched website extract with URL/time/hash. Use registered websites only for enrichment; never guess domains. Missing sites and fetch failures are normal visible gaps.

Website evidence is bounded, respectful fetch with normal TLS, sensible timeouts/rate limits, no bypassing access controls. Block private/local destination addresses and redirects for website fetches. Extract meaningful text, not scripts/nav boilerplate. Match explicit buyer/advisor keywords with source excerpts; score describes research relevance only, not transaction probability or financial suitability. At most one homepage plus two relevant same-domain pages per candidate, bounded concurrency.

Live refresh genuinely reruns retrieval. Persist previous real runs for repeatability; clearly label cached data and original timestamp. No false freshness if provider fails. Limit=10 default, maximum20. Progress/loading and actual elapsed time visible. Download selected shortlist CSV and markdown dossier. Retain exclusion/gap evidence, unsupported financial criteria remain unknown.

## Interface
Concise, professional, usable at laptop width. Buyer selector + editable search terms/industry filter + Run research. Search results table names/sector/source coverage/relevance; click row opens evidence panel with clickable original sources and retrieval dates. Select rows then Export brief. Show real-data status and gaps compactly. No wall of explanations or fabricated KPIs. Starter actions use verified buyer records, not hardcoded synthetic companies.

## Acceptance
Run actual live queries returning at least 10 real PRIVATE entities and at least 3 fetched website evidence records (if access fails show failures honestly and choose another accessible sector/query). Prove changing query changes request/results. Verify source identity and one excerpt manually. Tests for normalization, unavailable sources, current names, unknown financials, score missing evidence, no failed-fetch-as-verified, private URL protection, export selection and escaping. Test backend API and browser interaction. Saved fetched records are acceptable fallback only when explicitly labelled historic cached evidence, never synthetic or live.
