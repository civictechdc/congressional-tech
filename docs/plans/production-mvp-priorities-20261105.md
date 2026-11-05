# Production MVP priorities — November 5, 2026

Build a reliable hearing research product: find a hearing, understand who appeared and whom they represented, open testimony or recording evidence, and share a source-backed result. Use the existing archive and hosted MCP. The MVP is defined by useful working features, not completion of the Phase 2 migration or its administrative records.

Three GPT-6.1 Sol/xhigh reviewers used the greybeard and ETL workflow skills to rank the original 52 open tickets. Five HTML stage tickets were absorbed into `ct-082q`. The third review then closed `ct-syem` as satisfied and `ct-fd16` as deferred, leaving 45 ranked open tickets. Three new URL/recovery findings bring the current backlog to **48 open tickets**; they are listed separately pending comparative ranking. The numbered entries retain their relative order; audit reports preserve their original ranks. The audience is staff, reporters and researchers doing hearing research. Amendment specialists would move the already-captured Rules records higher.

## What already works

The archive has document discovery, saved source files and stable links. The deployed MCP 0.6.1 can find a hearing, return its witnesses and documents, and read a page from a saved transcript. Reuse those capabilities. The deployed MCP hearing dossier already excludes superseded witnesses. The second root-cause round found that the producer can incorrectly supersede distinct same-person roles, so correct that rule alongside the site's default-list behavior.

The audit baseline identified two concrete site failure mechanisms: an optional relation could reject a combined hearing/document load, and event witness lists merged rows without the producer's current-appearance rule. These are functional repairs. Completing a broader migration is unnecessary to address them. Implementation is proceeding alongside this plan; the diagnoses describe audit revision `c3ee2eec` and selected release e145, while each ticket retains its own implementation and publication status.

## Build first

The first six entries are feature work. The seventh is a narrow production repair that can run in parallel. These are slices of existing tickets; broader acceptance and historical commitments remain open until delivered.

| Rank | Ticket | User outcome | Smallest useful change |
| --- | --- | --- | --- |
| 1 | [ct-t915](../../.tickets/ct-t915.md) | Keep the hearing and its evidence usable | Separate core hearing/document loads from optional relations; show current witnesses while preserving distinct roles and statements; lead with the existing native archive. Coordinate the confirmed producer-precedence correction in `ct-x78c`. Keep stable links and historical access. |
| 2 | [ct-dx22](../../.tickets/ct-dx22.md) | Put witnesses at the sitting their evidence supports | Repair the appearance binding. A package-wide witness stays package-scoped when the source does not identify a sitting. |
| 3 | [ct-j78x](../../.tickets/ct-j78x.md) | Find the recordings a hearing actually has | Publish the existing recording evidence with one supported meeting association and use it in the site, coverage and MCP. Preserve uncertain package context. |
| 4 | [ct-lx67](../../.tickets/ct-lx67.md) | Find and group witnesses by the right employer | Fix shared title/employer extraction using retained source lines. Preserve full titles and uncertainty; replay only the proven affected input scope. |
| 5 | [ct-kthe](../../.tickets/ct-kthe.md) | Open testimony from the witness who supplied it | Repair the confirmed JEC witness continuation and event-matching exclusions. Inspect current retained Intelligence and Environment cases before choosing additional parser changes. |
| 6 | [ct-m94a](../../.tickets/ct-m94a.md) | Make date filters and observed ranges truthful | Qualify dates supplied by alternate download names before accepting them as document dates or coverage bounds. Reuse current typed readings; preserve literal aliases and uncertain dates. |
| 7 | [ct-680z](../../.tickets/ct-680z.md) | Keep hosted PDF reading usable | Patch the MCP app PDF dependency and ship the scoped runtime update. Verify saved-PDF reading with its existing limits; avoid pulling in the whole security backlog. |

Start the site repair immediately. In parallel, work on the appearance and testimony producers and the recording association. They can reuse retained inputs; a shared data release should contain the ready, qualified changes without waiting for every later enhancement. Upgrade the MCP app's PDF dependency separately from the archive parser lock.

The root-cause audit corrected the date diagnosis. In all three named `ct-m94a` cases, unresolved displayed dates are filled from opaque download aliases and incorrectly accepted; replaying the same parser is not the remedy. `ct-cxc5` uses generic document-to-meeting attachments as print-date evidence. Correct those selection rules while preserving real historical dates, useful links and uncertainty. See the [15-ticket root-cause analysis](production-mvp-root-causes-20261105.md).

