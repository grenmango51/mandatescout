# Measured collector experiment — 27 September 2026

The corrected live run queried three scenarios, 15 active private OY entities each. Current PRH sector codes were checked locally after retrieval because the provider's filter also returned records outside the requested current prefix.

- Cloud / sector62: 15 companies, 9 accessible websites, 4 companies with keyword excerpts, 1 corporate-change review flag;14.70 seconds.
- Metal products / sector25:15 companies,6 accessible websites,1 company with keyword excerpts;12.02 seconds.
- Machinery / sector28:15 companies,3 accessible websites,1 company with keyword excerpts;7.34 seconds.

Total:45 unique companies,18 accessible websites (40%),6 companies with keyword evidence (13.3% of returned companies),1 review flag;34.05 seconds summed execution time. Results are a bounded provider-ordered sample, not a representative market estimate. These are collection metrics, not qualified leads, time saved against a human baseline, or mandates.

## Reproduce and audit

Run `python benchmarks/run_benchmark.py`. The isolated collector snapshot, source HTML/JSON, metadata and complete runs are in benchmarks/. `results.json` identifies the three exact runs and original retrieval times. Network availability changes coverage and timing.

Parent recomputed totals from the saved company records and checked all current industry codes against requested prefixes. Earlier pre-fix results are retained separately for traceability and are superseded.

Source checks included Cloud Center's corporate-combination wording, Amak's machining wording, Asetekno's accessible site with no keyword evidence, Tascomm's inaccessible registered site, and Fincoil's missing registered website in the machinery sample. Website wording still needs human interpretation; source accessibility is not suitability.

## Limits

No revenue, EBITDA, ownership independence or transaction willingness was established. Registry name searches include auxiliary and historical names. Registered websites can be missing, stale or inaccessible. Lexical Finnish/English keywords miss synonyms and can match irrelevant text. The collector is bounded and does not examine every provider candidate. Financial qualification and a controlled advisor comparison are future experiments.
