# Retained Explorer inventory and native input acceptance

The bounded inventory is complete for the retained six-table Explorer snapshot,
the 16 frozen research CSVs, and the three named reference inputs. It identifies
291 fields, including nested fields, and supplies 878,151 non-witness row
references. This is retention accounting with specific native checks; several
queryable facts still need a native destination. **ct-gi01 remains open.**

Evidence lives under the main checkout's
`.cache/archive-release/implementation/reviewed-non-news-20261106/ct-gi01/`.
`inventory-attempt1/inventory.json` records every file identity, field type,
null/empty count, observed fact label, upstream generation and input selector.
`field-dispositions.json` assigns every measured field a destination, owner and
qualification. The witness table received schema inspection only; `ct-x78c`
owns its occurrence values and row ledger.

## Exact boundaries

| Boundary | Evidence and result |
| --- | --- |
| Legacy publication | `56c87f8a7e29314d9e1477c0`, generated October 23. All six local Parquets match their manifest hashes. Its original input identities remain in `legacy_inputs`. |
| Research CSV snapshot | Every CSV is independently hashed and profiled. These are the frozen November 1 comparison inputs, not automatically the input bytes of the October 23 publication. |
| Retained native candidate | `720c495b66d1691ee270dadb45c752f1c47d997c9fbe561dbbd039be15786b2f`, produced from `5d1a8779`. The eight files read here match its manifest. This candidate is private and predates newer main changes. |
| Native input acceptance | `candidate-native-acceptance.json` verifies the retained completed-model checkpoint against its receipt, its manifest against the checkpoint, and all eight native selectors and parser versions against both its candidate specification and main `742dbe70`. |
| SpicyRegs difference | Candidate manifest `7188109e…` selects 12 tables; main manifest `4adb1f42…` selects 14. The later additions are 932,877 bill actions and 10,561,417 member votes. Their retained local bytes match their declared digests; schemas are in `upstream-detail-schemas.json`. This difference prevents using 720c as final-main acceptance. |
| Existing model acceptance | Reuse the coordinator's six invariant suites, source checks and native import/append proofs where identities match. No model or import was repeated here. Final-data and deployed acceptance remain separate. |

The original publication pins matcher input `77d6119a…`; the later frozen CSV
has digest `db411198…`. They are distinct snapshots. No comparison in this
report equates them. The original publication also pins the issue-decision JSON
`a18a56e5…`. Its standalone JSON was not recovered here. The retained sources
table contains all 7,502 decision records, each with its own distinct body
digest and retained locator. Those records preserve the dismissal explanations,
dates, original/checked publication and history identities. Their raw-body
custody and the standalone JSON's custody remain separate obligations.

## Field destinations and missingness

The machine field map is exhaustive for the measured snapshots. These are its
important meanings; a mapped destination does not itself establish value parity.

| Retained family and fields | Destination and disposition |
| --- | --- |
| Committee code, title, chamber, type and parent; Congress-specific hierarchy, names, activity periods and archive links | Native `committees` has code/name/chamber/type/parent fields and pinned upstream history. All 3,432 old rows have a native code. Per-Congress legacy facts and the 77 committee-review source rows remain retained evidence with native equivalence unverified. Code presence does not preserve every historical value. |
| Meeting title, chamber, Congress, date, type, status, access, committees and scheduled time | Typed `meetings` fields and sittings; `ct-r4rd` owns equivalent-field/value checks. Source dates, publisher updates, capture times and import times remain distinct. The 312 Senate-page records need supported page-to-event association or a typed source-observation destination. Do not invent Congress.gov IDs or import distrusted old page decisions. |
| Meeting evidence states and completeness columns | `meeting_coverage` plus explicit typed meeting values. Keep scope, denominator and rule meaning. Old counts, `text_source`, absence flags and native states are not interchangeable. Positive held evidence pending association remains unknown, rather than proof of absence. |
| Material title, kind/provider/category, meeting links, scheduling/status, document groups and file metadata | Native document/detail/source fields or recording observations, according to kind. File URL presence is measured separately below. Literal labels, roles, category, publisher version, date meaning and meeting association retain exact old evidence until their equivalent native values are established. |
| Material `files[].sha256`, `saved_copy_sha256`, `saved_filename`, `version` | All 417,004 occurrences are null in this legacy snapshot. Do not diagnose their absence as migration loss or manufacture a saved-body identity from an old material UUID. Native saved-body evidence has its own provenance. |
| Source IDs, identifier scheme/value, input snapshot, import date, facts and links | Immutable legacy source references; native capture/reading evidence supplies its own identities and timestamps. Old UUIDs and snapshot IDs are not native document keys. All 213,545 old `identifier_scope` values are null. Most old retrieval timestamps are also null; import dates cannot establish live retrieval. |
| Witness fields, including participation, roles, position, organization and source evidence | `ct-x78c` owns the occurrence ledger. This report does not replace it with event/name grouping. |
| Issue IDs, title/category/severity/status/selection, subject/meeting references, detected date, selected values, alternatives and reasons | `issue-dispositions.json` accounts for all 35 title/status classes. Historical adjudications and conflict alternatives remain historical evidence. Association, inferred-recording and source-shape classes remain explicit native reconciliation work. No old issue is silently treated as a current coverage fact. |
| Channel directory: committee/code, primary/secondary/member handles and channel IDs | Typed `channels`, including mapping basis and source body. The 119-channel prior comparison remains reusable only with matching directory/output identities. Committee membership does not establish that a video records a hearing. |
| Collected video identity/title/description/channel, supplied publication dates, duration and availability | Typed `videos`, including unmatched videos and source body. Keep metadata timestamps distinct from actual publication and retrieval. Raw cache payloads and retained metadata-version details remain evidence references. The prior full raw video check is not a new check of all current candidate values. |
| Curated recording package/event, verdict, video/URL refs, notes, channel, lock, found-by and origin | **Verified:** all 7,200 source rows round-trip through the exact pinned decision JSONL, including source-only fields. Every decision's subject, verdict, reference multiplicity and applicable notes/disputes survives in native `recording_matches`. Channel, lock, found-by and origin remain in that provenance file. |
| Automatic matcher method, score, status, flags, channels, duration, source, notes and inferred recording pairs | **Producer gap:** candidate recording bases are publisher links, video claims and curated decisions. It has no native retained scored-matcher observations. Preserve original snapshot and row evidence; use the maintained `matching.gpo_decisions.decide` when implementing the producer. Historical inference must not become a curator verdict, publisher assertion or confirmed absence. |
| Committee amendment/vote nine-column source rows | Typed `committee_records`; comparison below preserves kind, literal number, sponsor, description, bill, URL and qualifiers. These are committee records, not complete member ballots. |
| GPO hearing metadata, text-source associations, found House/Senate documents/pages and derived video/completeness reports | Native transcript/document/recording links where supported; retain detailed metadata, original source URLs and derived-report denominators. Unqualified associations and summaries remain named gaps in the field map. Witness CSVs stay with `ct-x78c`. |
| Congress/session dates and chamber control | The exact bundled `congress_metadata.json` contains Congresses 106–119, session date strings and control labels. Native Congress numbers alone do not preserve this reference dataset. A typed reference destination remains open; do not infer control from a committee's channel role. |
| Archive routes and historical committee archive links | The current `archive-layouts.json` pins the GovInfo package/member address rule. Historical committee archive URLs remain in old committee/source evidence. The one current rule is not proof of historical archive-route parity. |
| SpicyRegs full histories, cosponsors, votes, nominations, amendments and rosters | The report enumerates actual pinned table schemas and generations. Detailed actions/member ballots belong to the newer upstream pins; counts/latest-action summaries do not stand in for them. The bill table exposes `cosponsor_count`, not cosponsor identities. No cosponsor-detail table is pinned. Historical roster input remains with `ct-8cno`; this work adds no duplicate upstream mirror. |

