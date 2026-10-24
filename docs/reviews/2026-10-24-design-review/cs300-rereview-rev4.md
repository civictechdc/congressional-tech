# CS 300 re-review: engine-first architecture revision 4 and simplification plan revision 2

> Owner's note, added Oct 24: hyparquet 1.31.2 does read single pages through the offset
> index (`useOffsetIndex` and `pageLocations` in `src/plan.js`); the README just doesn't
> say so. The row-group-granular premise in §2(b) and §4 item 1 therefore doesn't hold.
> Design revision 5 uses offset indexes and the folded `detail` layout this review
> measured as the page-granular winner.

Reviewer role: systems / data-intensive software engineering. Date: 2026-10-24.
Reviewed: `docs/engine-first-architecture.md` revision 4 (cited **D4:line**) and
`docs/plans/simplification-plan-20261024.md` revision 2 (cited **P2:line**), both at
`cfa1c7c2`, plus my first review (`cs300-efficiency-review.md`, cited **R1 §/F**). Not read:
pipeline code, engine source, tickets, the other reviews.

New measurements this pass (same data snapshot, same venv, script
`measurements/rereview_checks.py`, outputs quoted inline): the
`filename_readings` key cardinality, the grouping rule with a placeholder threshold,
three detail layouts at two page sizes, detail footer size against row-group size, duplicate
body attempts per day, non-date receipt prefixes, and the public hyparquet README
(fetched with `congressional-tech-review/1.0`). Facts about Basin Catalog are the owner's,
fetched today; I did not re-fetch them.

## 1. F1–F12: resolved, and resolved correctly?

