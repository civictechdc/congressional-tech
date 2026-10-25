# CS 300 review, round nine: the specification set at 1455011a, read as code

Reviewer role: systems / data-intensive software engineering. Date: 2026-10-25. Mode: audit (the
evolutionary-refactoring lens; nothing was modified). Reviewed at `1455011a` against `9a87e119`:
*Architecture* (**A §n**), *Data Model* (**DM §n**), *Implementation Plan* (**P §n**) and the rewritten
*Bindings* Note (**B §n**). Line numbers below are those of the files at `1455011a` (saved beside this
file as `v5_*.md`). Measurements ran on the read-only 2026-10-19 snapshot and on the four receipt files
fetched publicly in earlier rounds, through the project venv (`prof5_schema.py`, `prof5_checks*.py`,
outputs in `prof5_checks*.out`). No network.

## Verdict

**Ready to build from, with two one-sentence must-fixes, both about raw data or the files it feeds.**
Six of my seven items landed as asked and the seventh is moot. The owner's reversal of the wide
fingerprint scope is right, and the snapshot makes S's deciding count cheap: the re-packaged copies
the narrow guard could miss number at most 15 bodies (1.4 MB) today. The two must-fixes: B0 must cut
local paths only in the fields that hold them, never in every string value; and `complete` must have
one definition, because A §7.1 and DM §5.2 now disagree in a way that would keep B14's re-fetched
files out of the catalog for good. Read as code that five review rounds have patched, the documents
are in good shape: duplication was removed this round (A §7.2, B §2), the main accretion is a
format ladder in `real_files` and a 1:N step inside the scalar `url_key`, and the missing
abstraction is a registry for the source family.

**Grades.** Architecture **A (94)**, unchanged. Plan **A (94)**, +1.

## 1. My seven items

| # | Item | Verdict | Where |
|---|---|---|---|
| 1 | must-fix: lock `bodies/` and `provenance/` now, `receipts/` after B0 | **Landed.** "per prefix ... Creates stay allowed under it"; order, track table, B0 and B1 agree. | A §7.4 (l. 288); P §4 (l. 64, 75), B0, B1 (l. 164–165) |
| 2 | B0 idempotent, batched records, crash path | **Landed.** "for each receipt without a verification record ... a few batched verification files. A rerun skips receipts already recorded, and after a crash it verifies against the backup's original." | P §6.2 B0 (l. 162) |
| 3 | one name per capture row | **Landed**, with the same-body join named. | DM §7.4 (l. 444) |
| 4 | `text_head` in the size note | **Landed** (*est.* 100 MB per HTML and XML parser version; my 85–140 MB agrees). The second sentence added there is an implementation note that duplicates A §13 item 6; see finding 9. | DM §6.2 (l. 230) |
| 5 | registry widening makes publish refuse | **Landed.** | DM §6.2 (l. 229) |
| 6 | occurrence grain versus `entry_index` | **Moot**: `entry_index` is evidence, the endpoint is `(context_url, member_path)` again. Correct; §2.3 below. | A §3 (l. 74); DM §6.1 (l. 173–174), §7.10 |
| 7 | DM §6 caps clause | **Landed**, conditional on M1; keep it until M1 decides, then delete it (finding 10). | DM §6 (l. 153) |

## 2. The edits: correctness and cost

### 2.1 `retry_after` and `next_attempt_at`

**Population.** The snapshot holds 80,414 rows with HTTP 503 and 135 with 429, almost all in the
`documents` family (docs.house.gov), and 79,112 rows the old index resolved as `retry_later`
(measured). Honoring `Retry-After` across runs therefore matters daily, not in theory.

