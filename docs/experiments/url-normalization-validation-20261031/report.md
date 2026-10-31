# URL normalization: validation against real data

**The scheduler and parsing defects are reproducible. The stronger claims about new documents, correct document identity, and production readiness do not follow from them.** All fifteen assumptions in the requested audit now have an empirical result below. Several are confirmed only in a narrower form; others fail on real counterexamples.

The most important new finding is an accepted recovery for `hr-4824` whose PDF actually contains **H.R. 4755**. The bytes, receipt, first-page text, rendered page, and independent official bill texts agree. This is a document-identity problem that successful downloading and PDF parsing did not catch.

## What was checked

- **1,202,155 campaign targets**, using the previously frozen original plan, second-generation `plan_v2`, selected recoveries, state, and Wave 4 results.
- **4,129,878 capture-source rows**, **913,034 publisher-link rows**, **605,848 published source rows**, and **367,008 published document rows** from `publish_v20`.
- The actual native normalization SQL on **34,258 affected-family URLs**, screened from **1,418,211 distinct URLs** across campaign, publication, links, state, and recovery candidates.
- The actual scheduler on retained addresses and state; the actual link-resolution SQL on retained page readings; the actual frontend lookup function and reader against the published release.
- **1,561 complete repaired PDF bodies**, their SHA-256 hashes and receipts; **120 retained Wayback index responses** and available replay bodies.
- Fresh paired HTTP requests for all **27 trailing-space campaign cases**, followed by complete downloads and parser checks for the five successful PDF candidates.

The implementation code did not change between the starting commit `cafb1b43` and the checked ending commit `2716e9d`; the intervening changes were documentation. Inputs, hashes, native version, and limits are recorded in [manifest.json](evidence/manifest.json). Later campaign generations are not silently substituted for these fixed populations. This audit answers the fifteen assumptions listed before the Wave 6 expansion; the reconciliation addendum below separately verifies the later status counts. The [reconciled trace](../../url-normalization-trace.md) and [implementation plan](../../plans/url-normalization.md) incorporate both sets of results.

The native comparison uses the current **nine-rule** normalizer as its baseline. Its finding of zero changed published-source keys compares that implementation with the proposed corrections. The historical publication used seven rules. The comparison therefore does not establish that upgrading the published release from seven rules to the complete proposed implementation preserves every association.

## Results for all fifteen assumptions