| F | Status | Where | Verdict and evidence |
|---|---|---|---|
| F1 filename extraction had no home | **Resolved** | D4:81, D4:178–189, D4:399; P2:217–218 | Correct. Key `(filename, source_url, catalog_version)`; work list by anti-join; daily < 1 s. Measured cardinality: **1,392,681** distinct `(filename, source_url)` pairs in today's filenames table (D4:189 says "at most 1.35M"; 3 % low), so a catalog backfill is 1.39M × 0.31 ms ≈ **7.2 min**, as stated. One guard: if the producer ever passes `member_surnames` (README "Optional surname context"), that vocabulary's digest must be part of `catalog_version`; today's columns carry no surname tokens, so nothing is wrong yet. |
| F2 verification grew with history | **Resolved** | D4:102–109, D4:112–117, D4:132–141, D4:381–382; P2:141, P2:161–165 | Correct shape: MD5 in receipts, weekly `LIST ⟕ captures` on (key, size, ETag), a 25-body sample, no daily re-hash, a one-time baseline for legacy bodies. Two sharp edges remain, both in §3 below: what a writer does on a 412, and gzip determinism; without them the weekly join reports false mismatches on duplicate attempts (54 % of body-bearing attempts on Oct 16 hit an existing body). |
| F3 Iceberg growth without compaction | **Partly resolved, correctly gated** | D4:191–200, D4:413–414, D4:422; P2:73–82 | Maintenance is delegated to Basin (compaction 128 MB target, expiry 30 d / keep 5), with the one thing Basin's docs don't promise, bounded manifests, made a week-one measurement (M1) and a named fallback. That is the right way to carry an unverified dependency. Stays open until M1 reports. |
| F4 catalog unnamed | **Resolved** | D4:77, D4:145–148, D4:343–345 | Basin Catalog named; commit requirements stated. "The engine already uses" it is unverified (needs engine check); P2:73–74 says requirements are not yet sent, which M1 step 1 fixes. |
| F5 `list` size | **Resolved** | D4:234, D4:239–241, D4:433–435 | Correct and matches my numbers (4.05 / 15.8 / 45.9 MB). Row number is the key; deep links resolve through `ids`. |
| F6 point reads and footers | **Not resolved; the mechanism is wrong** | D4:235, D4:243–249, D4:255–257 | Binary hashes and shards are right. But "one page per column, located by the page index" assumes a reader capability the named library does not document: hyparquet's README (lines 23, 47–48, 106) offers `rowStart`/`rowEnd` over HTTP range requests and row-group reads, nothing about the offset index. At row-group granularity the footer, not the page size, sets the cost, and the shard threshold "at roughly 10 times today's rows" (D4:248) is wrong today. Measured in §2(b). |
| F7 grouping | **Resolved** | D4:218–226, D4:348–349, D4:425; P2:226–227 | Correct and measurably sufficient. With error sources dropped, body edges capped at degree ≤ *k* and (filename, URL) endpoint edges: *k* = 1000 → largest component 1,939; *k* = 200, 50 or 10 → largest **456**; adding "HTML bodies don't connect" gives 1,260,423 components, close to today's 1,241,157 documents. Only 12 bodies have > 200 source files and 6 have > 1000, so *k* anywhere in 50–200 excludes a dozen placeholder pages and nothing else. |
| F8 readings scope | **Resolved** | D4:162–176, D4:437–438; P2:213–216 | Correct: per-media-family parser versions, HTML/XML/JSON first (≈5 GB; measured 4.9 GB), PDF as a background decision. Gap: 73,644 untyped bodies (37 GB, `media_type` null) have no scope rule; say whether they are sniffed or skipped. |
| F9 dedupe claim | **Resolved** | D4:271–273, D4:281, D4:296–297, D4:424 | Correct: determinism kept for idempotence, per-release prefixes, no reference sweep, 150 MB/day accepted. A new edge case in the manifest (§3) is the only residue. |
| F10 receipt LIST | **Resolved in intent, broken on today's keys** | D4:74, D4:112, D4:154–158; P2:146, P2:206 | Per-family listing from the newest ingested date is the right shape once keys carry a write date. But today 48 receipt files under `…/undated/` hold **2,193,107 rows**, one `mixed-dates` file holds 4,154, and for **15 of 21 families the lexicographically largest key is `undated/` or `mixed-dates/`** (`'u' > '2'`). A `StartAfter` taken from the newest *key* would skip every dated receipt for those families until the weekly full LIST. Fix: take the newest *date-shaped* segment and list only date prefixes, or list the last N date prefixes explicitly; treat non-date segments as backfill-only. |
| F11 parity | **Resolved** | D4:485; P2:95–103, P2:233–242 | Correct: F0 converted from the pinned catalog is the oracle, parity on browser-visible fields, golden ID vectors, the 38–95-minute rebuild dropped. |
| F12 moving parts | **Resolved** | D4:288–291, D4:304–305, D4:319, D4:386–388 | Correct: Node canary on the publish path (< 1 min), headless browser only in the CI contract test, three scheduled jobs. New parts are accounted for in §4. |

Net: nine resolved correctly, one correctly gated (F3), one broken on current keys (F10),
one with the wrong mechanism (F6).

## 2. The two departures

### (a) `filename_readings` keyed by the full source URL — right

