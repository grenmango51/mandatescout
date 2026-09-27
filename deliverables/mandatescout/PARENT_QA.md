# Parent acceptance checks — 2026-09-26 23:35 EEST

- All direct Gemini workers completed; no native GPT subagents launched this turn.
- Parent reran 20 tests: passed in 21.7 seconds. Live smoke retrieved 12 private OY records and six accessible company websites.
- Browser starter query initially failed with stale sector62010. Corrected to62; verified10 real entities, sources, keyword evidence and mixed-cache status.
- Live Teqnion sector25 request returned five entities, one accessible website, 10763 total provider candidates. This bounded sample is not a complete market screen.
- Browser selected one company, downloaded Markdown dossier; verified actual file and one-company contents. CSV downloaded and verified locally.
- Saved run reopened with original timestamp and CACHED badge. Fixed prior misleading LIVE badge on historical reopening.
- Parent matched all13 full buyer excerpts to saved source text after correcting Sponsor partnership excerpt. Exact matches verify extraction, not the truth of corporate claims.
- Independently opened Cloud Center website and verified cited text. Website describes combination with Comspot. Added heuristic corporate-change review flag, verified through collector and included in export.
- Corrected wording that previously asserted no mandate existed. Status is unknown.
- Fixed desktop grid overflow; table retains its own horizontal scroll for narrow screens.
- Pitch is portable HTML, not PowerPoint. All six slides visually inspected in browser; arrow-key navigation verified. Print output has not been checked.

## Practical limits

Website snippets may include navigation, outdated branding or statements about other entities. Finnish/English keyword matching is lexical, not semantic. Registered websites may be stale. Financials, independent ownership and transaction willingness require additional evidence. Broad discovery returns a bounded provider-ordered sample and may miss good companies. No business outcome has been demonstrated.


## 27 September agent and experiment acceptance

Both direct Gemini jobs completed cleanly. Parent corrected too-short planner timeout to60seconds, enabled plan mode and sandbox flags, fixed UTF-8 subprocess decoding, and validated actual Gemini JSON output. Interactive browser request job_20260927_020052_f2d912 completed using gemini_agy:10 researched companies,3 accessible sites,1 company with keyword evidence,44.95seconds; mixedlive/cache. Saved proof:agent-run.json. Browser execution verified via Enter; pointer clicks through the in-app automation surface were inconclusive.

Parent reran26 tests:allpassed in71.071seconds. Follow-up planner/normalization unitchecks7passed aftercurrentcodecorrection. Origin restrictions reject external-site research requests; no cross-origin access is advertised. Request refinements preserve prior context. Historicmetricsarelabelledrecorded; stale developmentrunsarchivedoutsideproduct.

Initial benchmark revealed4wrongcurrentsectorresults. Addedlocalprefixfilter toproductandsnapshot, reranall3scenarioslive, and independentlyrecomputed45uniquecompanies,18fetchedsites,6keywordmatches,1flag fromsavedruns. Everycurrentindustrycodematchesrequestedprefix. Provider totalcandidatecountisbroaderthanlocalfilter; itisnotresearchedcount. UI nowshowsreturnedresearchedcount.

No outreach, paidAPI, billingconfiguration, submission or newnativeGPTagents.

Final package check: extracted ZIP into an isolated directory and started its server on8792. Health,5buyerprofiles,45-company benchmark and2auditedsavedruns passed. Final local API also rejected emptyrequests400,externalOrigin403,andnonobjectJSON400. Package excludes AGY sessions, credentials, oldsyntheticdemo and developmentrunhistory. No public deployment tested.
