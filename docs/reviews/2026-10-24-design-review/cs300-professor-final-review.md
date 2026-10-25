# CS 300 final review, second pass: the adopted specification set at c3b067c4

Reviewer role: systems / data-intensive software engineering. Date: 2026-10-24.
Reviewed at `c3b067c4`: *Architecture* (**A §n**), *Data Model* (**DM §n**), *Implementation Plan*
(**P §n**), against my five earlier reviews and, where a change needed tracing, the drafts at
`c466a45e` and the previous adopted set at `39ae52d2` (diff saved beside this file). Not read:
pipeline code, tickets, other reviewers' files. Measurements ran on the read-only Oct 19
snapshot through the project venv (`prof2_spotchecks.py`, `prof2_detail_view.py` here; the
Parquet files they re-read were built in earlier passes).

## Verdict

**Ready to build from.** All four must-fix items landed in the form I said I would accept, two
of them more strongly; every nice-to-have landed. The restructure ("one home per rule") lost
nothing any of my reviews required. The new parts are correct and linear. One new sentence is
needed (a reading's resolved links depend on a mutable input, which conflicts with the
re-run invariant); five smaller clarifications are listed in §5.

**Grades.** Architecture **A (93)**, +1 from A− (92). Plan **A− (92)**, +2 from A− (90).

## 1. The four must-fix items

| Item | What I said I would accept | What landed | Verdict |
|---|---|---|---|
| Detail page row limit and per-view cost | A 1,024-row page limit on every `detail` leaf, the per-view cost restated (≈70–90 KB with it) | DM §8.1 `detail`: "Offset index and a 1,024-row page limit on every leaf; 16 KB pages for the incompressible key columns (`link_key`, `saved_body`, `alternates.body`) and 64 KB for the rest; write batches of 1,024 rows"; size "55–70 MB; a view reads about 19 pages, 70–90 KB". A §10.1 "about 19 concurrent page reads"; A §16.1 "About 19 page reads, 70–90 KB". Recomputed from my files under exactly those settings: 19 leaves (8 scalars, 4 in `alternates`, 2 in `meeting_refs`, 3 lists, 2 in the fold), **≈49 KB per view** (`saved_body` 16 KB, `link_key` 8.5 KB, the fold 14 KB, `occ_start` 4.6 KB, the rest under 1 KB each). The stated 70–90 KB is a conservative upper bound. | **Landed.** |
| Lake row-group sizes against the engine cap | DM §6's sizes conditional on M1, or the cap's removal required in C | P §5.1 M1.3: "Measure scan and commit cost with and without the engine's 2 MiB file and 2,048-row group caps. [[DATA-MODEL]] §6 assumes they go; if they measurably help, that section changes instead." P §6.3 C0: "Remove the remote write caps unless M1 keeps them." DM §6 states the sizes and now also the table properties (`write.target-file-size-bytes` 128 MB, `commit.retry.num-retries` 0, `gc.enabled`, `write.metadata.delete-after-commit.enabled`). | **Landed** (the condition is stated where measurements live; one clause in DM §6 itself would complete it, §5 item 6). |
| Physical-key existence | An invariant that every physical key a release names exists, checked by the weekly LIST join or the canary | Stronger than asked: DM §7.5 `saved_suffix := '.pdf' when the saved body is a PDF with a verified .pdf copy; else '' when a capture row recorded stored_suffix ''; else '.gz'`, so the model never names a copy it cannot prove; DM §5.3 the PDF-copy job writes a verification record for each `.gz` source and `.pdf` copy; invariant 10 "Every physical key a release names (saved, alternate or recovery) is recorded by a capture's `stored_suffix` or a verification record"; invariant 2 "Every `sha256` in `captures` has a body object under its recorded suffix … a body with no creating line has a verification record"; A §7.4 the weekly LIST joins "the recorded keys of `captures` and the verification records". | **Landed**, prevention plus detection. |
| Retry bound | A named bound | A §8.1 "It retries at most three times", with `commit.retry.num-retries` 0 in DM §6 so the producer's recompute-retry is the only retry; P §5.1 M1.1 tests "lands within three retries". | **Landed.** |

