# CS 300 Re-review: Congressional Document Archive specifications after fixes

Re-reviewed 2026-10-24 against commit `39ae52d2` in `/Users/mikewolfd/Work/wt/ct-ticket-audit`:
`docs/engine-first-architecture.md` (A), `docs/engine-first-data-model.md` (DM),
`docs/plans/simplification-plan-20261024.md` (P). The first review is
`docs/reviews/2026-10-24-design-review/cs300-spec-review.md`; its finding IDs (M1–M5,
S1–S14, N1–N15) are used below.

Method. I read the three revised documents in full, diffed each against its pre-fix copy
(`specrr_arch.diff`, `specrr_dm.diff`, `specrr_plan.diff` in this folder), re-measured every
number the fixes touched or restored on the read-only 2026-10-19 snapshot with DuckDB through
the project venv (`specrr_numbers*.py`, `specrr_roles.py`, outputs beside them), and read
`packages/congress_api/src/congress_api/retention/index/bipartite.py` and `schemas.py` to
check the byte-level ID serialization the data model now claims. Nothing outside this scratch
folder was written.

## Verdict

The fixes are real, not cosmetic. All five original must-fix items are closed with the fix I
said I would accept, and 32 of 34 findings are fixed outright; the two "partly" items are
small. The specifications are now buildable with one more editing pass.