The [second root-cause round](production-mvp-root-causes-round2-20261105.md) adds one narrow witness fix to this first increment: event 100520 has two raw-supported W. Ron Allen roles with separate statements, but the model supersedes one by XML order. Repair that producer rule before relying on default supersession filtering. The broader `ct-x78c` migration accounting can remain later. The second round also identifies actual nightly approval/recovery gaps and corrects stale meeting-field comparisons.

The [third root-cause round](production-mvp-root-causes-round3-20261105.md) identifies specific writer-retry, acquisition and raw-protection gaps while shrinking maintenance scope. `ct-syem` is closed using existing caller assertions and retained passing shards on unchanged code. `ct-fd16` is closed as deferred, not delivered, until a named consumer needs canonical table identity. The remaining operational tickets retain their separate owners and historical obligations.

The PDF dependency repair is tied to the actual shipped reader. The app lock uses pypdf 6.19.0 and the body reader parses retrieved PDFs. The upstream [infinite-loop advisory](https://github.com/py-pdf/pypdf/security/advisories/GHSA-5849-834g-hvw5) affects versions below 6.21.4. No exploit was demonstrated. This calls for a scoped package update and a working PDF read, not closure of every dependency advisory.

Verify each feature by doing its user action through the normal site or MCP and opening the supporting source. Use the existing tests and release process for changed behavior. Keep that verification inside delivery; do not create a parallel receipt-management program.

## Next user-value increment

These features improve the research product after the core path works. Rank is expected user value relative to change scope; it is not a claim about implementation hours.

| Rank | Ticket | User outcome | Smallest useful change |
| --- | --- | --- | --- |
| 8 | [ct-67k1](../../.tickets/ct-67k1.md) | Explain what an attached document is | Publish Congress.gov role, name, description and format per document reference. The current producer drops these fields, so this is a bounded source/publication change. |
| 9 | [ct-cxc5](../../.tickets/ct-cxc5.md) | Correct three known hearing-date contradictions | Keep document attachments separate from evidence of the printed proceeding date. Correct the confirmed selection mistakes and preserve supported meeting dates and useful links. |
| 10 | [ct-717p](../../.tickets/ct-717p.md) | Query the 31 Rules records already captured | Publish the retained event 118300 XML through the existing parser. The documents are already readable; this adds structured amendment research. |
| 11 | [ct-9s7b](../../.tickets/ct-9s7b.md) | Read complete, consistently identified captions | Finish the retained playlist work and its producer-to-reader wiring. Do this before promising comprehensive captions. |
| 12 | [ct-j49p](../../.tickets/ct-j49p.md) | Follow nomination committee activity | Expose existing committee activity and exact supplied dates; keep it separate from floor votes. |
| 13 | [ct-umtm](../../.tickets/ct-umtm.md) | Recover high-value documents behind removal notices | Start with reader-reported missing documents and retained recovery evidence, rather than an unrestricted recovery campaign. |
| 14 | [ct-j9o7](../../.tickets/ct-j9o7.md) | Find more documents by bill identity | Recover the ambiguous filename cases only when a typed copy or independent source corroborates the bill. |
| 15 | [ct-opy0](../../.tickets/ct-opy0.md) | Explain meetings with an unknown chamber | Fill supported missing values and explain unresolved cases where users encounter them. |

`ct-67k1` precedes the broader HTML program because it preserves useful metadata already supplied by Congress.gov. It still needs a producer change: current meeting-record extraction reduces those references to URLs. It is not a metadata-only toggle.

The HTML work is one later feature in [ct-082q](../../.tickets/ct-082q.md): retained extraction, native publication, parallel site and MCP presentation, and one shared result check. Its checklist preserves the acceptance and evidence from the five absorbed stage tickets, including the earlier content and mapping requirements. Their closure records consolidation; the feature remains unfinished.

## Later, or when an actual constraint makes it necessary

These remain real obligations or useful future work. They do not all belong on the initial feature path. Full migration, broad parity and retirement can wait. The broader MCP acceptance matrix stays here; changed-feature checks happen as part of the builds above.

| Rank | Ticket | Purpose | Trigger or bounded action |
| --- | --- | --- | --- |
| 16 | [ct-8cno](../../.tickets/ct-8cno.md) | Compare historical committee rosters | Integrate the accepted upstream 113th–118th Congress generation when available; keep present coverage truthful. |
| 17 | [ct-k2ij](../../.tickets/ct-k2ij.md) | Expand House committee-record acquisition | Feed a bounded missing-input plan into the maintained capture path; changing only the old gap-filler would not reach the current workflow. Reuse held XML. |
| 18 | [ct-db3w](../../.tickets/ct-db3w.md) | Fill confirmed missing meetings | Prioritize real missing-event requests, then trace their source and inclusion boundary. |
| 19 | [ct-082q](../../.tickets/ct-082q.md) | Read cited descriptions, distinct page dates and cleaner testimony in both readers | Integrate the retained extraction and publication work, then deliver the site and MCP experience on one shared release. Reuse existing readings and verification. |
| 20 | [ct-gi01](../../.tickets/ct-gi01.md) | Complete the broader native data migration | Bring over only fields needed by selected features now. Finish the full inventory and legacy migration later. |
| 21 | [ct-x78c](../../.tickets/ct-x78c.md) | Preserve every distinct witness before legacy retirement | Fix the confirmed same-person/different-role precedence defect with the first witness increment. Complete source-occurrence accounting before retiring the old route. |
| 22 | [ct-r4rd](../../.tickets/ct-r4rd.md) | Compare delivered meeting details with upstream records | Update the comparator to the fields already published, then investigate residual values on pinned inputs. Current evidence does not require another parser replay. |
| 23 | [ct-m104](../../.tickets/ct-m104.md) | Complete the broader MCP acceptance matrix | Verify each changed user journey as it ships. Keep the full remaining matrix outside the feature build queue. |
| 24 | [cef-96wc](../../.tickets/cef-96wc.md) | Complete the full live migration and rollback record | Finish when the full producer/site switch happens; reuse current qualified deployment work. |
| 25 | [ct-5kto](../../.tickets/ct-5kto.md) | Retire the separate legacy publisher | Remove it after its useful data and readers have moved. Do not make deletion a launch requirement. |
| 26 | [ct-ud0b](../../.tickets/ct-ud0b.md) | Keep a promise of unattended freshness | Repair qualification of new documents' added URL state and preserve completed candidates across wrapper retries. Promote when unattended updates are promised; then observe a genuine scheduled result. |
| 27 | [ct-4jms](../../.tickets/ct-4jms.md) | Verify ongoing scheduled acquisition | Verify effective settings, budgets and the actual queue; retain cutoff and failure outcomes and observe a scheduled run. Keep publication and campaign acceptance separately owned. |
| 28 | [ct-nh41](../../.tickets/ct-nh41.md) | Explain why a recovered document belongs | Fix authoring on the next recovery change; the prior user-visible boilerplate has already been removed. |
| 29 | [ct-6v77](../../.tickets/ct-6v77.md) | Make repeated archive builds cheaper | The latest qualified build fits its 14 GiB limit. Qualify the retained bounded-export proposal only for a named budget gap; measure before selecting further joins. |
| 30 | [ct-zpbl](../../.tickets/ct-zpbl.md) | Avoid unnecessary parser rereads | Preserve active reading and refusal selections through the planned declared-version migration. Keep closure warnings advisory and compatibility until selection parity holds. |
| 31 | [ct-9lxf](../../.tickets/ct-9lxf.md) | Keep local work from running out of disk | Reuse custody-checked originals and retire owned disposable scratch. Preserve completed candidates for retry and measure capacity before Git maintenance. |
| 32 | [ct-f9hw](../../.tickets/ct-f9hw.md) | Keep local paths out of resumed recovery receipts | Fix before using the affected old frozen-receipt resume path. It is a conditional operational prerequisite, not an end-user feature. |
| 33 | [ct-1l1h](../../.tickets/ct-1l1h.md) | Protect irreplaceable raw inputs | Reconcile the three B0 metadata counterexamples and historical exceptions; obtain actual bucket-lock readback under the existing owner. |
| 34 | [ct-m56x](../../.tickets/ct-m56x.md) | Record custody of an already stored body | Preserve verified metadata through conditional upload, legacy/reference and cached reuse paths. Keep the delivered reader fallback and avoid redundant HEAD requests. |
| 35 | [ct-31e2](../../.tickets/ct-31e2.md) | Confirm the remaining hosted Explorer loopback | Credit original hosted passes. Verify the repaired loopback on a relevant revision after qualified runtime admission; rerun other native checks only where changed. |
| 36 | [ct-8bzh](../../.tickets/ct-8bzh.md) | Make a load-sensitive test reliable | Keep the real CLI and corruption assertions; use a measured hang guard when the flake recurs or that test is maintained. |
| 37 | [ct-a3le](../../.tickets/ct-a3le.md) | Keep the House diagnostic with maintained code | Move the single diagnostic and its two tests, preserving request distinctions and retained response evidence. Keep News Lake work separately owned. |

Automatic freshness becomes required when the product promises ongoing updates. The second audit established approval and retry-lifetime defects in the existing nightly path; the restored schedule had not yet invoked when inspected. Fix those mechanisms using the current gate and recovery controller. Old recovery-resume safety remains required before its affected path is used. Raw protection obligations retain their owners. This prioritization does not waive any of them.

## Park outside the MVP

| Rank | Ticket | Purpose | Reason to wait |
| --- | --- | --- | --- |
| 38 | [ct-77zb](../../.tickets/ct-77zb.md) | Coordinate full Phase 2 completion | Keep the long-term plan, without using the whole milestone as the MVP scope. |
| 39 | [ct-tbrj](../../.tickets/ct-tbrj.md) | Publish detailed acquisition status and timestamps | Resume when a named consumer needs that distinction. |
| 40 | [ct-yr9o](../../.tickets/ct-yr9o.md) | Classify a malformed House XML edge case | No affected current corpus was established; bundle with the next intentional parser change. |
| 41 | [ct-jo8n](../../.tickets/ct-jo8n.md) | Pin News Lake reads to one release | Separate News Lake product work. |
| 42 | [ct-4nyy](../../.tickets/ct-4nyy.md) | Apply News Lake export rights | Required before that news export is offered; outside congressional MVP features. |
| 43 | [ct-xu1o](../../.tickets/ct-xu1o.md) | Scale replay-safe news appends | Separate News Lake scale work. |
| 44 | [ct-d8cf](../../.tickets/ct-d8cf.md) | Migrate the News Lake backend | Separate parked product and backend migration. |
| 45 | [ct-5yof](../../.tickets/ct-5yof.md) | Expose persisted news labels | Resume for a named news consumer. |

## New findings awaiting comparative ranking

These three tickets came from the separate November 5 URL/recovery review after the original ranking. They remain open and retain that review's evidence and priorities. Listing them here does not add a new implementation wave or make campaign acceptance a dependency of ordinary capture.

| Ticket | User value | Bounded next step |
| --- | --- | --- |
| [ct-5esu](../../.tickets/ct-5esu.md) | Find a saved document through a supported alternate URL spelling. | Qualify narrow serialization aliases while preserving exact keys and historical editions. |
| [ct-rie2](../../.tickets/ct-rie2.md) | Know which requested recovery targets were accepted and published. | Finish one requirements-bound campaign through existing import and publication paths; preserve ordinary-capture ownership. |
| [ct-yci9](../../.tickets/ct-yci9.md) | Find a document under the bill its text supports. | Correct demonstrated filename-versus-body contradictions with retained source evidence and a bounded package/measure decision. |

## How the reviews were reconciled

- All reviewers prioritized the existing hearing path, witness attribution and recording discovery. The synthesis includes Senate witness-to-testimony recovery because normal Senate hearing research is part of the chosen audience.
- The runtime reviewer favored the 31 Rules records earlier. They are an attractive bounded next increment, but their documents are already readable; missing witness-to-testimony links affect a more basic task.
- The reader reviewer promoted truthful date bounds. The synthesis keeps that visible correction in the MVP and puts the three separately diagnosed cover disagreements immediately after richer document context, with ready fixes eligible for the same release.
- Full-ticket completion is different from an MVP slice. The root-cause reconciliation updated active scopes, transferred the five HTML stages to `ct-082q`, and repaired their dependency references. Original acceptance and history remain available. No software changes, deployment or implementation tests were performed for this planning work.

All 48 open tickets occur once in the tables: 45 ranked entries (seven MVP-build, eight next, 22 later and eight parked) plus three newer findings awaiting comparative ranking. The original detailed reviewer rankings covered 18, 22 and 12 tickets and retain the earlier 52-ticket snapshot. Current source and retained or lightweight read-only evidence support the disposition updates. No new implementation tests, interactive browser run, acquisition or deployment were performed for this ticket work.

Evidence and detailed effort/prerequisite notes: [consolidated ranking](/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/investigations/mvp-sharing-rank-20261105T173147Z/consolidated-ranking.json), [congressional data review](/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/investigations/mvp-sharing-rank-20261105T173147Z/congress-data-ranking.md), [reader review](/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/investigations/mvp-sharing-rank-20261105T173147Z/reader-release-ranking.md), [runtime review](/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/investigations/mvp-sharing-rank-20261105T173147Z/runtime-hygiene-ranking.md).