## Row and value results

| Population | Result against 720c |
| --- | --- |
| Old meetings | 18,141 have a native event mapping; 312 cite only `senate.committees:record`, with 312 distinct URLs. The latter are association gaps, not a proven count of missing distinct hearings. |
| Old materials | 359,287 have at least one native URL; 18,702 have none under the bounded HTTP/HTTPS comparison. The latter include 6,137 recordings and 12,565 documents. Neither count establishes source loss: aliases, meaning and associations remain unqualified. |
| Individual material files | All 417,004 occurrences have a row reference. 326,425 have a native source URL; 90,579 do not under that comparison. This catches partially represented materials hidden by an “at least one URL” test. It does not compare every file label, role or date. |
| Old source records | 79,999 have a native URL; 133,546 remain legacy-reference-only under this test. A matching URL is weaker than complete source-value preservation. |
| Old issue history | 264,732 rows in 35 classes retain their original status and exact row references. The 7,502 curator dismissals are separately identified from source diagnostics. |
| Curated decisions | 7,200 of 7,200 preserve source fields and exported references/values; no unexplained or extra candidate decision references. |
| Committee amendments/votes | 19,984 of 19,985 old rows match all nine values; 1,126 candidate rows are additional. The sole old-only row is event 115405's previously raw-adjudicated double-encoded Fernández description. Preserve that source correction as a disposition, not an unexplained missing amendment. A planted wrong description was rejected. |

The five original ledgers use physical legacy row number and ID. The file ledger
uses material ID and file ordinal. Resolve them against their hash-pinned
Parquet, rather than treating a worktree path as permanent data custody.
`retained-input-custody.json` also records independent copies on write of the
six legacy tables, their manifest and all 16 CSVs under `retained-inputs/`.
All copies were rehashed against the inventory. These bounded inputs total
178,303,483 logical bytes and survive removal of the separate pipeline-data
or task worktrees. The shared raw corpus was not copied.

## Cost, checks and remaining integration

The inventory ran for 49.6 seconds at 0.671 GiB peak process-tree RSS with a
3 GiB stop limit. It identified 204,907,673 logical input file bytes; this is not
physical I/O. The file/amendment follow-up took about nine seconds at 0.60 GiB.
Neither run assembled legacy JSON/CSV into a production release, reran native
imports, or used a swap allocation. Reports and watchdog records are durable.

The task's own frozen environment and pinned local runtime passed the focused
inventory tests, including corrupt bytes, lost source-only lock values,
duplicate rows, partial file coverage, missing versus empty values, wrong
verdicts, invented notes and preserved historical adjudications. These are
partial-lane checks. The helper's zero exit means that the inventory completed
and its scoped decision checks passed; it does not approve migration or release.

Current daily configuration already names seven writers, including committee
and playlist records. Video refresh support and produced-pin handoff exist;
video was deliberately opt-in when this inventory was taken (the owner set the
scheduled daily to read it on 2026-11-09, ct-85dm), and decisions remain pinned. This task does
not activate a new writer or schedule. The independent consultant's suggested
video activation is deferred to the existing qualified-source/operations owner,
because the latest accepted handoff explicitly preserves that opt-in boundary.

The next coordinated candidate must account for the actual producer gaps above,
reuse matching native/source evidence, and verify its own changed output and
reader selection. `ct-m104` owns paired readers; `cef-96wc` owns live cutover;
`ct-5kto` owns retirement. No source acquisition, raw/catalog import, model
rebuild, pointer change, deployment, push, main merge or cleanup occurred here.