**Rule** (DM §7.7, l. 546): for a retryable outcome, `next_attempt_at = max(last_attempt, retry_after)`;
otherwise `last_attempt + interval`. Correct: due now unless the server asked for a delay, and a
`Retry-After` on a successful fetch is ignored, as it should be. The header stays raw in the receipt
(DM §5.2 allowlist, l. 98) and the deadline is a `timestamptz` resolved against `retrieved_at` at
ingest (DM §6.1, l. 177), so a delta-seconds header and an HTTP-date header both become one
comparable column. Cost: one nullable timestamp per capture row, copied per body of a line like
`retrieved_at`; `url_state` stays one aggregation over distinct `(receipt_key, receipt_line)`, O(attempts).

Three gaps, none large:

- The rule fires only for `retry_later`, `size_limit` and `request_failed`, but no text says which
  statuses map to `retry_later`. If a fetcher records a 429 or 503 as `failed`, the deadline is read
  and ignored. One line in DM §5.2: `retry_later` for 429, 503 and any response carrying `Retry-After`
  (today's 17 `resolution` values collapse to the six outcomes in D1's mapping anyway).
- No ceiling. A server that sends `Retry-After: 31536000` blocks a URL for a year. The S fixture
  "a `Retry-After` beyond the next run" tests the honoring, not the bound; cap the deadline (the
  family's interval, or a registry value) and record the raw header as it is.
- B §3.1 has the fetcher "record ... the `Retry-After` deadline" while DM has the receipt carry the
  header and ingest resolve it. Pick the DM reading: raw header in the receipt, deadline in the lake.

### 2.2 The effective-filename chain

DM §7.4 (l. 435) is now a seven-step `coalesce` over named columns: `recovered_filename` (a provenance
field, DM §5.3), member basename, `Content-Disposition`, a parameter of the filename-parameter
registry, final URL segment, requested URL segment, `retained_name` (DM §6.1, l. 179). Replacing
prose ("the recovered name if provenance says so", "its retained path's last segment") with columns
is the right representation fix: every step is a column of `captures` or one provenance join, so the
producer can compute it from raw and provenance alone (DM §6.3, l. 255).

**Populations** (today's catalog, `filename_origins`, measured): URL path 878,949; `download_state`
494,878; filename inventory 369,226; archive member 171,892; download header 95,664 (E4's "about
95,000": confirmed); retained path 12,891; URL query 201; `recovered_filename` set on 463 rows.
Filenames that are not the URL's last segment: 32,573 (DM §6.3 says 32,574). Absolute local paths
in today's `source_paths`: 9,327 rows, shaped `/Users/.../witness_lists/house_..._pdf`, which is why
the `recovered_filename` step (K23, written by B7) has to outrank `retained_name`.

Two observations:

- **Two evaluators of one chain.** The producer computes the effective filename for its work list
  and the model computes it again for `filenames`; the two must agree byte for byte or the join on
  `(filename, coalesce(source_url, ''))` misses and the row has no reading. The design already hashes
  "the effective-filename rule" into `catalog_version`; make that rule one SQL file both evaluate,
  and say so. The first step is the delicate one: it joins a recovery decision by
  `url_key(original_url)` (DM §7.8), so the producer would depend on the URL registries and
  `url_variants`, which contradicts "the work list depends on no model decision". For an import row
  the decision was made about that row's own `original_url`; match it by the exact string there,
  which is identity semantics like `source_id`, and keep `url_key` for the model's attachment rule.
- **A cause E4 should name.** 460,256 catalog rows have `download_state` as their only name origin
  (measured), and they are the `saved-text` references of §2.6 below: 99.8% of those bodies are the
  same bytes as an exact-bytes capture of the same URL. In the target they collapse onto their twin's
  URL-derived name, so the source-file count falls by roughly that much (1,683,430 today) and so does
  the 1,392,681-pair work list. Not a renaming of 460k files, a disappearance of 460k duplicate rows;
  E4's predicate list should carry it as its own cause.

### 2.3 Endpoints without `entry_index`

Endpoint = `(context_url, member_path)`, with `entry_index` evidence (A §3 l. 74; DM §5.2 l. 112,
§6.1 l. 174; §7.2 l. 374 adds null-safe comparison). Correct: a repacked archive keeps its endpoints,
so an older `report.pdf` and its replacement meet at one endpoint and are editions or re-packaged
copies by text, which is what the ZIP fixture (P §5.3) tests; two members with one name and
different bytes make that endpoint edition-ambiguous and fall out of rendition grouping, which is
the conservative outcome. Measured today: 694,680 member rows at 614,439 member endpoints; **zero**
member endpoints hold two distinct bodies across fetches, and inside one archive fetch the same
path repeats with different bytes in exactly 2 cases (19,932 repeats are byte-identical). The
decision costs nothing today and simplifies every endpoint join.

One wording nit: DM §7.2 (l. 373) defines a context as "an endpoint the page body was good-fetched
at", then restates it as "its member path inside the container", which alone is not an endpoint.
Delete the restatement.

### 2.4 The narrow fingerprint guard and S's count

The guard (DM §6.2 l. 229; §7.5 l. 500; A §8.3 l. 325) is consistent and honest: pages carry a
fingerprint from their own parser, so a re-packaged *page* is recognized anywhere; a re-packaged
*PDF or ZIP* is recognized only at a contested endpoint, and the text says so. Byte-identical
mirrors need no fingerprint: `same_body` carries the exclusion to every copy of an ambiguous body
(110 of today's contested bodies also sit elsewhere, measured).

**S's count can be done in minutes.** For a re-packaged copy to join two editions through rule (b),
it must sit in a same-directory, same-stem format group. Rendition-group members (rule b) whose stem
matches a contested edition's stem and that are not themselves at a contested endpoint number **15
bodies, 1.44 MB, under 9 of 884 contested stems** (measured; the same count under a looser filter was
13 bodies). Fingerprint those, compare with the contested bodies' fingerprints, and the "does the
count matter" question is answered without the 8–45 GB read. Caveat: a copy renamed by its mirror
escapes a stem match, and rule (a) groups (publisher link groups) are not in the snapshot; S's
labeled sample of "widely mirrored real documents" covers that residue.

**The candidate numbers need re-measuring in D2** (which the plan says it does). My approximation of
`real_files` (status 200, bytes > 0, real fetches only, not HTML/VTT/JSON/m3u8, not a placeholder)
gives 860 contested endpoints and 1,822 bodies, not 148 and 297: PDF 313 bodies / 12.65 GB (123 of
them over 50 MB hold 11.86 GB; the rest 0.78 GB), ZIP 1,368 bodies / 75.5 GB, untyped 137 / 0.57 GB.
The spec's "about 1.4 GB" matches the PDFs under 50 MB plus the untyped bodies (1.35 GB), so it
looks like a size-capped count. Two consequences: the PDF read is nearer 13 GB than 1.4 GB (still a
one-time, bounded read); and the 1,368 ZIPs cost nothing only if their fingerprints come from member
hashes in `captures`, which DM §6.2 conditions on `expansion = 'expanded'`, a field older lines do
not carry. The ingest mapping must set it for every older line that has archive members, or the
`fingerprint` parser reads 75 GB of ZIPs once (finding 12).

### 2.5 B0, final procedure

Correct and better than before: the rule has one home (DM §5.2, l. 134), the tool sits outside the
body store with its own credential, verification is batched, reruns skip recorded receipts, a
crash verifies against the backup, the backup stays untouched (the owner's decision; it is private,
so keeping the originals is pure gain), and `receipts/` locks only after the re-scan. Cost O(R):
2,289 GET + conditional PUT + GET, about 3.2 GB, once. The credential-parameter removal joins the
rule; my 195 sample lines carry none, so that part is unverified here (taken).

**The one must-fix.** DM §5.2 (l. 134) and P B0 (l. 160) say "every string value that is an
absolute local filesystem path was cut to its last segment", recognized by "a short prefix list".
In my four files the paths sit in exactly five fields: `record.recovery_evidence.acquisition.body_path`,
`...acquisition.representations[].body_path`, `...acquisition.evidence_file`,
`...recovery_evidence.representation.body_path` and `record.retained_probe_evidence.response_file`
(measured; the only other strings starting with `/` are XPaths in `record.links[].source_xpath`).
Older lines also carry `links[].href` as written, and root-relative hrefs such as `/home/...` are
ordinary on committee sites; an all-fields recognizer with `/home/` or `/var/` in its prefix list
would cut them, the re-read check would pass because the recognizer defines "those fields", and
after the `receipts/` lock nothing can put them back. Cut only the named fields, enumerated from
the 150-file sample; assert in the re-scan that no `url`, `requested_url`, `redirects[]`,
`prior_attempts[]`, `links[]` or `pointer` value changed. One sentence in DM §5.2 and P B0.

### 2.6 The other edits, checked

- **`provider_status`** as its own field (DM §5.2 l. 94, §6.1 l. 178) replaces "recorded apart":
  right representation, and `http_status` keeps one meaning.
- **`complete`** gained an exception in A §7.1 (l. 257: a 206 is incomplete "unless the fetcher
  assembles the whole entity from ranges and its length matches the declared length") while DM §5.2
  (l. 96) still says "false for a 206 response or one with `Content-Range`". B14 re-fetches the
  cut-off files through `download_ranges` (B §3.1, §8), so by DM's words every one of those bodies
  is `complete = false`, fails `good_fetch` (DM §7.3 l. 382) and never becomes a real file: the 62
  documents B14 exists for stay broken. Must-fix 2, finding 1.
- **Archive limits** moved to a registry; a refused expansion is recorded on the container's entry as
  `expansion` (DM §5.2 l. 113, §6.1 l. 175). Good: one owner for the limits, and the ZIP fingerprint
  rule can test one field.
- **`intact`** from `sniff` (DM §6.2 l. 215) and `(format <> 'pdf' or r[sniff].intact)` in `real_files`
  (DM §7.3 l. 413): correct for PDFs, and it catches 112 of today's 201 cut-off bodies; the other 89
  are ZIPs, which nothing excludes unless `complete` is derived for older rows (finding 1, 4).
- **`meeting_refs`** from source records and the fourth source in `meeting_ref` (DM §6.2 l. 216,
  §7.5 l. 513): consistent; see finding 17 on first-of versus union.
- **`remove_date` → `removed_on`** (DM §6.2 l. 220, §7.5 l. 529; A §9.5, §11.6): consistent across
  parser, derivation, column, fold and reader label. One edge: "the earliest `remove_date` on a House
  meeting XML link" reads every historical XML body, so a document removed and later re-added keeps
  the note; derive it from the current meeting record's XML (latest good fetch), as §6.5 already
  does for the record itself.
- **Publisher kinds** registry and `document_kind` fallback (DM §7.1 l. 333, §7.5 l. 526): right.
- **`url_key` gains `repair()`** (DM §7.2 l. 345, 357): a repair "may split one concatenated href into
  several URLs". Finding 5.
- **Dense integer IDs, 32 MB at 4M nodes** (A §9.3 l. 369, §13 item 4): 4M × 8 bytes = 32 MB, correct.
- **Versioned `captures` tables** with a named owner for the drop (A §8.7 l. 347) and a short label
  mapped to the digest (DM §7.1 l. 308): right; a mapping change costs one O(R) re-ingest of 1.08 GB.
- **Invariant 4** now requires a maintained lake and a clean rebuild to give byte-identical releases
  (DM §10 l. 672): the strongest test in the set, and S has the fixture.
- **A §11.1** no longer names hyparquet: a spec should not; the plan (A1) still does, which is where it
  belongs.
- **Bindings rewrite:** binding rules cut from eight to three by pointing at principles 3, 5, 8 and
  A §15 item 7 (fewer homes, finding 2's pattern done right); a dormant-code section with a proposed
  use per item; C4 honestly moved from Bind to Adapt; `url`/`percent-encoding` named at exact versions
  with the WHATWG-versus-RFC 3986 risk stated; line numbers pinned to a commit with names "because
  they outlast line numbers". 36 binding rows for 17 components, the extra rows labeled
  configuration, one-off, migration tool or orchestration. Sound.
- **`fidelity`** (DM §5.2 l. 120, §6.1 l. 170) is carried on every row and read by no rule. Today's
  index has 460,271 `saved-text` rows; 99.8% of their bodies are byte-identical to an exact-bytes
  capture of the same URL, and only 532 URLs hold a saved-text body that differs. Finding 8 proposes
  the use.

## 3. The documents as code: audit findings

Each finding names the location, the evidence, the mechanism of harm or change cost, a bounded
recommendation (keep, reshape or delete) and how to verify it. "Confirmed" means the text or the
snapshot shows it; "hypothesis" means a change-cost argument.

| # | Smell | Location | Evidence and mechanism | Decision |
|---|---|---|---|---|
| 1 | **One rule, two definitions** (`complete`) | A §7.1 l. 257; DM §5.2 l. 96; DM §6.1 `complete` | Confirmed. A allows assembled ranges, DM forbids any 206; `good_fetch` reads the DM column. Also undefined for older rows, which carry no field: the 64 MiB cut-offs (201 bodies: 112 PDF, 89 ZIP; 62 URLs without a complete copy, measured) need a derivation or they pass `good_fetch`. | **Reshape (must-fix):** one definition in DM §5.2 by length: `complete` is true when the stored entity's length equals the declared length (`Content-Length`, or the `Content-Range` total for an assembled entity); the ingest mapping sets it false for older rows of capped runs whose `bytes` is 64 MiB. A §7.1 points to it. Verify: the S fixture "a body assembled from ranges" becomes a real file; the 89 cut-off ZIPs do not. |
| 2 | **One prohibition, three homes** (cookies, credentials, local paths) | A §7.2 l. 271, 274; DM §5.2 l. 132; DM §10 inv. 3 l. 671 | Confirmed. Two normative statements plus an invariant. The next forbidden field (a `Referer` with a session token) needs three edits; this round already edited A and DM in lockstep. | **Reshape:** A §7.2 keeps the principle (public and permanent) and cites DM §5.2 for the list; the invariant stays, it is the test. |
| 3 | **Candidate rule in two normative homes** | A §8.3 l. 325; DM §6.2 l. 229 (plus P S, D2, A §16.1) | Confirmed. Both say who fingerprints what; both changed this round; S may change it again. | **Reshape:** A §8.3 becomes one sentence and a pointer. P and A §16.1 may restate cost, not rule. |
| 4 | **Format ladder in `real_files`** | DM §7.3 l. 412–413 | Confirmed accretion: `(format <> 'html' or not file_shaped)` and now `(format <> 'pdf' or intact)`. The next well-formedness check (a ZIP without its end-of-central-directory, which is exactly the 89 truncated ZIPs) adds a third conjunct and a second home for the check (A §9.2 l. 361 already restates the PDF one). | **Reshape:** make `intact` the sniff parser's per-format well-formedness fact (PDF end marker today, ZIP EOCD next, null when unknown) and write one conjunct, `intact is not false`. The format knowledge then lives where sniffing already lives, and A §9.2 drops the PDF specifics. Hypothesis on the next change; confirmed on the duplication. |
| 5 | **A 1:N step inside a scalar function** | DM §7.2 l. 345, 357–358 | Confirmed. `url_key` is applied to `context_url`, `original_url`, queue keys and recoveries, all scalar joins ("Every link join MUST use `url_key`"); `repair()` inside it may return several URLs, so implementers must choose between a table function and silently taking the first. A concatenated `requested_url` makes no sense to split. | **Reshape:** move `repair` to the link-target step (§7.2 "Link targets": each `href` is repaired, possibly into several hrefs, then resolved, then keyed); `url_key` stays 1:1. |
| 6 | **Missing registry: the source family** | DM §5.2 l. 90 ("21 today"); DM §7.1 recheck intervals l. 329; B §3.1 receipt writer (`source_family.py`) | Confirmed gap: `family` keys receipts, `captures` and the recheck intervals, yet the URL → family mapping is fetcher code, not a registry. A family without an interval leaves `next_attempt_at` undefined (no text covers it). Next publisher: a code change plus 3–6 registry files (scope, pacing, interval, kinds, maybe file shapes and wrappers). 21 families measured. | **Reshape:** a family registry (family → URL patterns, interval, age bands) replaces the recheck-interval registry and seeds `family`; the fetcher reads it from the live profile as it does capture scope. Verify: a fixture adds a publisher with registry rows only. |
| 7 | **A list in the rule beside a registry of the same thing** | DM §7.5 l. 465 (`pdf, xml, htm, html, doc, docx, txt`); DM §7.1 format preference l. 328 | Confirmed. Rule (b)'s document extensions are prose while the saved-file order reads a registry. A new format (`pptx`: 9 rows today, `xlsx`, `rtf`) means a SQL edit and a registry edit. | **Reshape:** rule (b) groups the formats the format-preference registry lists. |
| 8 | **Dormant column** (`fidelity`) | DM §5.2 l. 120; §6.1 l. 170 | Confirmed: no derivation reads it. Today 532 URLs hold a provider-rendered body that differs from the exact bytes at the same URL; both are HTML, both parse, and whichever is first in the saved-file order is the saved file. | **Keep, give it a use:** the saved-file order prefers `exact-bytes` before format preference, and `real_files` may exclude `saved-record`. If no rule will read it, it does not belong in `captures` (it stays in the receipt). |
| 9 | **Implementation note in the schema** | DM §6.2 l. 230, second sentence | Confirmed duplicate of A §13 item 6 ("join on keys first, reduce, then attach the wide column"), written to answer my size note. | **Delete** the sentence; keep the size estimate. |
| 10 | **Spec conditioned on a plan step** | DM §6 l. 153 | Confirmed; I asked for it. Honest while M1 is open, dead text afterwards. | **Keep with a sunset:** delete when M1 lands. |
| 11 | **O(history) per sniff version** | DM §6.2 l. 226; A §8.3 | Confirmed cost: a new sniff version re-reads 1.04M bodies (one ranged GET each; hours). Most sniff changes add a format carved out of `other`/`empty` (396 octet-stream rows and the untyped bodies today) and cannot change a `pdf` or `html` verdict. | **Reshape (optional):** a sniff version declares the prior formats it may reclassify; its work list is the bodies at those formats, or every body when it declares all. Hypothesis on frequency; the saving is measured by the bucket sizes. |
| 12 | **Unstated derivation with a 75 GB consequence** | DM §6.2 l. 229 (`expansion = 'expanded'`); DM §6.1 l. 175 | Confirmed: older lines carry members but no `expansion`; 1,368 contested ZIP bodies (75.5 GB) would be "read from the archive otherwise". | **Add** to the ingest mapping: an older line with `archive_members` maps to `expansion = 'expanded'`. |
| 13 | **Growing link struct** | DM §6.2 l. 220 (9 fields; `remove_date` new) | Hypothesis. Four fields are House meeting-XML attributes; the next one is a parser version and a 5 GB background re-read. The alternative, a `map<string,string>` of the link element's attributes as written, is a native column the model may read (folds may not be), and makes the next attribute a model-only change. | **Keep for now;** the backfill path is designed for exactly this cost. Note the map option in DM §6.2 if a fourth House attribute arrives. |
| 14 | **Principle 8 and the 17-row table** | A §4 l. 160; A §6 l. 217–235; B §3 (36 rows) | Earns its keep: the refusal matrix, the local adapters for tests, the one-implementation rule and the ratchet are concrete; the variation (store, transport, catalog) is real. Cost: 17 contract suites, several of which coincide with DM §10 invariants. | **Keep, trimmed:** say in A §6 that a lake producer's contract suite is the DM invariants for its table; B already labels its non-component rows. |
| 15 | **Bolted elaboration** | DM §7.2 l. 373 | Confirmed: "its member path inside the container" is not an endpoint (§2.3). | **Delete** the elaboration; "an endpoint the page body was good-fetched at" suffices. |
| 16 | **One order in four places** | P §4 l. 64, 75; B0 l. 164; B1 l. 165 | Confirmed repetition inside one Note. | **Keep two** (§4 and B1). |
| 17 | **First-of where the rest of the model keeps every value** | DM §7.5 l. 509–516 | Hypothesis. `meeting_ref` per source file is the first of four sources; facets keep every value, and 1.7% of documents with a meeting have several. A file reused across hearings, linked from two meeting pages, keeps one. | **Question for the owner:** union per source file with a source label, or state why first-of. |
| 18 | **A column with no named receipt field** | DM §6.1 l. 179 (`retained_name`); DM §5.2 recovery-import table | Confirmed: the receipt fields that hold the retained path are not listed; my sample names them (§2.5). | **Add** them to DM §5.2's import table so the ingest mapping has a target. |
| 19 | **S as one gate** | P §5.3 (30 fixture groups, SQL for every derivation, 22 seeded registries, the labeled sample, the count, the raw check); P §4 table (C depends on S) | Hypothesis on schedule risk: M2 needs only "S's draft rules", yet all of S gates C. | **Reshape:** name the subset of S that C needs (the real-file and grouping SQL and their fixtures); the recovery, review and labeling parts land beside C. |

**What was removed this round, correctly:** A §7.2's restated cleanup rule (now a pointer), the
bindings' eight rules (now three plus principles), the "Kept as is" grab-bag row, the hyparquet name
in A §11.1, the `entry_index` identity in four places.

**Next-change costs, named.** A new publisher: one code edit (`family`, finding 6) plus 3–6 registry
files and fixtures; no SQL. A new file format: a sniff version (finding 11), a format-preference row,
a rule (b) edit (finding 7), possibly a file-shape row. A new registry entry: one row with a sample,
a profile change, a publish; cheap, as designed. A new receipt shape: one ingest-mapping version, a
test sample, a new `captures` table from 1.08 GB of receipts; cheap. A new House XML attribute: one
HTML/XML parser version and a 5 GB background re-read (finding 13). Nothing in the set is
superlinear; the repeated-per-item costs are the sniff re-read and the accepted per-run
recomputation of A §16.1.

## 4. Spot-checks

| Claim | Where | Result | Status |
|---|---|---|---|
| 32 MB parent array at 4M nodes with dense integer IDs | A §9.3 | 4M × 8 B = 32 MB | computed |
| 503 and 429 are worth a column | A §7.1; DM §6.1 `retry_after` | 80,414 rows at 503, 135 at 429; 79,112 `retry_later` | **measured** (new) |
| About 95,000 files carry a download-header name | P §6.5 E4 | 95,664 rows with a `content_disposition` origin | **measured** |
| 32,574 filenames are not the URL's last segment | DM §6.3 | 32,573 | measured, consistent |
| 1,683,430 source files; 21 families | DM §7.4; DM §5.2 | 1,683,430; 21 | measured |
| `entry_index` can go | A §3 | 0 member endpoints with two bodies across fetches; 2 same-archive same-path different-bytes cases | **measured** |
| 148 endpoints / 297 bodies / 1.4 GB candidates; D2 "about 300 bodies (1.4 GB)" | DM §6.2; P §6.4 D2 | by my approximation: PDF 313 bodies / 12.65 GB (0.78 GB under 50 MB), untyped 137 / 0.57 GB, ZIP 1,368 / 75.5 GB (no read if `expansion` is derived) | measured, **disagrees on bytes**; D2 re-measures |
| S's count: re-packaged copies in format groups without a shared address | P §5.3 | at most 15 bodies (1.44 MB) by stem match | **measured** (upper bound) |
| 8–45 GB wide read | P §5.3 | 8.3 GB rule-(b) members measured last round (19,165 PDF and 19,020 XML bodies this round) | measured floor, estimated ceiling |
| 62 to 64 cut-off URLs | P §6.2 B14 | 62 under both completeness definitions; 207 URLs ever cut; 112 PDF and 89 ZIP bodies | measured |
| 86 published assistant reviews | P B8; B §3.1 | `document-review-identities.json` at 1455011a: `rows` has 86 entries | measured |
| 22 registries, 17 components, 36 binding rows, 30 fixture groups | DM §7.1; A §6; B §3; P §5.3 | counted | counted |
| About 100 MB `text_head` per parser version | DM §6.2 | my 85–140 MB (2 KB × 214k, compressed) | estimated, consistent |
| 2,289 receipts, 1.08 GB; 5,587 recovery lines; 1,392,681 pairs; 277,642 contexts | P D1, B15; DM §6.3, §7.2 | from earlier rounds | measured earlier |
| Nine raw write entry points; 13 review forms; line counts in B §6 | B §2, §3.1, §6 | not checked (code) | taken |
| Credential parameters in recorded URLs; `Retry-After` headers | DM §5.2; P B0 | 0 of each in my 195 sample lines | taken |
| B0 path fields | DM §5.2; P B0 | five field paths hold every local path in my sample | measured |

## 5. Remaining items

**Must-fix (one sentence each)**

1. **B0 cuts paths only in the named fields** (DM §5.2 l. 134; P B0 l. 160): list the fields from the
   150-file sample, never touch URL, link, pointer or path-of-record fields, and have the re-scan
   assert it. Raw evidence is at stake and the lock makes the cut permanent.
2. **One definition of `complete`, by length** (DM §5.2 l. 96; A §7.1 l. 257; the ingest mapping for
   older 64 MiB rows). Otherwise B14's assembled bodies never become real files and 89 truncated
   ZIPs can.

**Nice-to-have, in order**

3. Ingest sets `expansion = 'expanded'` for older lines with members (finding 12; 75 GB).
4. `retry_later` for 429, 503 and any `Retry-After`; a ceiling on the deadline; raw header in the
   receipt, deadline in the lake (§2.1).
5. One SQL for the effective filename, evaluated by producer and model; exact-URL match for the
   `recovered_filename` step (§2.2).
6. `repair` out of `url_key` (finding 5); `intact` as sniff's per-format fact with one conjunct
   (finding 4); rule (b) reads the format-preference registry (finding 7).
7. A family registry (finding 6).
8. `fidelity` used in the saved-file order or dropped from `captures` (finding 8).
9. A §7.2 and A §8.3 point to DM instead of restating (findings 2, 3); DM §6.2's implementation
   sentence and §7.2's context elaboration deleted (findings 9, 15); `retained_name`'s receipt fields
   listed (finding 18).
10. E4 names the `download_state`-only collapse (about 460k rows) as a cause (§2.2); `removed_on`
    from the current meeting record (§2.6); S split into the part C needs and the rest (finding 19).

## 6. Grades and verdict

**Architecture: A (94), unchanged.** The edits are correct and several improve the model's
representation: `provider_status`, `recovered_filename` and `retained_name` as columns,
`entry_index` as evidence, `intact`, `expansion`, dense IDs, an implementation-neutral reader
section, and the narrow guard stated with its gap. Against that, this round introduced one normative
contradiction (`complete`) and one unstated derivation with a 75 GB price (`expansion` on older
lines), and `real_files` and `url_key` each took a patch where the model should have moved. Net zero.

**Plan: A (94), +1.** The lock order is right, B0 is specified like a raw operation should be, the
bindings Note now reads like an inventory rather than a manifesto, and S carries the one measurement
that decides the fingerprint scope. It does not reach 95 because B0's recognizer rule is wider than
its evidence, and because S has become a single gate for everything in track C.

**Verdict: ready to build from.** Make the two one-sentence fixes before B0's ticket and before
B14's; the rest can land as the sections are touched.