**Nice-to-haves from the last review**, all landed: `detail` 55–70 MB and uploads about 105 MB
(DM §8.1, A §16.1); weekly LIST about 1,300 requests (A §7.4); 59 cut-off URLs (P §6.2 B14); the
fingerprint producer's second `real_files` pass named in principle 4 (A §4.4) and in DM §7.3;
the retry reuses computed rows instead of re-parsing (A §8.1 "reusing rows it has already
computed"); multipart made testable (invariant 2: "no body ETag contains `-`"); a ratchet that
the engine crate carries no application identifiers (A §15.7); the old invariant 20 split
(now 14 and 15) and the duplicate rendition clause removed; the "25 URLs in 7 lists" count
replaced by the rule it stood for (DM §6.3). The `page_links` growth question is moot: links
now live on the page body's reading, stored once per body (A §8.3).

## 2. What the restructure kept, lost or changed

**Kept.** Every requirement from the four reviews has a home: F1 `filename_readings` (A §8.4,
DM §6.3); F2 LIST + ETag verification with no HEAD and no daily re-hash (A §7.4); F3/F4 Basin
named, compaction gated, dated-Parquet fallback (A §8.7, P §5.1); F5 no ID in `list` (A §10.1);
F6 offset-index page reads, folded detail, key columns at 16 KB (DM §8.1); F7 in-memory
grouping with a cap, placeholders at *k* = 100, star nodes (A §9.3, DM §7.3–7.5); F8 scope by
family, sniff for every older body (A §8.3); F9 determinism is not dedupe (A §10.2); F10
date-shaped prefixes (A §7.2, §8.2); F11 parity by cause against the pinned catalog pair, now
explicitly not against F0 (P §6.5); F12 Node canary, three jobs (A §10.3.5, §12); the rev-5
items (endpoint, `capture_index`, record roles, link context, recovery kinds, import runs by
registry, `url_state` without a hash, content identity, inputs records, two releases, 404
reload); the sanity-check items (five tables consistently, `ordinal` int32, `requested_url`,
"at least two" releases with a pointer `previous_release_id` null until the second flip,
`real_body`, the API registry, recovery-only documents, the recheck registry, total orders,
fixed list orders, Senate codes only with sample tests); and the four items above.

**Lost.** Nothing required. Two measured numbers left the architecture (the 4.05 / 15.8 /
45.9 MB `list` comparison; the $0.37 and $72 costs) under the owner's rule that only sizing
numbers stay; the decisions they supported are made. `url_state.links_scanned` is gone,
correctly: the queue (DM §7.7) replaces what it was for.

**Changed meaning, deliberately and for the better.**
- Links come from each HTML/XML page's reading, stored once per page body, not per fetch (A §7.2,
  §8.3; DM §6.2). Receipts no longer carry `links`. This is do-once applied to link context and
  removes a table.
- Writers check `…/<sha>.gz` before each create-only PUT and record `stored_suffix` (A §7.1; DM
  §5.2, §6.1). This closes a real hole: a new-format key would never 412 against a legacy
  `.gz` duplicate, so without the check duplicates of the 1.04M legacy bodies would be stored
  twice. Cost: one HEAD per body not yet seen in the run, 259–3,520 a day on normal days
  (measured), and it is one of the two HEADs §13.5 allows.
- The crash-attribution gap is accepted in words (A §7.1).
- Publish and maintenance share one CI concurrency group, and the architecture admits the one
  CI dependence (A §10.3.7, §12). This closes the retention race I raised in rev 5.
- A body at an edition-ambiguous endpoint takes no rendition edges (DM §7.5), which is stricter
  than "no edge at the endpoint" and blocks transitive merges through mirrors.
- `recoveries.parquet` is its own ranged file with `rec_start`/`rec_len` in `detail`, and
  `meetings.parquet` carries hearing titles (DM §8.1).
- The input identity is now receipt keys + provenance keys/ETags + model profile (DM §8.3),
  with the completeness gate carrying the rest of the argument (§3.4 below).

## 3. The new parts

### 3.1 Links on readings and `linked_from`

