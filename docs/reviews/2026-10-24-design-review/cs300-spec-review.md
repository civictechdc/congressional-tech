# CS 300 Review: Congressional Document Archive specification set

Reviewed 2026-10-24. Submission: `architecture.md`, `data-model.md` (Editor's Drafts) and
`implementation-plan.md` (Note), all dated 2026-10-24, as they stood before this review's fixes. They were then adopted as
`docs/engine-first-architecture.md`, `docs/engine-first-data-model.md` and
`docs/plans/simplification-plan-20261024.md`.

Method. Phase 1 read the three documents alone, in order, and formed every judgment below
before any evidence or draft was opened. Phase 2 checked load-bearing numbers against the
2026-10-19 snapshot (`adoption-inputs/captures.parquet`, `filenames.parquet`,
`documents.parquet`, `state.parquet`, `readings/`) with DuckDB through the project venv,
inspected `packages/house-naming` at the `ct-ticket-audit` worktree, and then compared the
specs with the three source drafts for material drops. Scripts and raw outputs are in
`measurements/cs300-specs/`
(`spec_schema*.py`, `spec_measure_*.py`, `*.out`). Section numbers below are the specs'
own (`A §n` architecture, `DM §n` data model, `P §n` plan).

## Verdict

This is a serious, well-structured design: an append-only content-addressed raw log,
six append-only lake tables keyed by their inputs, one deterministic SQL job, and an
If-Match pointer flipped after a canary. The cost model is honest (every pass over history
is named), the grouping is linear by construction, and 20 of the invariants are stated so a
test can assert them. Most of the numbers I spot-checked reproduce exactly on the snapshot.

It is not yet buildable as written. Five rules an implementer must code have gaps that
cannot be resolved from the text: the record role of any body that no parser reads (which
is every PDF, the bulk of the corpus); the saved-file choice when a document has several
PDFs (a regression introduced while condensing the drafts); the point at which a publish
run pins its snapshots relative to the lake steps it also runs; a membership rule that the
data model defines at the body level and the architecture at the row level; and a
rendition-grouping heuristic whose discriminating predicate ("different formats") is
described but not stated. The data model also stores its largest key as hex against its own
"binary everywhere" rule, and the specification craft, while good, lacks conformance
classes and places plan work (measure, confirm) under MUST.

Fix the must-fix list, restore the handful of measurements that the condensation dropped,
and this is a specification a team can build from.

## Grades

| Area | Grade | Score | One line |
|---|---|---|---|
| Correctness and completeness | B− | 80 | Sound shape; five rules cannot be coded without guessing (M1–M5) |
| Efficiency (Big O) | A− | 90 | Linear edges, O(history) passes named, bounds honest; hex `saved_key` and an unbounded occurrence range are the misses |
| Determinism and failure behavior | B+ | 87 | Strong framework (unique sort keys, total orders, create-only, retry-by-recompute); gaps in tie-breaks, last-good tracking, version completeness under backfill |
| Data model quality | B | 84 | Right types for the right layer; `saved_key` hex, untyped `list` columns, undefined completion sentinels, chamber dropped from `meeting_event_ids` |
| Specification craft | B | 83 | Keywords mostly right; no conformance classes, no section marked non-normative, process MUSTs, two cross-document contradictions |
| Plan (dependency order, risk, executability) | B+ | 88 | Risks front-loaded (M1, M2, S, lock, B14); rendition rule never measured; a few over-constraints and unexplained items |

**Overall, the two specifications: B (84). The plan: B+ (88).**

## Strengths

1. **Raw as the only truth, implemented with platform primitives, not bookkeeping.** Body
   identity is the SHA-256 key; integrity is R2's MD5/ETag; existence is a create-only PUT
   whose 412 is recorded and never followed by a HEAD (A §7.1). Measured: 63.9% of
   body-bearing capture rows reference a body an earlier line already stored, so the
   spec's "over half" is right and the zero-cost 412 path matters.
2. **"Do expensive work once" is concrete, not a slogan.** Every lake producer has a work
   list defined as an anti-join on its own key (A §8.1), completion rows keep empty inputs
   off the list, and parsers are partitioned by `(parser, parser_version)` so a new HTML
   parser never touches a PDF (A §8.3). The passes that do scale with history are named
   in A §4.4 and A §16.1 rather than hidden.
3. **Grouping is linear by construction.** Files connect through one node per body,
   fingerprint or rendition group, so n files cost n edges (A §9.3), and the placeholder
   guard is justified by data I could reproduce: a single body at 87,161 distinct
   `context_url`s, and 22/18/12 bodies above k = 50/100/200 (DM §7.2, measured exactly).
4. **Public links do not depend on the mutable `document_id`.** `link_key` is the body's
   8-byte prefix, so links survive regrouping (A §10.1, DM §8.2); the recovery-URL key keeps
   a recovery-only page stable after the original downloads. Collisions refuse the export.
5. **Determinism is treated as an engine contract** (A §10.3): unique sort keys or refusal,
   fixed row counts per row group, pinned writer properties, no run-specific content, and a
   test matrix over threads, input order, batch size and a forced spill. The release ID is a
   content hash and the early skip uses an input identity (A §10.4.1–10.4.3).
6. **The release layout follows the reader.** `list` is downloaded whole and decoded
   column-by-column; `detail`, `links` and `occurrences` are page-addressed through offset
   indexes; the "no ID in `list`" decision is backed by a measurement (4.05 MB vs 15.8 MB
   vs 45.9 MB, A §10.1). The fold rule (DM §4) draws the right line between what the site
   acts on (native columns) and what it displays.
7. **Twenty testable invariants** (DM §10) that the plan turns into E2's test suite, plus a
   rebuild-equivalence check for `captures` and `page_links`. Invariants 7, 13, 15 and 16
   are the ones that catch grouping and export bugs; good choices.
8. **The plan front-loads the two decisions that could change the design** (M1 on Basin
   manifest growth, M2 on wide joins in DataFusion) and the semantics (S) before any engine
   work, keeps the explorer off the converted release, and reports parity by cause rather
   than by document (P §5, §6.5).
9. **Numbers are measured, and most reproduce.** Of 18 claims I checked, 12 match exactly
   or within rounding (see the evidence table below).

## Findings

### Must fix before building

**M1. `record_role` is undefined for every body no parser reads, so no PDF can be a real
file as written.** `DM §7.2` defines `record_role := r.record_role, written by the parser …
else document` and requires `record_role = 'document'` in `real_files`. `A §8.3` says
"PDF: no full reading for now" and "ZIP containers and captions: none"; `DM §6.2` says new
bodies are sniffed by the fetcher, not by a parser. So a new PDF, Office file, image or
archive member has no `readings` row, `r.record_role` is null, and the `and` chain rejects
it. The "else document" branch belongs to a parser that never runs on these formats. The
plan (P §6.4 D2) says "the real-file rule needs a sniffed format and record role for every
body", which confirms the intent but not the mechanism. Evidence from today's readings:
`record_role` is populated on 1,065 of 491,710 rows (1,027 `error-response`, 38
`document`), so nearly all of this is future work and the rule will be coded fresh.
*Fix:* define `record_role := coalesce(r.record_role, role_from_format(format))` in
DM §7.2 with `role_from_format` written out (`vtt → caption`, `m3u8 → playlist`, else
`document`), and state in A §8.3 that the fetcher's `sniffed_format` is sufficient for
non-parsed formats. Then invariant 5 stops being tautological.

**M2. The saved file is not uniquely determined when a document has more than one PDF.**
`A §9.4`: "links its PDF if it has one, and otherwise its newest real file by first
fetch". `DM §7.4`: "the component's PDF real file if it has one, else its real file ordered
by first_fetched desc nulls last, then body_sha". The ordering is attached to the `else`
branch only. The common case is exactly the one the spec designs for: same-text groups
("one document whose bytes were re-packaged… the page shows the newest bytes", A §9.3) are
several PDFs in one document. The source draft had one total order ("ordered by format
preference (PDF first…), then first_fetched desc nulls last, then body_sha"); the
condensation lost it. Invariant 10 does not catch this. *Fix:* restore the single total
order in both documents: `(format preference, first_fetched desc nulls last, body_sha)`.

**M3. When a publish run pins its snapshots is contradictory.** `A §10.4.1`: "Every
publish run MUST compute the input identity before doing any work… The run pins the lake
snapshots once at the start." `A §12` defines the publish job as "captures, page_links →
readings, filename_readings, committee_records, meeting_records → model + export → …".
Read literally, the identity and the pin happen before today's receipts are ingested, so
the model reads yesterday's snapshots and the early skip (A §10.4.2) compares yesterday's
identity to the live release's: a day with only new captures publishes nothing, or
publishes stale data. *Fix:* say that the lake steps run first (each idempotent on its own
work list), then the run pins the current snapshots, computes the identity, applies the
early skip, and runs the model against those pinned snapshots. One sentence, but it is the
sentence the orchestration code is written from.

**M4. Membership in a document is defined at two different grains.** `DM §7.3` defines
`is_real_file := body_sha in real_files` (a property of the body). `DM §7.4` and `A §9.3`
define the `same_body` edge over "source files whose own capture rows are real files", and
`P §6.5` E1 restates "edges connect only source files whose own rows are real" (a property
of the row set). These differ whenever one body is served with a 2xx at one URL and a
non-2xx at another, or by a recovery import: the body-level definition pulls the second
source file into the document; the row-level one does not. `members`, `occurrences` and
`n_members` all change with the choice. *Fix:* define `is_real_file` as "the source file
has at least one capture row in `real_files`" and say "at least one" where "own capture
rows" is used; the body-level property already has its own name, `real_body`.

**M5. The publisher-grouping rendition edge does not state its discriminating predicate.**
`DM §7.4 (a)`: "links on the same parent page whose source_xpath shares the nearest `<li>`
or `<document>` ancestor". The preamble says renditions are "one document in different
formats", but nothing in (a) requires the formats to differ or limits a group to one file
per format. A hearing page routinely lists, under one `<li>`, a witness's testimony,
truth-in-testimony form and biography, all PDFs; as written they become one document. The
labeled-sample measurement (A §15.8, P §5.3) covers page-shape, error-sign and placeholder
rules, not this one, and there is no component-size guard anywhere (the node cap in A §9.3
bounds memory, not merging). *Fix:* make (a) and (b) require distinct formats with at most
one file per format in a group, draw no edge for a group that violates it, add the rule to
the hand-labeled sample in S, and have the model report the largest components by edge
kind (the draft's own evidence, "1.26M components with at most 456 source files", was
dropped and is the only size data there is).

### Should fix

**S1. `saved_key` is a hex string in the file whose principle is "binary keys
everywhere".** `A §4.7`, `A §10.1` ("Binary keys everywhere except `list`") versus
`DM §7.4` columns ("`saved_key` string (physical key: `<sha>`, `<sha>.gz` or
`<sha>.pdf`)") and `DM §8.1`, which lists `saved_key` among "the incompressible key
columns" needing 16 KB pages. At 0.65M rows a 67-byte hex key is about 44 MB
uncompressed against 21 MB for `fsb(32)` plus a three-value dictionary suffix; the draft's
own note that "a proxy of just three key columns measured 49 MB at 650k rows" (dropped in
condensation) says most of `detail`'s 50–70 MB is this column. Estimated, not measured.
*Fix:* `saved_body fsb(32)` plus `saved_suffix dict('', '.gz', '.pdf')`; the reader hex-encodes.

**S2. The two normative documents disagree on the placeholder set, and the architecture
mislabels the biggest one.** `A §9.3`: "any k from 50 to 200 excludes the same dozen
bodies". `DM §7.2`: "k = 100 selects 18 bodies (22 at 50, 12 at 200)". Measured over
distinct `context_url`: 22/18/12, max 87,161, so the data model is right and the
architecture is wrong. The 87,161-URL body is a 57-byte `text/vtt` caption, not "one error
page". Also undefined: "seen at N URLs" counts which URL (`context_url`, `requested_url`,
`url_key`) and over which rows (all modes, or `mode = fetch`). *Fix:* one sentence in
DM §7.2 defining the count; correct A §9.3.

**S3. The input identity is specified two ways.** `A §10.4.1` asks for "the digests of
the receipt keys ingested" and, two paragraphs later, says it "uses content high-water
marks". `DM §8.1` says "digests or high-water marks". A high-water mark (newest date)
misses the late receipt the weekly check appends under an older date (A §8.2). *Fix:*
digest of the sorted set of ingested receipt keys for `captures` and `page_links`; row
counts per partition for the append-only parsed tables are fine because a key's content
never changes.

**S4. Nothing records which release is last-good.** `A §3` defines it, `A §10.4.7`
deletes everything else, and `A §11.3` promises stale tabs that it exists, but the pointer
`viewer-publications/manifest.json` is only ever said to "name the live release"; its
content is never specified. *Fix:* specify the pointer (`release_id`,
`previous_release_id`, `schema_version`), require the flip to carry the outgoing release
as `previous_release_id`, and have retention read both from the pointer it just re-read.

**S5. Parser-version completeness during a backfill.** `A §8.3`: "The model MUST read
only the newest complete version." While version 2 backfills in the background, new
bodies arrive daily; unless the daily producer also runs version 1 on them, version 1 goes
incomplete and no version qualifies, so every HTML body fails `real_files`. Invariant 5
says "current HTML parser version", a third term. *Fix:* require the daily run to keep
every version the model may read complete, define "complete" at the pinned snapshot, and
use one term.

**S6. Lake producers depend on model logic the spec places elsewhere.** The
`filename_readings` work list is "(filename, source_url) pairs in `captures`" (DM §6.3),
but `filename` is not a `captures` column; it is the model's effective-filename derivation
(DM §7.3), which reads provenance ("the recovered name if provenance says so"). The
`fingerprint` work list is "endpoints that produced two or more distinct complete real
files" (A §8.3), which is `real_files`, a model CTE. Both are workable but the spec should
say so: the filename derivation is a lake-level rule whose version is part of
`catalog_version`, and the fingerprint producer evaluates the shared `real_files` SQL over
the pinned snapshot before the model runs, so fingerprints are not one publish behind.

**S7. The recovery-URL link key can legitimately map to several documents.** `DM §8.2`
says the key "resolves to the document that holds that link". At an edition-ambiguous
endpoint two or more listed documents hold the same URL (A §3). The only rule is "refuse
if two keys collide" (A §10.1), which turns an expected data condition into a build
failure, or, if "collide" means only byte-equal keys from different inputs, leaves the
choice unspecified. *Fix:* define the target by a total order (newest `first_captured`,
then `document_id`) and reserve refusal for byte collisions.

**S8. Completion rows have no defined values for non-nullable key columns.** `DM §6.4`:
"a completion row has `link_index = -1` and no `child_url`", but `child_url` is `string`,
not nullable. `DM §6.5` and `§6.6` put `congress`/`system_code` and `chamber`/`event_id`
(non-nullable) in the PK and say only "a body with no committees gets a completion row".
*Fix:* an explicit `is_completion boolean` column on the three tables with the sentinel
values spelled out, or mark the columns nullable and name the sentinels.

**S9. The ID formulas are not specified at the byte level.** `DM §7.3`:
`sha256(logical body key, filename, source_url)`; `A §9.1`: "ID formulas keep their exact
inputs". Separator, encoding, and the encoding of a null body (bodiless source files,
24,980 in today's catalog) or a null URL (331,985 rows, measured) are not given; the plan
defers to golden vectors generated from the Python (`P §6.5` E3). A specification that
says "the formula is whatever the old code does" has not specified it. *Fix:* write the
serialization (field order, separator, UTF-8, null encoding) and keep the golden vectors
as the test.

**S10. "Import run" is used but never defined.** `A §9.4` ("Import day is defined by the
import run's ID"), `DM §5.2` (`run_id` "defines the import run"), `DM §7.4` (`date_kind =
'import_day' if its only rows come from the import run`). The drafts said "the Sept 29
import run"; the specs name no run ID, and the terminology section defines "recovery
import" (`retained_import`) but not this unrelated bulk import. *Fix:* define "import run"
in A §3, and give the model a policy table of import run IDs (plural, since it will happen
again). Also decide whether import-day rows should carry `first_captured` at all: today
they sort in `list` as if captured on Sept 29, 2026, which "Dates say what we know" argues
against.

**S11. `list.meeting_event_ids` drops the chamber.** `DM §8.1` stores `List<int64>` while
`meeting_ref` is `(chamber, event_id)`. The "one ID space" claim in A §9.5 is made for
House and Congress.gov House meetings; nothing is said about Senate IDs colliding with
House IDs, and the draft's supporting measurement (7,243 of 8,956 House IDs overlap) was
dropped. *Fix:* either include chamber in `list` or add an invariant that `event_id` is
unique across chambers in `meeting_records` and let the build refuse otherwise.

**S12. Conformance craft.** (a) `A §2` and `DM §2` refer to "sections marked as
non-normative", but no section is marked; A §5 Scale, A §6 Overview and A §16 Performance
are plainly informative. (b) No conformance classes: a raw writer, a lake producer, a
publisher, a reader and the engine are different products with different requirements, and
"a conforming implementation satisfies every normative requirement" cannot be claimed by
any one of them. (c) Three MUSTs are process steps, not implementation behavior: A §9.2
("MUST be measured as classifiers… before they are fixed"), A §8.8 ("MUST confirm that
compaction keeps…"), A §16.2 ("MUST measure"). Move them to the Note or label them
implementation guidance. (d) Several normative rules depend on lists the spec does not
contain ("and similar" in A §9.2; the page-shape regexes "fixed after sampling" in DM §7.2;
the XML roots for `source_record`; the generic stems; the error words). Either incorporate
the SQL file by reference as a normative registry with a version, or add appendices.

**S13. Scale is mixed without saying so.** `A §10.1`: `list.parquet` "about 2.2 MB",
"Measured: 4.05 MB without an ID", and the ceiling "list reaches 40 MB at about 10 times".
The 4.05 MB and 40 MB are at 1.24M rows; the 2.2 MB is at 0.65M. The draft's caveat
"scaled from measurements at 1.24M" was dropped. Likewise `A §5` "Import day: up to 745k
attempts": 745,456 is capture rows; attempts (lines) were 708,626 (measured), and the spec
elsewhere insists attempts are lines.

**S14. The real-file rule admits every large, error-free web page as a document, and the
labeling rubric does not say whether that is intended.** Under `A §9.2` a committee's
hearing index page with a page-shaped URL, more than 2,048 bytes of text and no error word
is a `document`, and the sample in P §5.3 measures the rules against labels whose
definition of "real page" is not written down. The draft's claim that the rule "removes
listing, landing and error pages" was (rightly) dropped, but the consequence, up to the
86,343 page-like HTML bodies the draft counted entering the explorer as documents, is not
stated. *Fix:* state the intent and write the labeling rubric into S.

### Minor

- **N1.** `A §7.2` "One immutable file per fetch run at `receipts/<family>/<write-date>/<run>.jsonl.gz`". Observed keys carry a sequence suffix (`download-20261004T035944Z-0b9a53dccc9e-000065.jsonl.gz`; 26 files on the import day). Say a run writes one or more numbered files, and that the write-after-bodies rule (A §7.2) is per file.
- **N2.** `A §10.3` tests byte-identity "whatever the batch sizes", while `A §10.1`/`DM §8.1` pin `detail` to 1,024-row write batches. Say explicitly that the export re-batches to the pinned write batch regardless of upstream batch size; that is the mechanism that makes the test pass.
- **N3.** `DM §8.1` gives no type for `list.congress`, `format`, `date_kind`, `saved_kind`, `hidden`; nullability of `document_date`, `first_captured`, `url_state.last_status` is unstated; `captures.media_type` is non-nullable in `DM §6.1` but "string or null" in `DM §5.2`.
- **N4.** `DM §7.6` `links_scanned bool` has no derivation.
- **N5.** `DM §8.1` `occurrences`: one document has 33,479 rows, so "the range named in `detail`" is a ~6 MB read for that page. The reader should page the range; say so in A §11.1.
- **N6.** Facet counts: `DM §10` invariant 17 "facet counts equal counts over `list`" versus invariant 20 "a hidden document has no… facet presence". Define facet counts over non-hidden rows.
- **N7.** `DM §7.1` says nothing about percent-encoding or `+`/`%20` normalization; `A §3` defines the endpoint on raw URLs while `A §9.7` says endpoint matching uses `url_key`. Say endpoints compare on `(url_key(context_url), member_path)`.
- **N8.** `A §10.4.4` "a 412 on a rerun MUST be checked against the expected MD5" needs a HEAD; `A §13.5` forbids HEADs of immutable files. Carve out the 412 path.
- **N9.** Empty inputs: an empty lake or an empty output file is not addressed; the canary (A §10.4.5) reads "the first, last and a random detail" and would fail on an empty release. Say an empty `list` refuses to publish.
- **N10.** `A §7.1` "any HTTP client receives the original bytes" holds only for clients that honor `Content-Encoding`; the sniff parser's ranged read sees compressed bytes for both old and new objects.
- **N11.** `A §7.4` "Writers hold only create permission in practice" is contradicted by `A §14` (R2 tokens cannot be scoped to create-only or to prefixes); keep the §14 wording.
- **N12.** `DM §3` re-defines every term from `A §3` "summarized here"; W3C practice is to define once and reference. Already one summary differs in substance (M2).
- **N13.** `filename_readings` keeps every superseded `catalog_version` forever (append-only, 32 MB each). Fine today; say it is accepted or give a retention rule.
- **N14.** The `fingerprint` of a ZIP is "the digest of its sorted member hashes" (DM §6.2), which `captures` already holds; the parser need not read ZIP bodies at all. Small, but it is the spec's own principle.
- **N15.** Plan: `D` depends on `B16`, but only D5/D6 need it; `A §6.1` A11 measures speed targets on F0, which has 1.24M rows, roughly twice the target `list`; M1.3 "the unmeasured 2 MiB file cap" is unexplained now that ticket IDs are gone; Track A's "done when" cannot include A5's PDF copies before B13.

## Evidence check

Each row says whether the figure was **measured** by me on the snapshot, is **from the
spec** (not independently checkable here), or is an **estimate**.

| Claim | Where | Result | Status |
|---|---|---|---|
| 1,036,256 distinct bodies | DM §5.1 | 1,036,256 distinct `sha256` in `captures.parquet` | measured, exact |
| 2,596,054 receipt lines; 1,041,863 bodiless | DM §6.1 | 2,596,054 distinct `(receipt_key, receipt_line)`; 1,041,865 null-`sha256` rows | measured, exact / ±2 |
| 2,289 receipt files; non-date segments 49 files, 2.2M rows | A §7.2 | 2,289; 48 `undated/` + 1 `mixed-dates/` files, 2,197,261 rows | measured, exact |
| Up to 22,354 bodies per line | DM §5.2 | max 22,354 | measured, exact |
| Largest body 1.19 GB, none above 5 GB | A §5 | 1,187,816,490 bytes; 0 above 5 GB | measured, exact |
| Placeholders 22/18/12 at k = 50/100/200; top body at 87,161 URLs | DM §7.2, A §9.3 | 22/18/12 over distinct `context_url`; 87,161 | measured, exact (A §9.3's "same dozen" is wrong; the body is `text/vtt`, 57 bytes) |
| 1.16M distinct URLs; `url_state` 1,158,426 rows | A §5, DM §7.6 | 1,158,426 distinct `context_url` (old `state.parquet` has 1,298,420 URLs, including never-captured ones) | measured, exact |
| 1,683,430 source files; 331,985 without URL; 32,574 filename ≠ URL segment; 24,202 / 3,637 / 5,229 multi-valued facets | DM §6.3, §7.3 | all exact | measured, exact |
| 141,762 body keys in several old documents; old catalog 1.24M rows; 39,853 multi-body documents | P §5.4, drafts | 141,762; 1,241,157; 39,853 | measured, exact |
| 16,156 rendition groups across 32,547 documents | DM §7.4 | 16,164 groups / 32,329 documents with a same-directory same-stem proxy | measured, approximate |
| 34,331 HTML members at ZIP URLs | A §9.2, DM §7.2 | 34,452 archive-member source files with html format; 34,600 by `.htm(l)` path; 41,931 distinct bodies by server type | measured, approximate; A §9.2's "real web pages" overstates (format, not rule) |
| Import day 745k attempts, 547k new bodies | A §5 | 2026-09-29: 708,626 lines, 745,456 rows, 546,539 first-seen bodies | measured; "attempts" should read rows |
| "Over half of body-bearing attempts hit an existing body" | A §7.1 | 63.9% of body rows reference an already-seen body | measured |
| 579 older gzip bodies over 100 MB | A §11.5 | 505 non-PDF / 588 total above 100 MiB by original size; 528 by stored size | measured, definition-dependent |
| `retrieved_at` null for "about 1.0M older rows" | DM §6.1 | 2,717,129 null rows in the old index; 388,920 bodies with no dated row; the nulls are almost all archive-member (1.38M) and import (242k) rows whose line has a time | measured; plausible only if member rows inherit the line's time on backfill, which the spec implies but does not state. D1 should verify |
| 16,775 / 44,047 file-shaped HTML bodies | DM §7.2 | not reproducible without the sniffed format (79,056 / 79,079 by server media type with my regex guesses) | from the spec |
| 71 exact mirror URLs | A §8.4, DM §6.3 | house-naming 3.2.7 `guide.json` has 7 `source_urls` lists totaling 25 URLs and 66 distinct URL strings overall; README describes the mechanism; no list of 71 | from the spec, not found |
| 491,710 readings rows | DM §6.2 | 491,710 (`record_role` populated on 1,065) | measured, exact |
| `list` 2.2 MB, `detail` 50–70 MB, 90 MB/day | A §10.1 | not checkable here; the `detail` figure rests on a three-key-column proxy the drafts named and the specs dropped | estimate |
| Narrow proxy 3.7 s / 1.75 GB; components 1–2 s | A §5 | not reproducible here | from the spec |

**Could not verify:** hyparquet 1.31.2's `useOffsetIndex` page reads and exposure of
dictionary codes (A §11.1); R2 token scoping and bucket-lock semantics (A §14); Basin
Catalog compaction behavior (the spec defers to M1, correctly); the 148 endpoints / 297
bodies / 1.4 GB fingerprint candidates (needs the real-file rule); the 102,427 import-only
saved files (different grain from anything in the snapshot; by body I count 25,798 bodies
whose rows are all on 2026-09-29 and 56,155 whose only dated rows are); "House and
Congress.gov meeting IDs are one ID space".

## Material content lost or changed relative to the drafts

Revision history, review tables, the 47-decision table and ticket IDs were removed on
purpose and are not counted. The following are losses or changes of substance:

1. **Saved-file total order (changed meaning).** The draft data model (§3.3) ordered the
   saved file by `(format preference, first_fetched desc nulls last, body_sha)` as one
   total order; the spec's two-branch wording loses the tie-break among PDFs (M2).
2. **"Scaled from measurements at 1.24M" (dropped).** Without it, A §10.1's 2.2 MB,
   4.05 MB and 40 MB figures read as a contradiction (S13).
3. **The empirical basis of the real-file rule (dropped).** The draft architecture §6.1
   broke down the 39,853 multi-body documents: 30,303 real files beside an error page
   (25,236 govinfo "retry later"), about 4,900 Senate landing pages, 413 empty playlist
   bodies, 120 API JSON, 236 cut-off downloads, 43 placeholders, 38 other error pages, 6
   hearing-record excerpts, 2 genuine versions. P §6.5 E4's expected parity counts now
   cite nothing in the specs. Belongs back as an informative note.
4. **`url_key` safety evidence (dropped).** Draft DM §3.0: 25,287 of 25,355 scheme/`www.`
   groups (99.7%) served an identical body; `download` separated 916 of 916 Senate groups;
   26 redirect and 620 archive wrappers; 13,930 URLs with a query string. This is the
   evidence that the one merging normalization is safe and the one that strips nothing
   else is right.
5. **Meeting-ID and coverage evidence (dropped).** Draft DM §3.3: 7,243 of 8,956 House
   event IDs also appear on Congress.gov; 116,901 / 163,476 documents carry House /
   Congress.gov meeting URLs; 108,753 carry a govinfo package. A §9.5's "one ID space" now
   stands without support (S11).
6. **Component-size evidence (dropped).** "1.26M components with at most 456 source
   files each" (draft A §6.1) is the only data on merging risk; relevant to M5.
7. **Undated saved files (dropped).** Draft A §6.2: about 756k saved files have a real
   fetch date, 102,427 only the import run's, 368,748 none. The spec keeps 102,427 and
   drops the 368,748, which is 30% of rows sorting as undated in `list`.
8. **The breakdown behind "0.6–0.7M listed" (dropped).** Draft A §2: 454k caption
   snippets, 98k metadata records, 10k playlists, plus API responses, which is where the
   plan's "about 560k leave the list" comes from.
9. **"Engine first is an owner constraint, not a measured conclusion" (dropped with the
   Alternatives table).** The spec presents engine-first as a principle (A §4.5). The
   draft's §13 table also carried the reasons against a replaced-Iceberg model,
   content-addressed shared release files, a second raw copy and a separate release bucket;
   W3C specs do not need an alternatives table, but the one admission above changes how a
   reader weighs §13.
10. **Weakly grounded estimates lost their caveats (dropped).** `detail` 50–70 MB
    ("a proxy of just three key columns measured 49 MB at 650k rows; measured in F0") and
    the filename-reading coverage figures (`congress` 34.7%, `meeting_date` 16.0%, GPO
    14.2%, measure 2–4%, Bioguide ~3%; 146 of 10,000 pairs unreadable). The coverage
    numbers decide how useful `document_date` and the record-key facets are.
11. **Smaller:** "Compaction is a paid Basin feature" (draft A §5.7); "201 bodies cut off
    at 64 MiB" (measured 201 exactly; the spec says only "bodies"); "12,431 of 24,028
    recoveries" (the denominator is gone); the committee/meeting fetches added to the
    publish job and the orchestration diagram are improvements, not losses.

## Three questions for the author

1. For a body that no parser reads (every PDF, Office file, image and archive member, and
   every new body sniffed only by the fetcher), what supplies `record_role`? Does `sniff`
   write a role for older bodies, and is the fetcher's `sniffed_format` meant to imply
   `document` for new ones? (M1)
2. In the publisher-grouping rendition edge, is "different formats" a predicate, and what
   happens when one `<li>` groups several files of the same format, such as a witness's
   testimony and truth-in-testimony form? What precision did you expect, and why is this
   rule not in the hand-labeled sample? (M5)
3. Which run IDs are "the import run", and after the receipts backfill how many capture
   rows and saved files will be undated? The old index has 2.72M undated rows and 388,920
   bodies with no dated row, against the spec's "about 1.0M older rows"; the difference is
   explained only if archive-member rows inherit their line's `retrieved_at`, which the
   spec implies but never states as a derivation. (S10, evidence table)