| # | Assumption | Result from real data |
| --- | --- | --- |
| 1 | Lexicographic scheduler selection causes substantial acquisition loss. | **Mechanism confirmed; historical loss count unproved.** With real HTTP/HTTPS spellings and empty state, the planner emits no request because it selects the inadmissible spelling first. The same addresses with their actual retained state emit HTTPS successfully. The census finds 26,777 potentially affected HTTP-first groups, but these are not 26,777 lost documents or reconstructed historical seed batches. [Scheduler evidence](evidence/scheduler-results.json). |
| 2 | Repairing the address will recover the remaining House targets. | **Not established for the remaining population.** Among the frozen 1,411 pending House ampersand targets, 1,399 have no matching repaired attempt in the pinned Wave 4 results; the other 12 include three size limits, two failed 302s, two request failures, and five stored/unchanged responses with unresolved qualification. Address repair alone did not satisfy those 12. [Cohort evidence](evidence/corpus-results.json). |
| 3 | The 1,563 accepted repair transitions represent correct additional documents. | **False as a blanket claim.** They bind to 1,561 unique PDF bodies. All hashes and receipt bindings check out, but 1,332 bodies were already saved in publication, and `hr-4824` contains H.R. 4755. The remaining 229 hashes are new to that saved-body set; that does not establish 229 new semantic documents. [Body checks](evidence/repair-body-summary.json), [novelty census](evidence/corpus-results.json). |
| 4 | House/Senate behavior proves the proposed server configuration and generalizes across hosts. | **Observed difference confirmed; server explanation and universal rule unproved.** The retained evidence has 4,062 successful literal ampersand URLs on four Senate hosts, versus 19 House HTTP attempts, all 410 on one Transportation host. It does not expose internal rewrite configuration or test every House route. The newer defense appropriately withdraws that inference. [Earlier pinned host census](../../url-normalization-defense-response-evidence.json). |
| 5 | Existing scheduler state and exact campaign membership create the predicted operational failures. | **Confirmed.** Mixed seeds, a lone ampersand seed, and an existing bad state row plus a good seed all select the ampersand request. A controlled implementation that substitutes the repaired address without preserving the campaign target yields an empty campaign queue. These were actual planner executions, using real addresses and retained state. [Seven scenarios](evidence/scheduler-results.json). |
| 6 | Fragment and `%2F` repairs normalize affected URLs correctly without demonstrated document collisions. | **Confirmed for the observed corpus, with limited outcome meaning.** Native execution changes four Senate error-address spellings and 30 ampersand fragment spellings. Including the separately tested trailing trim changes 81 URLs total and zero published-source keys. The only two newly merged campaign groups are the known GPO error/PDF pair and a Finance hearing/error-address pair; the latter has retained redirects from the clean hearing to the same error page. No distinct-document collision was found. This does not recover the hearing. [Native comparison](evidence/normalization-results.json), [capture evidence](evidence/corpus-results.json). |
| 7 | A matching Wayback SURT identifies the correct archived resource. | **Supported for the checked replay bytes; SURT alone is insufficient.** The proposed validation yields 145 candidate rows for 15 formerly rejected targets. Twelve targets have retained qualified replay bodies whose SHA-256 and CDX SHA-1 digests independently match, with exact replay spelling/timestamp validation. Three lack a matching qualified replay in this evidence. Wrong keys and inconsistent returned originals are rejected by negative controls. [Replay results](evidence/wayback-results.json), [controls](evidence/wayback-guard-results.json). |
| 8 | The Wayback changes preserve pagination, acquisition checks, and completeness. | **Core behavior confirmed; full recovery completion unproved.** Replaying all 120 responses preserves 60 rate-limit failures and all nine previously valid outcomes. Of 51 invalid responses, 46 become complete and five correctly remain page-limited. A control using retained CDX rows, a constructed continuation marker, and an empty second page preserves candidates and both evidence pages. Digest, timestamp, redirect, status, and incomplete-response controls still reject bad replays. This is not a completed live multi-page archive campaign or historical HTTP-custody replay for all 12 bodies. [Discovery evidence](evidence/wayback-results.json), [guard evidence](evidence/wayback-guard-results.json). |
| 9 | The publisher-link join causes no additional acquisition loss. | **Confirmed for the cited case and supported by the replay.** On 14,157 retained wrapper contexts, native SQL extracts 1,193,036 links, resolves 1,193,035, and rejects one. It discovers 8,053 ampersand download targets; 8,035 already have exact state rows, while only 4,096 occur in the publisher-link table. Ashley's 87 links resolve, and its ampersand target exists in state. Absence from publisher links therefore does not imply failed discovery. The remaining 18 state differences are not attributed to this join. [Native link replay](evidence/discovery-link-results.json). |
| 10 | Separate wrapper/download identities produce correct document outcomes. | **Separation is supported; universal document correctness is not.** Of 8,055 campaign ampersand/base pairs, 8,021 have a captured base wrapper and 2,564 have both that wrapper and a selected recovery. Only one base address is a published source, versus 4,024 ampersand addresses. Keeping these resources separate is justified. It does not prevent the `hr-4824` mismatch or establish that every wrapper led to a correct file. [Pair census](evidence/corpus-results.json). |
| 11 | Filtering error-response redirect addresses from the capture union is effective and harmless. | **Ineffective in the checked corpus.** All 80,764 error final addresses also enter through the source-address branch; 80,761 additionally enter as contexts. All 55 Senate `notfound` error addresses survive elsewhere. Filtering only the final capture union removes zero addresses. This does not justify deleting those addresses globally: many have good captures or published uses in other observations. [Input-route census](evidence/followup-results.json). |
| 12 | Additional malformed-literal repairs recover intended URLs. | **Some specific repairs supported; broad inference rejected.** The pinned raw readings contain five `mailto:http...` literals and one malformed `http://File URL path:` literal. Native resolution rejects them; narrow prefix removal admits all six. Four mailto links lead to already retained and published bill PDFs; the file-prefix case leads to an already retained Dallin Maybee PDF. The fifth mailto target lacks matching retained bytes here. A Congress GPO wrapper points to an already published bill. Most nested-HTTP matches are legitimate sharing/archive links, not corruption. [Raw census](evidence/malformed-results.json), [native repair checks](evidence/remaining-results.json). |
| 13 | All 35 accepted stored aliases attach the correct documents. | **Key and custody checks pass; the stronger document claim remains incomplete.** All 35 target/candidate pairs produce equal valid native keys and have complete retained-import and accepted-decision bindings. Thirty-three bodies each belong to one published document. The other two are a video and an HTML download wrapper, neither a published document body in this generation. The check did not rehash all 34 distinct alias bodies or prove the historical semantic identity of each target. [Native keys and bindings](evidence/remaining-results.json), [document memberships](evidence/alias-membership-results.json). |
| 14 | Alternate-spelling public lookups fail as claimed. | **Confirmed, with narrower semantics than a blanket failure claim.** All 605,848 exact source rows find their expected document. Many alternate spellings miss; some succeed or return other document rows. The census uses the actual frontend `lookupUrl`, followed by real reader journeys against a manifest-verified local release. These are reader executions, not a browser UI test. [Lookup census](evidence/lookup-summary.json), [reader journeys](evidence/lookup-journeys.json). |
| 15 | The combined fixes preserve publication and are production ready. | **Not demonstrated.** The tested normalization proposals change no published-source keys; 58 existing publisher-link associations are affected, with no existing published target-document memberships for those source IDs. That bounds one impact. There is no implemented combined scheduler/qualification/publication change to run through a full publication comparison, and the real document mismatch defeats an unconditional readiness claim. [Affected associations](evidence/publication-link-impact.json). |

