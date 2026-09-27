# MandateScout — 90-second demo

Start with `python product/server.py`, then open http://127.0.0.1:8787.

**0–15 seconds — Job**
“One Mergero advisor needs a concrete reason to start a conversation with an acquirer. MandateScout gathers Finnish company records and public website evidence into a reviewable target brief.”

**15–40 seconds — Real search & discovery pool**
Run a sector search or the built-in starter search. Explain that buyer keywords and sector suggestions are analyst inputs.
“Company identities come from PRH. Multi-page retrieval discovers a bounded candidate pool of 100–200 active OYs, and 4 concurrent workers enrich registered websites in ~16s live with bilingual keyword heuristics. Here is the search details provenance bar showing the exact count of candidates scanned, websites read, and evidence matches found.”

**40–65 seconds — Qualify evidence & coverage toggle**
“MandateScout defaults to an evidence-backed shortlist view so advisors see actionable leads immediately, with a toggle (`#coverage-toggle`) to inspect all candidates. Open a company with a keyword excerpt. Follow its source link and compare the passage. This passage supports a research lead. It does not establish financial fit, independent ownership, or willingness to sell. Those still need advisor review.”

**65–90 seconds — Output and business use**
Select relevant companies and download the brief. Demonstrate job persistence: refreshing the browser seamlessly recovers any in-flight research job.
“The advisor can use this cited shortlist to propose a focused acquisition search. The commercial hypothesis is faster preparation for better buyer conversations. We would measure preparation time, qualified meetings and signed mandates in a pilot; we have not measured those outcomes yet.”

## Before presenting

- Verify system state with `python -m unittest product.test_relevance_pool product.test_backend product.test_ui_fixes product.test_deep_ingestion` (all 53 tests pass).
- Rehearse the current search; external sources can fail or change.
- Use a saved real run if needed and identify its original retrieval date.
- Do not describe keyword coverage as buyer fit or target availability.
- No outreach, MGX integration, customer pilot or signed mandate has occurred.

## Agent-first alternative

Type “Find precision CNC machining companies in Finland” and press Enter. Watch planning and retrieval stages: Gemini derives bilingual keywords (Finnish and English: koneistus, sorvaus, cnc) without injecting restrictive name filters, expands candidate discovery to 100–200 active OYs, and enriches websites in parallel (~9–16s live). While the earlier single-page run retrieved 10 companies, 3 accessible sites, and 1 match in 44.95s, the expanded relevance pool and Approach B deep ingestion surface 15 evidence-positive companies from 130+ scanned records (leveraging 1-hop subpages and Finnish compound word matching in ~2.2s cached / ~9.4s live). Open the measured experiment panel to compare the independent 45-company baseline benchmark (34.05s). In-flight jobs recover across browser reloads. Neither figure proves commercial results.