The README is explicit that some readings are qualified per exact URL ("Exact reviewed
mirror URLs can qualify an occurrence without extending the convention to every file on that
mirror", README:393–394; "Supply the source of that particular occurrence", README:414–415).
The catalog carries 9 `source_urls` lists naming 71 distinct URLs on 33 hosts, so a host key
would be wrong for those 71 URLs and a host-plus-exceptions key is more machinery than it
saves. The cost difference is immaterial: 1,392,681 `(filename, URL)` pairs vs 727,025
`(filename, host)` pairs, i.e. 7.2 vs 3.8 CPU-minutes **once**, and under a second a day
either way. The key must include the filename, not just the URL: 32,574 rows today have a
filename that is not the URL's basename (recovered cache names). Verdict: correct as written;
add the surname-vocabulary guard from F1.

### (b) Detail not folded into one struct — right reason, wrong conclusion, and a larger problem underneath

The owner's premise is correct: a flat `Struct` is shredded into one leaf column per field, so
it saves no requests. The fold I meant is the shape D4:165–166 already uses for readings,
`List<Struct<field, value>>`, where fields become rows of the inner list: three leaf columns
regardless of field count. A single serialized blob column is the degenerate case with two.
Measured on the real documents (1,241,157 rows, ZSTD-3, Parquet 2.0, estimates of bytes per
view assume page-granular reads):

| Layout | Leaf columns | File | 64 KB pages: bytes per detail view | 16 KB pages |
|---|---|---|---|---|
| Flat, 9 columns, binary hashes | 9 | 175.4 MB | ≈319 KB in 9 requests | ≈82 KB in 9 requests |
| `List<Struct<field,value>>` fold | 3 | 162.5 MB | ≈86 KB in 3 requests | ≈22 KB in 3 requests |
| One JSON blob column | 2 | 162.8 MB | ≈64 KB in 2 requests | ≈16 KB in 2 requests |

So the design's "roughly 80 KB in ~8 requests" (D4:243–244) is the flat layout at 16 KB pages,
and a two- or three-leaf layout would be 4–5× fewer bytes and 3–4× fewer requests. That
would settle (b) in favor of folding **if** reads were page-granular. They are not with the
named reader:

- hyparquet documents range requests and `rowStart`/`rowEnd` (README:23, 47–48, 106), i.e.
  it fetches the column chunks of the row groups that overlap the requested rows. No page
  index. Whether a page-granular read is possible through its lower-level API is
  **unverified (needs reader check)**.
- At row-group granularity the layout no longer matters (every layout fetches the same
  row-group bytes); only the row-group size does, and the footer grows with the number of row
  groups. Measured on the flat detail file:

| Rows per row group | Row groups | FileMetaData | Bytes per detail view (one row group, all chunks) |
|---|---|---|---|
| 1,024 | 1,213 | **1,975 KB** | 160 KB avg, 290 KB max |
| 4,096 | 304 | 497 KB | **622 KB avg, 983 KB max** |
| 16,384 | 76 | 129 KB | 2.4 MB avg, 3.5 MB max |
| 131,072 | 10 | 18 KB | 17.9 MB avg, 22 MB max |

Under the design's own 512 KB footer rule (D4:257), a single-file `detail` needs ≥ 4k-row
groups and therefore costs **0.6–1 MB per detail view**, eight to twelve times D4:244, at
today's scale, not at 10×. The same arithmetic applies to `ids` (43 MB: 140 KB per lookup at
4k-row groups, 47 KB with 8-byte ids) and to `occurrences` (4.7M rows: a 512 KB footer forces
≈16k-row groups, ≈100 KB per range read; fine).