That pass is needed because the two owner decisions folded in during the fix (a `listing`
record role; recovery attachment) each left a seam. The listing rule is now stated two
different ways in two layers: the architecture defines it as a ratio ("visible text mostly
links") and the data model as absolute thresholds, and the data model has the HTML *parser*
apply a *model registry*, which contradicts the registry rule it introduced three sections
earlier. That is the one new must-fix. Behind it are a few should-fix items, most of them
consequences of the same two decisions: a parse-failure hole in the real-file rule, a
completion-row granularity mismatch, a lake work list that now depends on a model decision,
and a listed-document estimate that ignores the exclusion the owner just added.

## Regrade

| Area | Before | Now | Why |
|---|---|---|---|
| Correctness and completeness | B− (80) | B+ (87) | M1–M5 closed as asked; one new contradiction (listing rule) and a parse-failure hole in `real_files` |
| Efficiency (Big O) | A− (90) | A− (92) | Binary `saved_body`, occurrence paging, ZIP fingerprints from `captures`; identity still re-runs the model during backfills |
| Determinism and failure behavior | B+ (87) | A− (90) | Total orders restored, pointer carries last-good, versions stay complete, empty `list` refused; `alternates` pick rule missing |
| Data model quality | B (84) | B+ (87) | Types, nullability, sentinels, binary keys fixed; completion rows still contradict required columns |
| Specification craft | B (83) | B+ (88) | Conformance classes, non-normative marks, registries, one terminology section; residual nits (three bullets under "two checks", MUST in a non-normative section) |
| Plan | B+ (88) | A− (90) | Dependencies narrowed, rubric written, M1.3 explained, F0 scale caveat; E1's registry list is incomplete |

**Overall, the two specifications: B+ (88), up from B (84). The plan: A− (90), up from B+ (88).**

**Count: 32 fixed, 2 partly (S8, N4), 0 not fixed, 0 no longer apply.**

## Verdicts per finding

Each verdict names where the fix lives and whether it is the fix I said I would accept.

### Must fix (original)

| ID | Finding | Verdict | Location and note |
|---|---|---|---|
| M1 | `record_role` undefined for unparsed formats | **Fixed** | DM §7.2 `record_role := coalesce(r.record_role, role_from_format(format))`, `role_from_format` written out; A §3, A §8.3, DM §6.2 agree. Exactly the requested fix. See NP2 for a hole the fallback leaves open for parsed formats. |
| M2 | Saved file not unique with several PDFs | **Fixed** | One total order `(format preference, first_fetched desc nulls last, body_sha)` in A §3, A §9.4, DM §7.4 and invariant 10. |
| M3 | Snapshot pinning contradicted orchestration | **Fixed** | A §10.4.1 and DM §8.4: lake producers first, `fingerprint` last, then pin, identity, early skip, model; A §12 diagram and P §6.6 F1 updated to match. |
| M4 | Membership defined at two grains | **Fixed** | DM §7.3 `is_real_file` = "at least one capture row in `real_files`"; DM §7.4 and A §9.3 `same_body` say "at least one"; P §6.5 E1 restates it. |
| M5 | Rendition edge lacked its predicate | **Fixed** | A §9.3 (3) and DM §7.4: different formats, one file per format, otherwise no edge; invariant 21; rendition rule added to the labeled sample (P §5.3, A §15.8); largest components reported by edge kind (A §9.3, DM §7.4). |

### Should fix (original)

| ID | Finding | Verdict | Location and note |
|---|---|---|---|
| S1 | `saved_key` hex against "binary everywhere" | **Fixed** | DM §7.4 and §8.1: `saved_body fsb(32)` + `saved_suffix dict`; recoveries and alternates carry `body fsb(32)` + `suffix`; `evidence_sha256 fsb(32)`; A §10.1 detail now 30–50 MB; DM §9 key table updated. |
| S2 | Placeholder set contradiction; "error page" mislabel | **Fixed** | A §3, A §9.3, DM §7.2: distinct `context_url`, any mode, 18/22/12, 57-byte caption file. Reproduces exactly. The companion "174,323" does not (NP6). |
| S3 | Identity digest vs high-water mark | **Fixed** | A §10.4.1, DM §8.1, DM §6.4: digest of the sorted set of ingested receipt keys; the text says why. |
| S4 | Last-good release recorded nowhere | **Fixed** | A §3 "pointer", A §10.4.6 (`release_id`, `previous_release_id`, `schema_version`), A §10.4.7 retention reads both; DM §8.1 pointer row; invariant 17. |
| S5 | Versions go incomplete during a backfill | **Fixed** | A §8.3, DM §6.2, invariant 4 (one term, "the version the model reads"); P §6.4 D2. |
| S6 | Lake producers depend on model logic | **Fixed** | A §8.4 and DM §6.3: effective-filename rule is lake-level and part of `catalog_version`; A §8.3 and DM §6.2: `fingerprint` evaluates `real_files` before the pin. A new dependency appeared elsewhere (NP4). |
| S7 | Recovery URL key ambiguous at edition-ambiguous endpoints | **Fixed** | Owner's rule, not my total order, but deterministic and refusal-free: A §9.6, A §9.3 Listing, DM §7.7 Attachment, DM §8.2, invariant 16. Accepted. |
| S8 | Completion rows undefined for non-nullable keys | **Partly** | DM §6: `is_completion` column and PK sentinels for `committee_records` and `meeting_records`; `child_url` nullable. Missing: a `receipt_line` sentinel for `page_links`, and "its other columns are null" contradicts columns still declared required (NP3). |
| S9 | ID formulas not specified byte for byte | **Fixed, verified** | DM §3 "compact JSON", DM §7.3 `[logical body key, filename, source_url]`, DM §7.4 `["bodies", …]` / `["sources", …]`. Matches `schemas.py:377` (`json.dumps(v, ensure_ascii=False, separators=(",", ":"), allow_nan=False)`) and `bipartite.py:165–205` (`sorted(set(...))`, hex source IDs). One precision gap (NP11). |
| S10 | "Import run" undefined; import-day dates sorted as real dates | **Fixed** | A §3 "import run", import-run registry (DM §2, §5.2); `first_fetched` excludes import runs, `in_archive_since` added (DM §7.3–7.4); import-only files sort with undated ones (A §9.4, DM §8.1, invariant 14). |
| S11 | `meeting_event_ids` dropped the chamber | **Fixed** | `meeting_keys` = `chamber:event_id` (DM §7.4, §8.1, invariant 13; A §9.5). |
| S12 | Conformance craft | **Fixed** | Five classes (A §2, DM §2); sections marked non-normative (A §1, §5, §6, §16; DM §1, §9); process MUSTs removed (A §8.8, §9.2, §16.2); registries incorporated by reference (DM §2). Residue in NP8, NP14, NP15. |
| S13 | Mixed scales; "745k attempts" | **Fixed** | A §10.1 "scaled from measurements on today's 1.24M catalog rows", "Measured at today's 1.24M rows", ceiling in catalog rows; A §5 "708,626 receipt lines (745,456 capture rows)". Both reproduce. |
| S14 | Large error-free web pages all become documents; no rubric | **Fixed** (owner decision) | `listing` role: A §3, §8.3, §9.2; DM §6.2 (`link_count`, `link_text_bytes`), §7.2; invariant 22; rubric in P §5.3. The decision is sound; its specification is where the one new must-fix sits (NP1). |

### Minor (original)

| ID | Finding | Verdict | Location and note |
|---|---|---|---|
| N1 | "One file per run" vs numbered files | **Fixed** | A §3, A §7.2, DM §5.2 `<run>-<seq>.jsonl.gz`; the A §6 diagram (non-normative) still shows `<run>.jsonl.gz`. |
| N2 | Batch size as a determinism input | **Fixed** | A §10.3 "re-batches its input to the pinned write batch". |
| N3 | Missing types and nullability | **Fixed** | DM §8.1 `list` columns typed; `url_state` nullability; `captures.media_type` nullable; DM §7.4 columns annotated. |
| N4 | `links_scanned` undefined | **Partly** | DM §7.6 defines it per receipt *line*, but completion rows are written per receipt *key* (DM §6.4 work list), so a link-less line in a receipt that has links never satisfies it (NP3). |
| N5 | Unbounded occurrence range read | **Fixed** | A §11.1 "read a page at a time". |
| N6 | Facet counts vs hidden rows | **Fixed** | Invariant 17 "non-hidden rows of `list`"; A §10.2 still says "unfiltered facet counts", which now reads oddly but is not wrong. |
| N7 | Percent-encoding; endpoint on `url_key` | **Fixed** | DM §7.1 decodes unreserved escapes; endpoint matching compares `(url_key(context_url), member_path)`. |
| N8 | 412 check needs a HEAD | **Fixed** | A §10.4.4 and A §13.5 carve out the one HEAD. |
| N9 | Empty inputs | **Fixed** | A §10.4.3, DM §8.4, invariant 22: an empty `list` is never published. |
| N10 | `Content-Encoding` wording | **Fixed** | A §7.1. |
| N11 | "Create permission in practice" | **Fixed** | A §7.4 defers to §14. |
| N12 | Terminology defined twice | **Fixed** | DM §3 defines only its four additions. |
| N13 | Superseded catalog versions kept forever | **Fixed** | DM §6.3 "kept; that cost is accepted". |
| N14 | ZIP fingerprint needs no ZIP read | **Fixed** | A §8.3, DM §6.2. |
| N15 | Plan nits (D on B16, F0 scale, M1.3, A5/B13) | **Fixed** | P §4 table, §5.1 M1.3 (now explained: 2 MiB file and 2,048-row caps), §5.4, §6.1 A11 and "Done when", A §11.2. |

## New problems the fixes introduced

### Must fix

**NP1. The listing rule is defined two ways and placed in the wrong layer.**
A §9.2 (7): "A page whose visible text is *mostly* links to other files … is a listing
page": a ratio. DM §7.2: "link-dominant HTML (`link_text_bytes` and `link_count` *above the
listing-page thresholds*, registry) → `listing`": absolute thresholds. A long transcript
with two hundred footnote links passes the second and fails the first. Worse, DM §7.2 has
`r.record_role` "written by the HTML, XML and JSON parsers", with `listing` decided by a
*registry*; DM §2 says "a registry change is a model version change" and DM §7.1 that
registries are "applied in the model rather than stored, so changing them rewrites nothing
in the lake". As written, retuning the listing threshold either forces a new HTML parser
version and a re-parse of every HTML body, or leaves stale `listing` roles in old readings
that disagree with the registry. The data model already added `link_count` and
`link_text_bytes` to the typed core as "the listing-page signals", which is the right design.
*Fix I would accept:* the parser writes signals only (`text_bytes`, `link_count`,
`link_text_bytes`); the model derives `listing` the way it derives `error_signs`, from one
predicate stated identically in A §9.2 and DM §7.2 (a link-text ratio over `text_bytes` plus
a minimum link count, both in the registry); `r.record_role` never carries `listing`.
Invariants 5 and 22 then stay as they are.

### Should fix

**NP2. The role fallback opens a parse-failure hole for parsed formats.** DM §7.2
`role_from_format` maps "every other format → document", which includes `html`, `xml` and
`json` when a reading row exists but carries no role: a parser row with `status = error` or
`size_limit` (today's readings hold 6,814 such rows plus 107,184 `unclassified`). An XML
metadata record the parser failed on then has `record_role = document` and passes
`real_files`; an HTML one is excluded only by three-valued-logic accident
(`not error_signs(r)` is null). *Fix:* `role_from_format` returns null for formats a parser
reads, or `real_files` requires `r.status = 'completed'` for them. Invariant 5 should say
"from a completed reading".

**NP3. Completion-row granularity contradicts `links_scanned` and the required columns.**
`page_links` completion rows are per receipt key (DM §6.4 work list: "receipt keys not yet
in `page_links`"), but `links_scanned` (DM §7.6) asks for a row "for the latest attempt's
receipt line"; a line with no links inside a receipt that has links never gets one. The
`page_links` completion row has a `link_index` sentinel but no `receipt_line` sentinel, so
invariant 1 (PK unique) is undefined for it. DM §6 says a completion row's "other columns
are null" while `parent_url`, `parent_sha`, `basis`, `tag`, `source_xpath`, `text`
(§6.4), `chamber`, `name` (§6.5) and `congress`, `title`, `meeting_date`, `meeting_type`,
`committee_keys` (§6.6) are still declared required. *Fix:* `receipt_line = -1`; declare
every non-PK column nullable on the three tables (or say completion rows relax nullability
and list the sentinels); define `links_scanned` by receipt key, or write completion rows per
line.

**NP4. The `filename_readings` work list now depends on a model decision.** DM §7.3
adds "one bodiless row per recovery that needs a document of its own (§7.7)", and A §8.4 /
DM §6.3 define the producer's work list as "every source file (§7.3)". Whether a recovery
"needs a document of its own" is the attachment rule's output, which needs listed
documents, which the lake producer cannot compute. *Fix:* the producer includes the
`(filename, url)` pair of every recovery's original link unconditionally; the superset costs
a few thousand pairs.

**NP5. The listed-document estimate ignores the exclusion the owner just added.** A §5
and DM §7.4 derive 0.6–0.7M as 1.24M − 454k − 98k − 10k − 1k = 678k, "before untyped bodies
are sniffed and renditions merge". Listing pages now leave too (P §6.5 E4 says so, with no
count), and the old catalog has 203,336 HTML-typed rows (measured), so the 0.6M floor is not
safe. *Fix:* add the listing exclusion to both derivations and bound it from the S sample;
until then say "0.5–0.7M".

**NP6. "174,323 source files" (A §9.3) does not reproduce.** The 57-byte caption body sits
at 87,161 distinct `context_url`s; those URLs hold exactly 87,161 source files and no other
body (measured). Under the specified edge set a placeholder glues 87,161 source files, not
174,323 (which is 2 × 87,161 + 1, an artifact of the old URL-node graph). *Fix:* say 87,161.

**NP7. `alternates` "one per format" has no pick rule** (DM §7.4, A §9.4). A document with
re-packaged XML at one endpoint has two XML real files; which one is the alternate is
unspecified, so the export is not deterministic there. *Fix:* "the first real file of each
other format in the saved-file order".

### Minor

- **NP8.** A §9.2 (7) says "two checks decide … applied to the locator" and lists three
  bullets; the third (listing) is applied to the reading, not the locator.
- **NP9.** The restored "368,748 have no capture date" (DM §7.4) reproduces exactly on the
  old catalog and stays at 368,572 after member rows inherit their line's time (DM §5.2,
  §6.1), because the undated receipts' lines carry no time in the old index: 2,714,472 of
  3,909,134 capture rows and 388,817 of 1,036,256 bodies stay undated. Say that about 30% of
  listed documents will have `date_kind = 'unknown'` and sort last within their filename, and
  have D1 check whether the undated receipts' JSON carries times the old index dropped.
- **NP10.** Two `schema_version`s now exist, on the pointer (A §10.4.6, DM §8.1) and on the
  release manifest (A §11.4); say which one the reader checks and whether they must agree.
  `previous_release_id` is null at bootstrap, so "at least two releases exist at all times"
  (A §10.4.7) is false for the first flip.
- **NP11.** DM §3 "compact JSON" should state the escaping that remains: `"`, `\` and
  U+0000–U+001F are escaped, `/` and non-ASCII are not. That is what
  `json.dumps(ensure_ascii=False)` produces and what a `serde_json` compact writer produces;
  without the sentence an implementer may escape `/` or `\u007f`.
- **NP12.** "The export MUST refuse if two keys from different inputs are byte-equal"
  (A §10.1, DM §8.2) would refuse two recoveries for the same original link, which share one
  URL key by design. Say "one key per distinct original link; refuse only byte-equal keys
  from different link keys' inputs".
- **NP13.** A §6 diagram still shows `receipts/<family>/<write-date>/<run>.jsonl.gz`.
- **NP14.** A §5 is now non-normative yet contains "MUST NOT be repeated".
- **NP15.** Normative text leans on the informative Note: A §8.8 ("[[IMPLEMENTATION-PLAN]]
  confirms it") and A §9.2 ("measured … [[IMPLEMENTATION-PLAN]] §5"). Descriptive, so
  acceptable, but an editor would phrase both without the dependency.
- **NP16.** Registry naming drifts: DM §2 lists eleven registries; P §6.5 E1 lists seven
  and, with DM §7.6, calls the recheck intervals a "policy table". One term.
- **NP17.** DM §7.3 "plus one bodiless row per URL that never yielded a body, plus one
  bodiless row per recovery…" can describe the same `(null, filename, url)` triple twice;
  say "or, if not already present".
- **NP18.** The input identity counts rows in every `readings` partition (A §10.4.1), so a
  background backfill of a version the model does not read changes the identity daily and
  runs the model for nothing before the release-ID check stops it. Count only the versions
  the model reads.
- **NP19.** `in_archive_since` is "the earliest import run's date" (DM §7.3) but nothing says
  where that date comes from; the import-run registry should carry it.
- **NP20.** P §5.3's rubric sentence "two files are one document only when they are the
  same text in different formats" contradicts `same_body` and `same_text` (same text, same
  format) if read as a definition; scope it to the rendition rule.
- **NP21.** Invariant 22 bundles two unrelated assertions (non-empty `list`; listing pages
  never real). Split them.
- **NP22.** A §8.3 lists "archive members" among formats that take their role from the
  sniff; an HTML member is parsed by the HTML parser like any HTML body. Drop the words.

## Numbers re-checked against the snapshot

| Claim | Where | Result | Status |
|---|---|---|---|
| Import day 708,626 lines, 745,456 rows, 547k new bodies | A §5 | 708,626 / 745,456 / 546,539 | measured, exact |
| Placeholders 18 (22 at 50, 12 at 200); 87,161 URLs; 57-byte `text/vtt` body | A §9.3, DM §7.2 | 18/22/12; 87,161; 57 bytes, `text/vtt` | measured, exact |
| 174,323 source files glued | A §9.3 | 87,161 source files at those URLs, one body | does not reproduce (NP6) |
| 201 bodies cut off at 64 MiB | A §7.1 | 201 distinct bodies | measured, exact |
| 454k caption snippets | A §5, DM §7.4 | 453,751 `text/vtt` rows in `documents.parquet` | measured |
| 98k metadata records, 10k playlists, 1k API responses | A §5, DM §7.4 | 147,779 XML-typed, 2,591 `x-mpegURL`, 560 JSON-typed rows; the spec's criteria are roles, not media types | from the spec, not reproducible here |
| 102,427 saved files dated only by the import run | DM §7.4 | 102,427 | measured, exact |
| 368,748 saved files with no capture date | DM §7.4 | 368,748 now; 368,572 after member rows inherit their line's time | measured, exact (NP9) |
| `retrieved_at` "null only when the line has none" | DM §6.1 | 2,717,129 null rows now; 2,714,472 after inheriting | consistent; the lines are undated |
| 25 mirror URLs in 7 lists, house-naming 3.2.7 | DM §6.3 | 25 URLs, 7 `source_urls` lists in `guide.json` | measured (my own figure, restored) |
| Compact JSON; `["bodies", sorted distinct keys]` / `["sources", sorted distinct hex]`; null for missing | DM §3, §7.3–7.4 | `schemas.py:377`, `bipartite.py:165–205` | verified against code |
| 1.26M components, largest 456 | A §9.3, DM §7.4 | old-model measurement | from the spec |
| 203,336 HTML-typed catalog rows (bounds the listing exclusion) | new | measured | measured |
| `detail` 30–50 MB | A §10.1, DM §8.1 | estimate, "measured in F0" | estimate |
| 2 MiB file / 2,048-row caps, ~70 files for 150 MB | P §5.1 | arithmetic consistent; engine not inspected | from the plan |

## What remains for the author

1. Decide where `listing` is computed (NP1) and write one predicate in both documents.
2. Close the parse-failure hole (NP2) and the completion-row contradictions (NP3), which are
   two lines each.
3. Re-derive the listed-document estimate with the listing exclusion (NP5), ideally from the
   S sample, and correct 174,323 (NP6).
