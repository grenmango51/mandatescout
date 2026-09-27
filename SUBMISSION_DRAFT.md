# Submission email draft — NOT SENT

To: timo.tontti@mergero.com; tatu.nordback@mergero.com
Cc: meri.heikkinen@aaltoes.com; olivia.ronnemaa@aaltoes.com
Subject: POWER RANGERS — MandateScout — Mergero challenge
Attachments: MandateScout-review.zip (package), MandateScout-review-receipt.json (checksum receipt)

Hello,

Our submission is MandateScout, a local workbench for one advisor preparing an acquisition-search proposal for a prospective buyer.

The app uses Gemini to plan bounded research requests, expands multi-page queries to discover a bounded candidate pool of 100–200 active Finnish Osakeyhtiö (OY) records from PRH, conducts 4-worker concurrent enrichment with Approach B deep ingestion (1-hop internal link discovery and Finnish compound word / morphological matching), and extracts verified text excerpts with dates and source URLs. Bilingual keyword heuristics (Finnish and English) prevent generic terminology from acting as restrictive registry name filters. Advisors can inspect an evidence-backed shortlist by default or switch view scopes via the Evidence vs. All Candidates toggle, verify scan/read/match metrics via the search provenance bar, and recover in-flight research jobs across browser reloads. Public buyer criteria are displayed alongside explicit qualification gaps, and corporate-change flags highlight records needing ownership verification.

The deliverable ZIP includes the runnable Python application, six-slide HTML pitch deck, 90-second demo script, empirical benchmark artifacts, source captures, and real saved runs. Start with README.md or Start-MandateScout.cmd. Structured research runs with zero API keys or external dependencies. Gemini planning uses an installed, authenticated AGY CLI; without it, the app explicitly labels its deterministic rule-based fallback.

Fifty-three unit and integration tests passed (`python -m unittest product.test_relevance_pool product.test_backend product.test_ui_fixes product.test_deep_ingestion`). We verified browser search, candidate pool expansion, concurrent website crawling, Approach B deep ingestion (1-hop subpages and Finnish morphological matching), source inspection, saved-run reopening, Markdown dossier download, and Excel-compatible CSV export. Financial fit, ownership independence, and transaction interest remain unverified (explicitly reported as null/unknown). No cold outreach, signed mandates, or MGX integration are claimed. Across empirical benchmarks, the initial 3-sector baseline retrieved 45 unique companies, 18 accessible websites, and 6 keyword-evidence companies in 34.05s; with candidate pool expansion and Approach B deep ingestion, a targeted CNC query scans 130+ active OYs, inspects 20+ websites, crawls 20+ priority subpages, and delivers 15 evidence-positive matches in ~2.2s cached / ~9.4s live (a 50% increase in evidence density over the single-homepage baseline). These represent verifiable retrieval and extraction metrics. The proposed next step is a 30-day advisor pilot measuring preparation cycle time, fact accuracy, and qualified mandate conversations.

Best,
POWER RANGERS

---
This is a review draft. Explicit user authorization is required before sending or marking the event submission complete. Nothing has been sent.