**What to do.** Use the shard mechanism D4:246–249 already defines, now rather than at 10×:
split `detail` into fixed row-range shards (64–256 files of 5k–20k rows, each with 1k-row
groups), so a detail view is one small footer (≈10 KB) plus one 160 KB row group, and
`ids` into a few shards by id range. Cost: 64–256 PUTs per release, Class A, ≈$0.001/day; the
manifest already lists shard row ranges. Keep the flat columns (the owner's choice) because
layout is irrelevant at row-group granularity, and drop the two derivable detail columns
(`source_id`, derivable from the triple per D4:213; `body_sha`, the first of `body_shas`): that
is how the stated "about 100 MB" (D4:235) is reached from the measured 175 MB. Revisit the
fold only if a page-granular reader is adopted.

## 3. New claims not in my review

| Claim | Verdict | Evidence and cost |
|---|---|---|
| Release ID = digest of the file list, not the inputs (D4:278–280, D4:286–287) | **Right, with one edge** | Byte-identical exports give the same ID under a catalog compaction or a no-op rerun, which is exactly what idempotence needs. Edge: the manifest *includes* the inputs (D4:283–286) and lives under the create-only key `releases/<id>/manifest.json`. A release that re-emerges with different snapshot IDs (a rollback, a rerun after compaction, a non-live earlier release) writes identical files (412, MD5 matches) but a different manifest (412, MD5 differs) and fails. Fix: inputs in a per-run sidecar (`releases/<id>/runs/<run>.json`) or exclude the inputs block from the 412 comparison. |
| Per-release prefixes, no shared objects, no sweep (D4:281, D4:296–297) | **Right** | 150 MB/day of PUTs ($0.00002), ≈2 GB steady state for 10 releases ($0.03/month), a weekly LIST of ~15 prefixes. Missing: where "pinned" releases are recorded (D4:296); name the file. |
| Capture reads `url_state` from the live public release (D4:316, D4:326–328; P2:249) | **Right, and a good simplification** | Removes lake and release credentials from the capture job (D4:371). Costs: `url_state` is ≈30–45 MB per release (measured 44.7 MB with hex hashes), downloaded once per capture run and stored 10× (≈0.4 GB); it is absent from the §6.2 file table and from the canary's checks, so add it to both. Staleness is bounded by publish cadence and is safe because writes are create-only. Bootstrap: F0 has no `url_state`, so capture keeps the raw index until track F (P2:249), which means the revision-1 E1 cost (whole-leaf rewrites, O(S+B) per run) continues for 8–16 weeks; acceptable, but the plan should say it. |
| Per-media-family parser versions (D4:162–164, D4:173–176) | **Right** | A new HTML parser re-reads ≈5 GB, not 590 GB. The work-list anti-join is a relational pass over ≈1M rows per run (seconds), which principle 4 (D4:34–36) permits. |
| Node canary instead of a production headless run (D4:288–291, D4:304–305) | **Right** | Same reader module, under a minute, no browser. Run it against the *uploaded* candidate over HTTPS so Range and immutable caching are exercised; CORS cannot be tested from Node, and the CI contract test (D4:386–387) covers it. |
| Two digests per body: original SHA-256 plus stored MD5 as the ETag, no stored SHA-256 (D4:102–109, D4:115) | **Right in principle; two semantics are undefined** | MD5 as a non-adversarial integrity check that R2 verifies on upload is sufficient; a third digest adds nothing. But (i) **the 412 path**: "the writer checks the ETag against its MD5" (D4:109) needs the existing object's ETag, which a 412 response is not documented to carry, so as written it is a HEAD per duplicate, contradicting D4:350; duplicates are common (1,831,013 of 2,867,269 body-bearing attempts historically; 1,935 of 3,553 on Oct 16). (ii) **gzip determinism**: the writer's MD5 of a freshly compressed duplicate equals the stored ETag only if compression is byte-deterministic (pinned library and level, zero mtime). Without that, every duplicate of a compressible body "mismatches" on the 412 path and in the weekly join. Fix: on a 412 record `unchanged` with the computed MD5 and no HEAD; the weekly join compares the ETag with the receipt line that *created* the object, and reports other lines only as "different encoding"; pin and test deterministic gzip. (iii) New receipts carry no stored SHA-256, so D1's multiset comparison with the old index (P2:210) must exclude that column for new rows. |
| Basin Catalog facts (owner-fetched): GA, compaction 64–512 MB, expiry by age and retain-last, data files of expired snapshots deleted, orphans not removed, manifests unsaid | **Consistent with D4:192–200** | The design's numbers sit inside the documented ranges and its "to confirm" is the one undocumented property. Two notes: compaction is a paid Basin feature (price unknown to me; bounded by ≈315 KB/day of appends plus rewrites of the last partial file, a few GB/month at most), and it rewrites data files, which D4:27 ("never update") should mention is Basin's doing, not a row edit. |

## 4. What revision 4 and plan revision 2 got wrong or introduced

Ranked by effect on efficiency or correctness.

1. **Point-read cost mis-stated by ~8× and the shard trigger wrong (D4:235, D4:243–249).**
   See §2(b). Fix: shard now; state the row-group size per file; verify or drop the page-index
   claim.
2. **Receipt ingest skips 15 of 21 families on today's keys (D4:154–158).** See F10. Fix is
   one sentence.
3. **412 semantics and gzip determinism undefined (D4:106–109, D4:132–135).** See §3. As
   written it either HEADs every duplicate or raises false mismatches.
4. **Early skip is too eager (D4:276–277).** "If ingest appended nothing and the work lists
   were empty, publish stops before the model runs" ignores provenance records and SQL,
   engine, parser and catalog versions, all of which change the output (D4:206–207,
   D4:284–286). A human review decision or a model change would not publish until the next
   capture. Fix: key the skip on the full input identity the manifest already records.
5. **Manifest-with-inputs under a create-only key contradicts the file-list ID (D4:278–287).**
   See §3, first row.
6. **`url_state` is a release file but not in the release (D4:232–237 vs D4:326).** Add it
   to the file table, the manifest and the canary.
7. **Untyped bodies have no readings scope (D4:168–172).** 73,644 bodies, 37 GB.
8. **"HTML bodies don't connect anything" (D4:220) needs its reason written down.** It is
   measurably helpful (1.26M components, largest 456) but it also keeps identical transcript
   HTML at two URLs apart; say that is intended.
9. **F0 go-live and ID churn (P2:95–103, P2:335–336).** F0 carries the old pipeline's
   `document_id`s; the new grouping rule regroups some documents (the HTML rule alone
   yields 1,260,423 components vs 1,241,157 today, so at least ≈1.5 % of IDs change at the
   switch). Either accept broken deep links for those, or ship an alias file once. The plan
   should choose.
10. **Open question 6 (legacy gzip bodies, P2:343–344) sits on track A's path and has no
    numbers.** Saved-copy links depend on it. Options: an edge rule can set
    `Content-Encoding` by key pattern but not the original `Content-Type`, which today's
    objects do not carry (served as `application/gzip`, R1 §0), so that route is a Worker
    with a sha→media-type lookup; or a one-time rewrite under target keys: all legacy bodies
    = 1.04M PUTs ($4.7), 0.70 TB through a runner (≈2–4 h in batches), and **0.70 TB of
    permanent duplicate storage under the indefinite lock (≈$126/year)**; compressible types
    only = ≈300k PUTs, 5 GB, ≈$0.9/year, but leaves 261k PDFs (365 GB) downloading as `.gz`.
    Not an efficiency decision at this scale; it is a week-one decision.
11. **Track C is one 3–6 week block with seven capabilities (P2:111, P2:185–193).** C3
    (deterministic sharded export with two digests while writing) and C1 (Basin tables and
    Parquet in one context) are the large ones; give each a week estimate so M1/M2 can shrink
    the right one.
12. **Minor:** D4:189 "at most 1.35M pairs" is 1.39M; D4:235 "about 100 MB" is reached only
    after dropping the two derivable columns (measured 175 MB with them); P2:97–98 "built all
    four files in 24 s" — `build_list.py` built three (list, ids, detail) in 24 s and
    `size_occ_captures.py` built occurrences separately; D1's multiset comparison (P2:210)
    must be on receipt-derived columns only.

Contradictions between the two documents: none of substance. Both agree on the three
tables, the release layout, the canary split, the credentials and 8–16 weeks (D4:488,
P2:117). The only cross-document gap is item 6 (`url_state` as a release file in D4:326 and
P2:249 but absent from D4:232–237).

## 5. Re-grades

| Axis | Rev 3 | Rev 4 | Δ | Why |
|---|---|---|---|---|
| 1 Asymptotics | B+ 87 | **A− 90** | +3 | Every recurring job is now O(change) or O(listing) by design (F1, F2, F10 in intent, F3 gated). The `undated` prefix and the 412 path are implementation edges, not design shape. |
| 2 I/O and network | B 82 | **B+ 87** | +5 | Verification fixed, early skip added, per-release prefixes. Held back by the detail read path (0.6–1 MB per view under the documented reader) and the possible HEAD per duplicate. |
| 3 Do-once | B 80 | **A− 90** | +10 | `filename_readings`, two digests with one job each, no re-hash, per-family parser versions. The early skip is in the right direction but keyed on too little. |
| 4 Bytes | B+ 85 | **B+ 87** | +2 | `list`, `ids`, `occurrences` right and matched to measurements; `detail` reaches 100 MB only after dropping derivable columns; per-view bytes mis-stated; `url_state` unlisted. |
| 5 Compute and memory | A− 90 | **A 93** | +3 | In-memory CC with a cap and a grouping rule that measurably works (largest component 456). |
| 6 Simplicity | B− 78 | **B+ 86** | +8 | Basin replaces engine maintenance, Node canary, three jobs, capture decoupled from the lake. New parts: a managed catalog, a temporary converter, an undecided legacy-body route, and two undefined semantics (412, early skip). |
| 7 Plan | C+ 70 | **B+ 85** | +15 | Rewritten around measurements first, parallel tracks with estimates, an early live release, an explicit map from revision 1 and parked items. Short of an A: track C unsplit, F0→E ID churn and open question 6 undecided on the critical path, the `undated` prefix in D1. |

**Architecture: A− (89), from B+ (84).** It moved because the four findings that changed
cost classes (F1, F2, F7, F10) are fixed and F3 is honestly gated; it stops short of an A
because the browser read path rests on an unverified reader capability and three write-path
semantics are undefined.

**Plan: B+ (85), from C+ (70).** It moved because it now measures before committing, runs
site and raw work in parallel, puts value live in weeks 2–3 and carries real estimates; it
stops short of an A− because the largest block is unsplit and two decisions it needs in week
one (legacy bodies, ID churn at the switch) are not scheduled.

## 6. The three changes that matter most now

1. **Fix the browser read path to the reader you have.** Shard `detail` and `ids` now (small
   footers, 1k-row groups), state row-group sizes per file, drop the two derivable detail
   columns, and either verify page-index reads in hyparquet or delete the claim.
2. **Define the raw write path precisely.** Deterministic gzip (pinned, tested); on 412
   record and move on, no HEAD; the weekly join compares the creating receipt line; ingest
   lists date-shaped prefixes only. Four sentences in §4 and §5.1.
3. **Key the early skip and the manifest 412 on the right identity,** and schedule the two
   week-one decisions (legacy saved copies; whether IDs may change at the switch) so tracks A
   and E have fixed targets.

## Appendix: measurement log for this pass

| Measurement | Result |
|---|---|
| Distinct `(filename, source_url)` / `(filename, host)` / `filename` in filenames.parquet | 1,392,681 / 727,025 / 564,604 |
| Rows where filename ≠ URL basename | 32,574 |
| Catalog URL qualifiers (`guide.json`) | 9 `source_urls` lists, 71 URLs, 33 hosts |
| Body-bearing attempts that hit an existing body | 1,831,013 of 2,867,269 overall; Oct 13–16: 76/953, 1/270, 881/2,437, 1,935/3,553 |
| Non-date receipt prefixes | `undated`: 48 files, 2,193,107 rows; `mixed-dates`: 1 file, 4,154 rows; 15 of 21 families have a non-date largest key |
| Body degree (source files per body) | max 87,161; p99.9 = 8; > 10: 236; > 50: 20; > 200: 12; > 1000: 6 |
| Components with non-error sources, endpoint edges, body cap *k* | none: 1,033,646 (largest 174,323); 1000: 1,126,214 (1,939); 200: 1,128,970 (456); 50: 1,129,399 (456); 10: 1,131,285 (456); 50 + HTML excluded: 1,260,423 (456) |
| Detail layouts (file; est. bytes/view at 64 KB and 16 KB pages) | flat 175.4 MB (319 KB / 82 KB, 9 req); fold 162.5 MB (86 / 22 KB, 3 req); blob 162.8 MB (64 / 16 KB, 2 req) |
| Detail row-group size → footer, bytes per view | 1,024: 1,975 KB, 160 KB; 4,096: 497 KB, 622 KB; 16,384: 129 KB, 2.4 MB; 131,072: 18 KB, 17.9 MB |
| hyparquet README (public) | range requests, `rowStart`/`rowEnd`, `asyncBufferFromUrl`; no page/offset index mentioned |
