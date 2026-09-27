# MandateScout

A local research workbench for one M&A advisor. Search real Finnish companies, inspect public website evidence, and export a shortlist for a prospective buyer conversation.

## Run

Requires Python 3.10+ and internet for new retrievals. No packages, API keys or payments.

On Windows, double-click **Start-MandateScout.cmd**. Alternatively run:

    python product/server.py

Open http://127.0.0.1:8787. Keep the terminal open. Ctrl+C stops the server.

1. Describe the companies you want and press Search, or click one of the examples. "Open a saved example" loads a previous search instantly. Buyer profiles, industry code and search words are under Advanced. In-flight research jobs automatically recover across browser reloads.
2. The interface defaults to an evidence-backed shortlist. Use the coverage toggle (Evidence matches vs All candidates) to switch scopes, and inspect the search provenance bar for candidate scan, crawl, and match statistics. Click a company to see what its website says, the source links and any "Check ownership" flag.
3. Tick companies, then use Export to download or copy a report, or download a spreadsheet.
4. Use "Past searches" to reopen earlier results.

Buyer keywords and industry codes are analyst suggestions. Website keyword coverage is not buyer fit. Corporate-change flags are text heuristics requiring review, not ownership determinations. PRH name search includes auxiliary and historical names; sector filters help narrow the results. Searches are bounded, not exhaustive market scans.

## Included

- `product/`: Python backend, browser interface, source cache and tests.
- `deliverables/mandatescout/pitch.html`: six-slide browser presentation; arrow keys navigate, S shows notes.
- `DEMO.md`: 90-second walkthrough.
- `deliverables/mandatescout/example-brief.md`: actual retrieved research example, not a qualified acquisition target.
- `deliverables/mandatescout/PARENT_QA.md`: verified checks and limitations.

## Data boundaries

Real identity data comes from PRH Open Data; website evidence comes from registered domains. Buyer criteria cite saved public company pages. Raw captures retain URLs, timestamps and hashes. Cached records are historical observations and can become stale.

Revenue, EBITDA, ownership independence, owner willingness and buyer interest are unverified. Some websites cannot be retrieved. No outreach, MGX integration, customer pilot or signed mandate has occurred. Commercial value remains a hypothesis to test with an advisor.

## Checks

    python -m unittest product.test_relevance_pool product.test_backend product.test_ui_fixes product.test_deep_ingestion

Fifty-three tests passed in review, validating bounded candidate pool expansion, 4-worker concurrent website enrichment, Approach B deep ingestion (1-hop internal link discovery and Finnish compound/morphological matching), bilingual keyword heuristics, SSRF defense, static asset security, in-flight job recovery, and live PRH/website smoke checks. Network-dependent tests require source availability. Test fixtures are isolated from demo data. The app binds only to this computer; public deployment would require additional authentication and operational hardening.

## Research agent and measured experiment

On this machine, natural-language planning uses the installed, authenticated AGY CLI with Gemini 3.8 Flash High. Planning runs with plan mode, sandbox restrictions and a 60-second limit. Only validated search parameters reach the collector. No model-generated shell commands are executed by the app. On machines without AGY, a clearly labelled rule-based planner provides deterministic sector/name parsing and bilingual keyword expansion (Finnish and English, e.g. "koneistus", "sorvaus", "cnc"), preventing generic terms from acting as restrictive registry name filters. Structured filters remain available. Model access depends on the local AGY account and quota; the package does not provide an API key or paid credits.

The pipeline incorporates bounded candidate pool expansion (discovering 100–200 active current-sector OYs across multi-page PRH queries), 4-worker concurrent website crawling, and Approach B deep ingestion (1-hop priority subpage discovery and Finnish compound word & morphological matching). In a verified CNC query comparison, this shifted output from the initial single-page 10-candidate baseline (10 scanned / 3 websites read / 1 match in 44.95s) to 130+ scanned OYs, 20+ websites read, and 15 evidence-positive candidates in ~2.2s cached / ~9.4s live (a 50% increase in evidence density over the single-homepage baseline). In-flight research jobs persist across browser reloads via session state recovery and conflict re-attachment.

A separate live three-scenario benchmark returned 45 unique companies, 18 accessible websites and six companies with keyword evidence in 34.05 seconds. Read benchmarks/RESULTS.md and results.json for denominators and limitations. These are retrieval metrics, not qualified leads or mandates. Open "How it works" in the app's footer to see them.
