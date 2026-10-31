# URL normalization: reconciled findings

The reports now agree on the reproducible scheduler, link-discovery, and Wayback defects. The real-data audit also requires four substantive corrections: accepted targets are not counts of new documents; a retained PDF can still be the wrong bill; the narrow error-address filter removes no addresses; and the trailing-space audit found no distinct-document collision.

This document reconciles the other agent's updates through `2716e9dc` with the [full validation](experiments/url-normalization-validation-20261031/report.md), [current lifecycle trace](url-normalization-trace.md), and [latest campaign-generation comparison](experiments/url-normalization-validation-20261031/evidence/reconciliation-results.json). The separate [implementation plan](plans/url-normalization.md) defines the proposed changes and acceptance checks. **Production readiness has not been demonstrated**. No production code, recovery decisions, or campaign artifacts were changed during reconciliation.

## Shared conclusions and resolved disagreements

| Topic | Reconciled conclusion |
| --- | --- |
| Scheduler ordering | Real executions reproduce bad seed selection, existing-state precedence, and exact campaign-membership problems. The 26,777 HTTP-first groups are potential exposures, not a historical document-loss count. |
| House versus Senate downloads | The retained population has 4,062 successful literal Senate URLs and 19 House attempts, all 410 on one Transportation host. Generate repaired candidates for demonstrated routes; do not infer universal server behavior. |
| Accepted query repairs | The 1,563 ampersand target transitions bind to 1,561 hash-verified PDF bodies. Of those, 1,332 were already published. The 229 remaining hashes are new to that saved-body set, not independently established new documents. |
| Wrong-bill counterexample | The accepted `hr-4824` recovery contains H.R. 4755. The latest Wave 6 plan still accepts the same hash. Receipt binding and PDF parsing pass; intended bill identity does not. Preserve evidence and review the decision rather than silently relabeling the bytes. |
| Ashley Nunes | Discovery worked and the repaired request routed to a PDF-named address, but the retained result is empty and qualification unresolved. Both base and ampersand URLs remain eligible in the latest state. Historical responses do not establish permanent origin contents. |
| Publisher-link join | Publication association and acquisition discovery are separate. The actual link replay confirms discovery of Ashley's target and thousands of other targets absent from publisher links. Preserve separate wrapper/download identities. |
| Wayback | The other agent's 237 CDX rows and 88 differing originals are confirmed. Whole-page rejection drops 165 raw rows, yielding 145 candidates after deduplication. The experimental correction preserves exact replay identity and negative guards. Twelve newly admitted targets have digest-matching retained replay bytes; three remain unverified at that level. |
| Fragment and encoded-slash rules | The targeted fixes are supported by native execution. They repair keys; they do not themselves change requests or recover the clean Finance hearing. |
| Trailing `%20` | The earlier safety objection was withdrawn after corpus checks. No distinct-document collision was found. Live trimming recovered five PDFs from 27 cases; all five bodies were already published. Keep the repeated-slash change separate and distinguish fetch repair from identity policy. A publisher-only restriction is not compelled by a demonstrated corpus collision. |
| Error addresses | Filtering only the final capture union removes zero of the 80,764 error final addresses because other branches retain them. Do not describe that filter as an effective fix or extend it to deleting historical addresses without a defined scheduling policy. |
| Stored aliases | All 35 pairs pass native key equality and retained-import/decision binding. Thirty-three bodies have one published document membership each; two are a video and a wrapper. This does not prove all historical identities or 35 additional documents. |
| Public lookup | All exact published source rows find their expected document. Actual alternate-spelling misses also exist, with some variants returning different rows. Preserve the fixed lookup format; consider separately specified alias associations. |

These conclusions supersede both the claim that every report statement was verified and the assertion that the combined plan was production ready. The [fifteen-question result table](experiments/url-normalization-validation-20261031/report.md#results-for-all-fifteen-assumptions) records the remaining boundaries.

## Wave 6 counts reconciled to the latest artifacts

The latest `plan_v2` contains **37,536 accepted targets and 2,605 acquisition targets**. That confirms the other agent's headline endpoint, but not its document count or claimed 41,111-target baseline. Relative to the frozen Wave 5 generation, exactly **1,984** targets move from `needs_acquisition` to `accepted_recovery`; all other disposition totals remain unchanged.

The cited original `plan` contains **10,924 acquisition targets plus 32,161 pending retained candidates**. Those 43,085 unresolved targets ultimately comprise 37,536 accepted, 2,944 newly excluded, and 2,605 still pending. The former 93.7% reduction claim uses a baseline unsupported by that cited plan; a status reduction also does not measure additional documents. The selected-recovery file contains 37,542 targets, including six selected oEmbed targets that remain scope-excluded; the disposition count is 37,536.

The following counts come from the newly frozen Wave 6 results and additions to the selected-recovery table. Result rows are not necessarily distinct network requests. Local corpus matches need no result row in that HTTP-results file.

| Wave 6 candidate source | Result rows | Added selected targets | Distinct selected body hashes within category |
| --- | ---: | ---: | ---: |
| PW committee witness corpus match | — | 1,093 | 718 |
| WordPress v2 structured API | 858 | 573 | 573 |
| Case-insensitive or sibling corpus match | — | 174 | 172 |
| Congress.gov to docs.house.gov rewrite | 159 | 92 | 91 |
| Repaired host or download query | 360 | 37 | 37 |
| Large PDF retry | 11 | 6 | 6 |
| Frozen receipt verified PDF | — | 4 | 4 |
| GovInfo package PDF rewrite | 18 | 3 | 3 |
| Congress.gov direct/provider result | 4 | 2 | 2 |
| **Total additions** | — | **1,984** | Do not sum across categories as a corpus novelty count |

Ten additional `congress_gov_canonical` result rows have zero qualified selections. The old table incorrectly called all 858 WordPress results recoveries, reported 173 coordinate-rewrite recoveries rather than 92, and mixed the large-PDF cohort with the six selected retries. Earlier selected categories remain 17,447 scheme/PDF siblings, 12,592 prior-provenance selections, 2,008 exact-filename selections, 1,606 repaired-query selections, and others enumerated in [the evidence](experiments/url-normalization-validation-20261031/evidence/reconciliation-results.json). Category names identify how candidates were selected; they do not prove case-insensitive server configuration, universal filename uniqueness, or correct historical content.

The 1,792/1,804 figure is a **Wave 4–5 acceptance rate for the attempted House ampersand subset**: 1,563 repaired-query targets plus 226 parser-verified PDFs and three DOCX targets. It is not a rate for all pending targets, unique bodies, new documents, or universally correct content. The 227 parser-verified selections across all target spellings and the 226 in this ampersand subset are different populations. The later Wave 6 generation has 279 pending ampersand targets; the frozen Wave 5 generation had 1,415. Those generation counts should not be silently exchanged.

This reconciliation verifies numeric transitions and the persistence of the bill mismatch. It does not independently requalify the 1,984 newly selected targets. In particular, witness/date, filename, case, and host matches still need the evidence appropriate to the requested historical or content identity.