## Accepted bytes can still be the wrong document

The two selected targets below have the same 66,128-byte body, SHA-256 `f984b8439d21b0ef80f8a6f2e16f1dfc20d1ff57a53afe3f65ceefca67b551ee`:

- `https://democrats-science.house.gov/download/hr-4755&download=1`
- `https://democrats-science.house.gov/download/hr-4824&download=1`

Their retained receipts bind the repaired requests to final URLs ending `HR%204755.pdf` and `HR%204824.pdf`, respectively. Both bind to the same PDF. Its [rendered first page](evidence/accepted-hr4824-first-page.png) visibly says **H.R. 4755**, and its text identifies the Privacy Enhancing Technology Research Act. The [unchanged retained PDF](evidence/accepted-hr4824.pdf) is included for direct review.

This is not merely a difference between URL strings. The official introduced texts identify [H.R. 4755 as the privacy technology bill](https://www.govinfo.gov/content/pkg/BILLS-118hr4755ih/html/BILLS-118hr4755ih.htm) and [H.R. 4824 as the Carbon Sequestration Collaboration Act](https://www.govinfo.gov/content/pkg/BILLS-118hr4824ih/html/BILLS-118hr4824ih.htm). The retained `hr-4824` result therefore does not establish recovery of the bill named by that target.

The same hash was already published as document `9ad7ef59a70fd920308d9a5debef6dafeefff85a0791e432ccaf6839b344afc0`, list row 59142, under House meeting source filenames `BILLS-118HR4775ih.pdf`. Official [H.R. 4775 concerns tobacco cessation](https://www.govinfo.gov/content/pkg/BILLS-118hr4775ih/html/BILLS-118hr4775ih.htm), adding a third conflicting identifier. The preserved source spelling may itself be wrong. This audit establishes the mismatch, not which publisher or pipeline step originally introduced it. It must not be presented as a regression caused by the proposed normalization changes.

The wider repaired-body check verified every hash, PDF header, repaired requested URL, and receipt binding. First-page extraction succeeded for all 1,561 bodies; 343 had little or no extracted first-page text. A slug-token heuristic corroborated 1,144 bodies, but is not semantic ground truth. The universal correctness claim is disproved by the bill example; the remaining bodies have not all received manual identity review.

## Trailing `%20`: recovery and novelty checked separately

The earlier collision check remains valid: among the 27 affected campaign paths, the only existing clean campaign counterpart is the GPO Deepwater URL. Its spaced URL yielded an error, while the clean URL yielded the published PDF. Different spellings did not demonstrate different documents.

The new live check adds actual retrieval outcomes, measured on October 31, 2026:

| Trimmed outcome | Targets | Meaning |
| --- | ---: | --- |
| HTTP 200 PDF | 5 | Each literal `%20` URL returned 404. All five complete PDFs downloaded; their first-page parser checks succeeded. |
| HTTP 200 non-PDF | 19 | HTML responses include wrappers and a security rejection. A 200 response does not establish document recovery. |
| HTTP 403, 404, or 410 | 3 | Trimming did not recover a file. |

**All five successful PDF hashes already occur as saved bodies in the published release.** Their subjects include two FY 2027 subcommittee notices, the H.R. 4674 amendment roll call, the Central America hearing transcript, and the Deepwater report. This establishes useful address repair in five cases, with zero additional saved-body hashes in that subset. It neither proves that all 27 clean addresses are equivalent nor demonstrates global harm from trimming. [Paired HTTP evidence](evidence/live-trim-results.json), [complete PDF checks](evidence/live-pdf-results.json).

The experimental `(?:%20|/)+$` SQL changes identity keys, not the stored fetch address. Obtaining these five PDFs required explicitly requesting the trimmed candidate. That distinction also applies to the scheduler proposal.

## Public lookup results

Counts below are source-row/variant pairs; they are not counts of distinct missing documents. “Other rows only” means the lookup returned results but omitted the source row's expected document.

| Input spelling | Tested | Expected document found | No document found | Other rows only |
| --- | ---: | ---: | ---: | ---: |
| Exact published source | 605,848 | 605,848 | 0 | 0 |
| Browser-serialized spaces | 472 | 2 | 470 | 0 |
| Lowercase percent hex | 987 | 1 | 986 | 0 |
| Repaired download query | 4,270 | 10 | 4,256 | 4 |
| Removed Congress `q` parameter | 174 | 0 | 174 | 0 |
| Removed tracking parameters | 13 | 0 | 13 | 0 |
| Unwrapped Wayback address | 67 | 10 | 54 | 3 |

The four download-query differences involve JSON wrapper records versus PDF or other JSON records. The three Wayback differences involve separate HTML bodies with the same hearing titles. These real differences show why broader lookup aliases should return appropriately associated records instead of assuming every alternate URL identifies exactly one interchangeable document. They do not establish that the existing exact lookup format is corrupt. [Different-document details](evidence/lookup-different-documents.json).

## Remaining acceptance boundaries

The audit is complete for the requested fifteen questions. It does not convert unresolved claims into passes. The evidence still cannot establish:

- The number of historical documents lost specifically because of scheduler ordering; historical seed batches and alternative acquisition paths matter.
- Universal server rewrite behavior or guaranteed success for the still-unattempted repair cohort.
- Correct semantic identity for every accepted PDF and stored alias, especially image-only pages, wrappers, and historical replay requirements.
- Recovery of the three newly admitted Wayback targets without matching qualified replay bytes, or completeness beyond retained/query-bounded pages.
- Correct publication after a combined implementation that does not yet exist. A full rebuild and consumer comparison remain implementation acceptance work.

The concrete next correction is to separate **target satisfaction, verified bytes, document identity, and additional published documents** in the report's counts. The `hr-4824` evidence needs identity review before being counted as the intended bill. Preserve the original bytes and receipt; this audit made no recovery-decision, campaign, production-code, or publication changes.

## Reconciliation with the later Wave 6 documents

The other agent's documents at `2716e9dc` were compared with fresh, frozen copies of the latest plan, selected recoveries, URL state, and Wave 6 result files. [Reconciliation evidence](evidence/reconciliation-results.json) records their hashes and exact transitions. This follow-up checks statuses and relationships; it does not independently requalify all newly selected content.

| Population | Original plan | Frozen Wave 5 plan | Latest Wave 6 plan |
| --- | ---: | ---: | ---: |
| Accepted recovery | 0 | 35,552 | 37,536 |
| Needs acquisition | 10,924 | 4,589 | 2,605 |
| Retained candidate pending | 32,161 | 0 | 0 |
| Acquisition excluded | 604 | 3,548 | 3,548 |
| Usable direct | 1,158,466 | 1,158,466 | 1,158,466 |

The endpoint of 37,536 accepted and 2,605 pending is confirmed. Exactly 1,984 targets changed from pending to accepted after the frozen Wave 5 generation. The original plan's 10,924 acquisition targets and 32,161 pending retained candidates sum to 43,085 unresolved targets; these become 37,536 accepted, 2,944 newly excluded, and 2,605 still pending. The earlier 41,111-target baseline and resulting percentage are not supported by that cited plan.

The selected-recovery table contains 37,542 rows because six selected oEmbed targets remain excluded by scope. Wave 6's 858 WordPress result rows produced 573 selected targets; coordinate rewrites produced 92 selected targets from 159 result rows, not the claimed 173 selections. The large-PDF retry category produced six selected targets from 11 result rows. The plan now uses these artifact-specific units instead of calling attempts, selections, and documents the same thing.

The latest plan still accepts `hr-4824` with body `f984b8439d21b0ef80f8a6f2e16f1dfc20d1ff57a53afe3f65ceefca67b551ee`, and Ashley's base/ampersand targets remain eligible. Thus the newer generation does not resolve those two findings. Pending ampersand targets fall from the frozen 1,415 to 279; the earlier cohort-specific results remain correctly labeled rather than being overwritten.

The Wayback counts also reconcile: the other agent correctly counted 237 CDX row occurrences and 88 original spellings differing from their query. All 237 have matching SURT keys and can form exact-validator-compliant replay URLs. Whole-page rejection discards 165 raw rows on the affected pages; deduplication yields the 145 newly admitted candidates measured by this audit. The 237, 88, 165, and 145 figures describe different units, not contradictory measurements. This still leaves only twelve newly admitted targets with the independently checked replay bytes described above. [Row-unit check](evidence/wayback-row-unit-check.json).

Reconciliation also removes stale code descriptions from the trace: split positions are zero-based, `url_normalized` exports its key/error fields, query filtering occurs in `url-normalized.sql`, source addresses include more than document roles, recovery attachment uses component disambiguation, and frontend `lookupUrl` throws on invalid input. Both current documents now state that distinct-document harm from `%20` trimming was not found and that combined publication readiness remains unproved.