**Correctness.** The HTML and XML parsers emit each page's links with `group_path`, label and
attributes (DM §6.2); listing pages still supply links though they are not documents (DM
§7.3); `same_rendition (a)` groups links by `(page body, group_path)` (DM §7.5); `linked_from`
takes the earliest link whose `child_url` has the occurrence URL's `url_key`, in a total order
that first reduces each page body to its first real fetch (DM §7.10). All deterministic given
the inputs.

One gap: `base_url`, against which relative links are resolved, is "the page's `<base href>`,
else the URL of the body's first capture row" (DM §6.2). A reading is a lake row computed once,
but its first capture row can change when a late receipt is ingested, so the reading is not a
pure function of the body and the pinned version. Invariant 1 then asserts something that can
fail by design: "A parser version re-run on a sample of its inputs reproduces its rows, links
included." The fix is one sentence either way: store `href` unresolved plus `base_href` in the
reading and resolve in the model (O(links) string work per run, which the model already does
for `url_key`), or define the re-run test with the reading's recorded `base_url` as an input.
A second, smaller consequence: a mirrored page's relative links resolve against the first
mirror's host only. Must-fix for the invariant's sake; small either way.

**Big O.** Unnest ≈4.2M links (estimated from an 80-body sample; 287,765 HTML and XML bodies
measured exactly), `url_key` each (regex, O(L)), hash-join to ≈1.7M source URLs by `url_key`
(O(L + S)), reduce to the earliest per occurrence (an `arg_min`, linear). Fan-in (a privacy
page linked from 100k pages) and fan-out (a page with thousands of links) stay inside O(L).
Nothing superlinear. The passes are named in principle 4 and M2 measures them with build sizes
(P §5.2). `readings` grows by the links: at ≈100–150 B per link after dictionaries, about
0.4–0.6 GB raw and ≈100 MB compressed (estimated), so A §13.6's "keep wide columns off the
build side" applies to `readings.links` as it does to the fold.

### 3.2 The `url_state` queue

DM §7.7: each child URL of a real or listing page that matches the capture-scope registry and
whose `url_key` no capture row's requested URL shares becomes one row (`attempts = 0`, due now),
one per `url_key` under its byte-wise least child URL. Recomputed each run from readings, never
stored: an anti-join of distinct child keys against requested keys, O(L + U). Deterministic.
Invariant 12 covers it. Two notes, neither a defect: a link to a redirect's *final* URL does
not match the `requested_url` that produced it, so it is fetched once more and then leaves the
queue (self-healing, one extra fetch); and the queue's size is set by the capture-scope
registry, which S must write with care. The quoted 16,753 waiting URLs could not be reproduced
from the snapshot (links are not in it); from today's old occurrences I get 19,971 unfetched
link keys of 650,942, the same order of magnitude and without the scope filter.

### 3.3 The model profile and its completeness gate

DM §7.1: the profile pins model SQL, engine, one version per parser, the catalog, one version
per registry (its SHA-256) and the writer settings; a new version backfills while the old is
pinned, the profile moves when the new work list is empty, the daily run produces every pinned
version for new inputs, and "Publish MUST refuse when a pinned version's work list is not empty
at the pinned snapshot" (also A §10.3.1). This is the right design: no release can mix parser
versions, and a registry change is a profile change that re-publishes without touching the lake
(A §10.3.2). The gate costs one anti-join per pinned version per run, O(table), already named
among the accepted passes. One interplay to state in words: DM §7.3 says a body that lands
between the fingerprint pass and the pin "gets its fingerprint one run later"; under the gate,
that run is *refused* (the fingerprint work list is not empty at the pin), not published
without the fingerprint. Both sentences are true; say which happens.

### 3.4 The input identity (DM §8.3)

The identity is the SHA-256 of the compact JSON of the sorted receipt keys ingested into
`captures`, the sorted keys and ETags of the provenance records, and the model profile. The
argument that equal identities mean equal model inputs holds: every other lake row the model
reads is a deterministic function of a body named by those receipts (readings, committee and
meeting records), of a `(filename, URL)` pair named by those receipts and provenance
recoveries (filename readings), or of a version in the profile (registries, writer settings),
and the gate (§3.3) guarantees every pinned version covers every such input at the pin.
Snapshot IDs are rightly excluded. Receipts are immutable and create-only, so a receipt key
names fixed content. Two residual dependencies are worth naming:

- the `captures` *ingest mapping* (P §6.4 D1 maps "older receipt shapes" in SQL) is not in the
  profile and `captures` has no version dimension. A mapping fix cannot rewrite an append-only
  table; it means a new table and a full backfill from 2,289 receipts (1.08 GB, minutes). Say
  so, and put the ingest code's version in the profile so the identity changes when it does;
- `base_url` (§3.1) makes a reading depend on `captures` at parse time; the fix above removes
  the dependency.

The weekly verification records change the provenance digest weekly, so the model runs and
the release ID comes out equal (A §10.3.3 "records the new input identity and stops"): minutes
of compute, no upload. Acceptable, and the early skip against "any input record of the live
release" (A §10.3.2) handles re-emergence.

### 3.5 `meetings.parquet` and `recoveries.parquet`

`meetings.parquet` (DM §8.1): one row per meeting a listed document references, from the
current `meeting_records` record, `(chamber, event_id)` order, one row group, 1–2 MB. Measured
today: 8,956 House event IDs ∪ 12,041 Congress.gov meeting IDs with 7,243 shared = 13,754
meetings, so a few hundred KB to 1.4 MB with titles; the estimate holds. A §10.1 reads it
"whole when a hearing is shown"; cache it per session or the hearing view costs 1–2 MB each
time (§5 item 7). `recoveries.parquet`: `(list_row, ordinal)` ranges named by `rec_start`/
`rec_len`, a 1,024-row page limit, 1–3 MB; rows are the ≈24k accepted recoveries plus the
5,587 Oct 15 imports (measured) at ≈150 B each, so 1–3 MB is right. Invariant 18 covers both
range partitions; invariant 16 covers `list_row` bounds and `meeting_refs ⊆ meeting_keys ⊆
meetings`.

### 3.6 `detail`: 19 leaves and size

Counted from DM §8.1: `link_key`, `saved_body`, `saved_suffix`, `saved_media_type`,
`occ_start`, `occ_len`, `rec_start`, `rec_len` (8); `alternates` format/body/suffix/size (4);
`meeting_refs` chamber/event_id (2); `govinfo_package_id`, `measure_keys`, `bioguide_ids` (3);
the fold's field and value (2): 19. Size 55–70 MB at 0.65M documents: my recomputation gives
≈65 MB (124 MB at 1.24M rows). Per view ≈49 KB under the adopted settings, inside the stated
70–90 KB. The offset index for 19 leaves at these page sizes is roughly 300–500 KB at 0.65M
rows (estimated: ≈19 leaves × ≈1,000–1,500 pages × 16 B), fetched once per session; the
10×-rows shard trigger (A §10.1) is still the right place to revisit it.

## 4. Spot-checks

| Claim | Where | Result | Status |
|---|---|---|---|
| Normal day: 3,553 capture rows from 2,946 receipt lines on 2026-10-16 | A §5 | 2,946 / 3,553 | **measured**, exact |
| 2.7M of 3.9M capture rows carry no time | DM §7.5; P §6.4 | 2,717,129 of 3,909,134 | measured |
| Source files with several measure numbers / date tokens / congresses: 498 / 955 / 2 | DM §6.3 | 498 / 955 / 2 | measured, exact |
| 287,765 HTML and XML bodies | DM §6.2; P §6.4 | 287,765 (214,041 with a 2xx) | measured, exact |
| About 4.2M links over those bodies | DM §6.2 | ≈14.6 per body, from the owner's 80-body sample | taken (estimated by the owner) |
| 16,753 linked-but-unfetched URLs | DM §7.7 | 19,971 unfetched link keys of 650,942 from today's occurrences, before the scope filter | estimated; same magnitude |
| Import day 708,626 lines / 745,456 rows; bodiless lines 1,041,863 of 2,596,054 | A §5; DM §6.1 | from the previous pass: exact / 1,041,865 | taken (measured earlier) |
| Placeholders 18 at *k* = 100 (22 / 12), the 57-byte caption file at 87,161 URLs | DM §7.3 | from the previous pass: exact | taken |
| 34,000 HTML archive members at ZIP URLs | DM §7.3 | from the previous pass: 34,443 | taken |
| 148 endpoints / 297 bodies / 1.4 GB fingerprint candidates | A §8.3; DM §6.2 | from rev 5 | taken |
| Meetings referenced today (rows of `meetings.parquet`) | DM §8.1 | 13,754 | measured |
| Recovery rows: 5,587 Oct 15 imports plus ≈24k accepted decisions | DM §8.1 | 5,587 measured; 24,028 taken from P §1 | measured / taken |
| Older-copy HEADs per normal day | A §7.1 | 259–3,520 bodies touched on Oct 13–16 | measured |
| `detail` 55–70 MB, ≈19 pages, 70–90 KB per view | DM §8.1; A §16.1 | ≈65 MB; 19 leaves; ≈49 KB | estimated, consistent (conservative) |
| `list` 2–3 MB; `links` 7–9 MB; `occurrences` 20–30 MB; `url_state` 10 MB; `recoveries` 1–3 MB; `meetings` 1–2 MB | DM §8.1 | consistent with earlier measurements (1.68 MB at 0.5M with meeting ids; 10.7 MB at 963k keys; 22.7–33.6 MB at 4.7M rows; 42.8 MB with a hash) and §3.5 | estimated, consistent |
| Uploads about 105 MB; up to 0.7 GB of releases in a week | A §16.1, §10.3.7 | sum of the file sizes; 7 × 105 MB | derived |
| Listed documents 0.5–0.7M | A §5; DM §7.5 | my breakdown, now also less listing pages | estimated |

## 5. Findings

1. **must-fix (one sentence).** `base_url` makes a reading depend on `captures` at parse time,
   so invariant 1's re-run test can fail after a late receipt (§3.1). Store `href` and
   `base_href` unresolved and resolve in the model, or define the re-run with the recorded
   `base_url` as an input.
2. nice-to-have — State that a fingerprint landing between the fingerprint pass and the pin
   makes the gate *refuse* that run (DM §7.3 vs §7.1), not publish without it.
3. nice-to-have — `captures` has no ingest version and no replace path; say that a mapping fix
   is a new table plus a minutes-long backfill, and add the ingest code's version to the
   profile (§3.4).
4. nice-to-have — `url_key`'s last step recurses through `url_variants` (DM §7.2); bound it to
   one level or have the registry test reject cycles.
5. nice-to-have — `link_url_key` is "`url_key` under the registry versions fixed when link keys
   were first published" (DM §8.2); name those versions as a profile field so they are pinned,
   not remembered.
6. nice-to-have — DM §6 should carry the clause P §5.1 states for it: the row-group sizes assume
   the engine's remote write caps go.
7. nice-to-have — A §10.1 reads `meetings.parquet` "whole when a hearing is shown"; say once per
   session.
8. nice-to-have — The queue matches `requested_url`, so a link to a redirect's final URL is
   fetched once more before it leaves the queue (DM §7.7); fine, worth a sentence so nobody
   "fixes" it.

## 6. Grades and verdict

**Architecture: A (93).** Every mechanism, rule, order and registry now has one home; the
MUSTs are testable (the two I named last time now are); the identity argument is sound given the
gate; all recurring cost is O(change) or named as an accepted pass; the new decisions close
real holes (legacy duplicates, the retention race) without adding history-shaped work. The one
remaining defect is a single sentence about `base_url`.

**Plan: A− (92).** Lean, dependency-ordered, measurement-first (M1 decides DM §6, M2 measures
the link join and the wide joins, S writes the rules with adversarial fixtures and a labeled
sample before engine work), with a switch checklist that includes the B13 copies and the speed
targets. It stops short of an A only because the queue's scope registry and `readings.links`'s
volume are first seen in S and D rather than measured in week one, and because the parity
causes, though complete, will be read against a catalog whose link labels came from a different
source.

**Verdict: ready to build from.** Fix item 1 in the data model before track D's parsers are
written; the rest can land as the sections are touched.
