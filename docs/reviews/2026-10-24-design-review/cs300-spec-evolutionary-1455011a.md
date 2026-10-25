# CS 300 Review, round 6: Congressional Document Archive specifications (commit 1455011a)

Reviewed 2026-10-25 against `1455011a` ("address the final review round") in
`/Users/mikewolfd/Work/wt/ct-ticket-audit`: `docs/engine-first-architecture.md` (A, 603
lines), `docs/engine-first-data-model.md` (DM, 725 lines),
`docs/plans/simplification-plan-20261024.md` (P, 290 lines) and the rewritten
`docs/plans/bindings-20261025.md` (B, 200 lines). My previous round is the final review of
`9a87e119` (finding IDs G1–G19, R13, R15).

Method. The evolutionary-refactoring skill was loaded in Audit mode, so this round reads the
four documents as code that five review rounds have patched: trace the flow from a receipt
line through `captures`, the readings, `real_files`, source files, edges and documents to the
release; name the owner of each rule; and treat every smell as a hypothesis tied to a
concrete failure or change cost. I read all four documents in full, kept the diff from
`9a87e119` beside me (`spec5_docs.diff`, 913 lines), re-measured the numbers the edits touched
on the read-only 2026-10-19 snapshot through the project venv (`spec5_numbers.py`, output
`spec5_numbers.out`), and read the code the bindings cite for the new `intact` rule and the
2xx defect, read-only. Nothing outside this scratch folder was written.

## Verdict

**Ready to build from, with one must-fix that is one field and one `coalesce`.** Nineteen of
the twenty-one items from the last round are fixed, and I accept the two that were not: G1 was
fixed differently and better (a name per capture row, joined by the same-body edge, removes the
circularity with no tie-break rule), G11 is moot once no recorded URL carries a credential
(with one small residual in the queue), and G17 is superseded by an evidence-first owner
decision.

The edits introduced one regression. The broken-PDF decision landed as `real_files … and
(format <> 'pdf' or r[sniff].intact)`, but `intact` is written only by the `sniff` parser, and
the `sniff` parser reads only bodies the fetcher did not sniff. Every PDF captured after the
switch therefore has `intact = null` and is never a real file. Today's code already computes
the check on the spooled body (`capture_inspection.py:89-99`), so the fix is to record it in
the capture entry and coalesce, exactly as `format` already does.

Under the refactoring lens the documents are in good shape for their age: every rule has one
normative home, the registries have one owner each, and the next publisher costs registry
edits only. The erosion is where five rounds of patches would put it: body classification is
split between `record_role` (the dispatcher) and two format-keyed conjuncts bolted onto
`real_files`; three joins (the queue, `linked_from`, recovery attachment) each define "the
URLs a copy is known by" differently; `url_key` has absorbed a `repair` stage that can return
several values, so it is no longer a function; and the 206 rule has two homes that already
differ. Each is a bounded reshape to do in S, when the SQL is first written.

## Regrade

| Area | Last round | Now | Why |
|---|---|---|---|
| Correctness and completeness | A− (92) | A− (91) | G1–G10, G12–G16, G18–G19 closed; one regression (`intact` for new PDFs); feeds as documents (6 bodies today) |
| Efficiency (Big O) | A (94) | A (93) | Narrow fingerprint candidates keep the pass at 1.4 GB; the sniff pass is no longer "one ranged read" for PDFs and its reader fallback is unbounded in the text |
| Determinism and failure behavior | A (93) | A (94) | Per-row names, byte-identical rebuild invariant, `retry_after` in the schedule, verified cleanup with an untouched backup |
| Data model quality | A− (92) | A− (92) | Six new facts landed as typed columns; the 206 rule now has two homes; `repair` breaks `url_key`'s function contract |
| Specification craft (refactoring lens) | A (94) | A− (91) | One home per rule holds; but `real_files` accretes per-format conjuncts, the registry table mixes three owners, and A §9's paraphrase needs editing every round |
| Plan and bindings | A (94) | A (94) | Lock on `bodies/` first, cleanup tool outside the body store, dormant code given uses, fixtures for every new rule |

**Overall, the two specifications: A− (92), down from A (93). The plan with its bindings Note: A (94).**

**Counts over the 21 items (G1–G19, R13, R15): 19 fixed, 0 partly, 2 not done and accepted (G11 moot, G17 superseded).**

## Verdicts per item

| ID | Finding | Verdict | Location and note |
|---|---|---|---|
| G1 | Effective-filename rule circular about which fetch names a file | **Fixed differently; accepted** | DM §7.4 "One name per capture row … each name is its own source file, and they join through the same-body edge." The name is a function of the row, so the source-file grain is well-defined without a tie-break; the evidence stays in the receipt; `occurrences` shows each name. P §6.5 E4 states the parity cause. One consequence to know: the `list` name of a body offered two names is the saved file's, chosen by the saved-file order, so it is stable but arbitrary between the two. |
| G2 | Cleanup rule vs invariant 3 on credential parameters | **Fixed** | DM §5.2 "credential parameters were removed from recorded URLs"; P B0 rule; DM §5.3 verification counts "cookies, paths and credential parameters removed". |
| G3 | Cleanup named neither fields nor recognizer | **Fixed** | DM §5.2 names `Set-Cookie`, `Cookie`, `Authorization`; "every string value that is an absolute local filesystem path"; P B0 "a short prefix list with samples, checked against the 150-file sample"; member paths, pointers and URLs untouched. |
| G4 | `entry_index` made member link targets unmatchable | **Fixed** | A §3 and DM §6.1: `entry_index` is evidence; the endpoint is `(context_url, member_path)` again; DM §7.2 null-safe comparison; "A target path that several members of one archive share matches each of them"; duplicate names form an edition-ambiguous endpoint by DM §7.5's definition. |
| G5 | "The entry's outcome" named no field | **Fixed** | DM §5.2 and §6.1 `expansion`; A §7.2 "recorded on the container's entry". |
| G6 | "The recovered name" had no source | **Fixed** | DM §5.3 `recovered_filename`; §7.4 first precedence item. |
| G7 | Provider status "recorded apart" | **Fixed** | DM §5.2 and §6.1 `provider_status`. |
| G8 | Import rows lacked `recovered_url`, `evidence_sha256` | **Fixed** | DM §6.1 import columns. |
| G9 | Capture-scope version for fetchers | **Fixed** | DM §7.1 "Fetchers use the capture-scope version of the live release's profile." |
| G10 | Stripped credentials made URLs unfetchable | **Fixed** | A §7.2 "the fetcher adds it from configuration at fetch time". |
| G11 | `url_key` could strip the credential registry | **Not done; accepted** | After B0 and B2 no recorded URL carries one, so the step would be dead. Residual (minor N6): a queue row's `requested_url` comes from a page link, not a receipt, so a page that links to a URL with a key can put that key into the published `url_state`. |
| G12 | `text_head` size unstated | **Fixed** | DM §6.2 "*est.* 100 MB per HTML and XML parser version … reduces readings to the narrow columns … before any join". |
| G13 | A §16.1 repeated-work wording | **Fixed** | With candidates back to contested endpoints, "evaluates the real-file rule once more" is again exact. |
| G14 | `recoveries.parquet` lacked the byte limit | **Fixed** | DM §8.1. |
| G15 | Normative citation of the plan | **Fixed** | A §7.2 cites DM §5.2. |
| G16 | B0 used the body store before the refusal matrix | **Fixed** | P B0 "a one-off rewriter outside the body store, with its own credential"; B §3.1 "Receipt rewriter". |
| G17 | Fingerprint estimate conservative | **Superseded; accepted** | Owner decision: candidates stay at contested endpoints (148 endpoints, 297 bodies, 1.4 GB); S counts the contested editions whose copies sit in groups without sharing an address and widens only if the count matters (*est.* 8–45 GB; my same-stem proxy was 7.0 GB). DM §7.5 now says what the guard does not catch. Pages get fingerprints from their own parsers regardless. |
| G18 | "One level of nesting" | **Fixed** | A §7.2 "an archive inside an archive is not expanded". |
| G19 | Generic query-parameter names | **Fixed** | DM §7.1 filename-parameter registry with samples; §7.4 cites it. |
| R13 | 64 cut-off URLs | **Fixed** | P B14 "62 to 64 by the snapshot index depending on how a complete copy is counted; the receipts decide". |
| R15 | `detail` size basis | **Fixed** | DM §8.1 "recomputed from measured column sizes at 1.24M rows". |

## New problems the edits introduced

### Must fix

**N1. New PDFs can never be real files.** DM §7.3 adds `and (format <> 'pdf' or
r[sniff].intact)` to `real_files`. DM §6.2 defines `intact` as "From `sniff`, for a PDF", and
the `sniff` parser "reads every body whose capture rows carry no sniff at the pinned sniff
version (in practice, every older body)". A PDF captured after the switch carries the
fetcher's `sniffed_format` and `sniff_version`, so the `sniff` parser skips it, no reading
holds `intact`, the conjunct evaluates to null, and the row is excluded. `format` avoids the
same trap by coalescing the fetcher's value (`else c.sniffed_format when c.sniff_version is
that version`); `intact` has no such clause, and the `captures[]` entry (DM §5.2) has no field
for it. Today's code already computes the check on the body it holds
(`capture_inspection.py:89-99`: `%%EOF` in the last 8 KB, else a bounded reader), so recording
it costs nothing. *Fix:* add `intact` (bool, PDF only) to the `captures[]` entry and `captures`,
and derive `intact := r[sniff].intact at the pinned sniff version, else c.intact when
c.sniff_version is that version`. Better still, see S1.

### Should fix

**S1. Body classification has two homes: `record_role` and the format-keyed conjuncts in
`real_files`.** `real_files` now ends `and (format <> 'html' or not file_shaped(locator)) and
(format <> 'pdf' or r[sniff].intact)`. The first is a per-row check on the locator and belongs
there. The second is a body property, and the body's classifier is `record_role` (DM §7.3),
whose branches already cover captions, playlists, API rows, source records, error pages and
listings. Each future format check (a truncated ZIP, an unreadable DOCX) would add another
conjunct to `real_files` while invariant 8 keeps listing roles. *Reshape:* add a `damaged` role
(`when format = 'pdf' and not intact`) so `real_files` has one body predicate,
`record_role = 'document'`, plus the locator check; invariant 8 then covers broken PDFs
without a new clause.

**S2. "The URLs a copy is known by" is defined three times, differently.** The queue
(DM §7.7) tests a target against "the requested [or] final URL of any `mode = fetch` row";
`linked_from` (DM §7.10) matches the endpoint and then adds "a link whose target is a fetch's
requested URL also counts for the copy that fetch saved after its redirects"; recovery
attachment (DM §7.8) matches "the listed document that holds its original link" with no
statement of which URL holds it, which reads as `context_url` only. A recovery whose original
link redirected would therefore attach by a different rule than the link context for the same
copy. *Reshape:* define once, in §7.4 or §7.2, `copy_urls(source file) := {context_url} ∪
{requested_url of its good fetches}` by `url_key`, and have the queue, `linked_from` and
attachment all join on it. One definition replaces a bolted clause and fixes an unstated one.

**S3. `repair` makes `url_key` return a set.** DM §7.2 `url_key(url) := unwrap(repair(url))`
with "a repair may split one concatenated href into several URLs, each a separate target".
`url_key` is also applied to `context_url`, recoveries' original links and the queue's
targets, where a split has no meaning, and a key function that may yield several keys cannot
serve `source_id` joins or the uniqueness that invariant 19 assumes. *Fix:* move `repair` into
"Link targets" (DM §7.2), applied to an `href` before resolution, where splitting into several
targets is well-defined; `url_key` stays a function.

**S4. The sniff pass is no longer "one ranged read of its first bytes".** `intact` needs the
last 8 KB (a second ranged read for every PDF, about 261k more GETs) and, when `%%EOF` is
absent, "a PDF reader opens it", which needs the whole body. The text bounds neither; the
fixture "a valid PDF with trailing bytes after its end marker" is exactly the case that falls
to the full read. *Fix:* state the tail read in DM §6.2, bound the reader fallback (only when
the tail check fails; the bounded reader the bindings name; a size cap) and say what an
over-cap PDF gets (`intact = null`, not real, reported).

**S5. The 206 rule has two homes that already differ.** A §7.1: a 206 or `Content-Range`
response is incomplete "unless the fetcher assembles the whole entity from ranges and its
length matches the declared length". DM §5.2 `complete`: "false for a 206 response or one with
`Content-Range`", with no exception. *Fix:* DM §5.2 owns `complete` in full; A §7.1 cites it.

### Minor

- **N2.** Feeds and sitemaps: the feed-root registry (DM §7.1) is used only by `linked_from`,
  so an RSS or Atom body (format `xml`, root not in the source-record registry) is a
  `document` and lists. Measured: 6 feed-like URLs among good fetches in the snapshot, all six
  already rows of today's catalog, so the gap is small; give feed roots a role (`listing`) in
  `record_role` so the registry has one effect.
- **N3.** DM §7.5 `meeting_ref` "else from a source record whose `meeting_refs` name it" does
  not say how a MODS record names a document; the join is presumably the GovInfo package ID.
  Write the join.
- **N4.** DM §7.8 "An import that carries no category takes its decision's kind" exists for
  today's imports (B §8 defect, fixed by B7); mark it transitional with its removal condition.
- **N5.** DM §7.2 "A target path that several members of one archive share matches each of
  them" follows from the null-safe endpoint definition; it can go.
- **N6.** G11 residual: a queue row's `requested_url` is a page link; a link carrying a
  credential parameter reaches the published `url_state`. Apply the credential-parameter
  registry to queue targets, or say the fetcher's receipt will carry the clean URL and the
  queue row is replaced on its first fetch.
- **N7.** Invariant 8 lists the excluded bodies but not a PDF that is not `intact`; S1
  removes the need, or add it.
- **N8.** Invariant 1 requires `text_bytes`, `link_count` and `link_text_bytes` on a
  completed HTML reading; `text_head` and, for XML, `xml_root` should join the list now that
  rules read them.
- **N9.** DM §6.2 `fingerprint` is written by two producers (the page parsers and the
  `fingerprint` parser) into one column across partitions; say which reading the model reads
  for a body with both.
- **N10.** DM §7.5 `removed_on` is "the earliest `remove_date`"; a document removed and
  re-added still reads as removed. Say so, or take the latest and require no later re-add.
- **N11.** P §5.3's count of "contested editions whose re-packaged copies sit in format
  groups without ever sharing an address" needs those copies' text to decide equality, which
  is the fingerprinting being decided; say it runs on a sample.

## The refactoring audit

The documents as a system, read along the flow from receipt to release. A smell is a
hypothesis; each is tied to a failure or a change cost and given a disposition.

**Where the model is sound (keep).**
- *One home per rule* holds. Every derivation, order and registry lives in DM §5–8; A §7–8,
  §10–13 state behavior and cite it; A §9 is non-normative; P and B carry no rules. Invariants
  4 and 8 now state the two properties that matter most (pinned versions complete; a maintained
  lake and a clean rebuild give byte-identical releases).
- *Registries earn their keep.* Twenty-two lists, each with one owner rule, one consumer
  column and a sample per entry. The next publisher costs capture-scope, host-pacing and
  publisher-kind entries, and perhaps a file shape or an error URL: registry edits that are a
  profile change, with no spec, parser or SQL edit. That is the design doing what it claims.
- *Facts in the lake, classification in the model.* Readings hold `title`, `text_bytes`,
  `text_head`, `link_count`, `base_href`, `links` as written, and now `intact` and
  `meeting_refs`; the model classifies with registries. A threshold change re-parses nothing.
  Keep, and keep the discipline.
- *The lake producers depend on raw and provenance only* (filename reader, DM §6.3) and the
  identity argument (DM §8.3) is sound.

**Erosion found (reshape).**
1. *Branch accretion in `real_files`* (S1 above). Two format-keyed conjuncts now sit beside
   the role check. Mechanism of harm: the next format quality rule edits `real_files`, invariant
   8 and A §9.2 together instead of one `record_role` branch.
2. *Three definitions of "the URLs a copy is known by"* (S2). Mechanism: a redirected original
   link attaches by one rule and gets link context by another; a fourth consumer (say, a
   "where else was this URL seen" view) would write a fourth.
3. *`url_key` has absorbed a non-function* (S3). Mechanism: a key that may be several keys
   breaks `source_id` and invariant 19's uniqueness argument at the edge.
4. *A §9 as a second, informal home.* A §9.2 has been edited every round (archive members,
   placeholders, broken PDFs); A §9.3 twice (per-address grouping; "in any copy the model
   recognizes by its text"). It is non-normative, but it drifts and costs a synchronized edit
   per rule change. Reshape: cut A §9 to intent (why documents are one content, why editions
   stay apart, why links point at files) and stop enumerating conditions there.
5. *The registry table mixes three owners.* Nineteen profile registries, three raw-writer
   registries and one hybrid (capture scope) share one table under "Model Profile and
   Registries"; the "Used by" column carries the distinction. Reshape: two headings (profile
   registries; raw-writer registries), so profile membership is readable without scanning the
   column.
6. *The effective-filename chain* (DM §7.4) is seven prose steps over five columns, applied
   by two evaluators (the producer's work list and the model). Today's code expresses the same
   thing as a list of `(name, origin)` candidates with an origin order (`sources.py:119-145`).
   Reshape, modestly: write the chain as an ordered table of name sources (a registry or a
   table in §7.4) that both evaluators read, so a new name source (an inventory name, a page
   title) is one row, not an edit to prose, to §6.3 and to the parity cause list. Keep the
   per-row semantics G1 introduced.

**Compatibility sediment (keep, with a removal condition).**
- `retained_name` (older import lines), "Older lines carry it as `source_file`",
  "`original_path`", "`record.archive_members[i]`" are the ingest mapping's concerns leaking
  into the target schema's notes. Harmless and short; keep, since the mapping is versioned and
  the notes document it. The recovery kind fallback (N4) is the one that should carry its
  removal condition.

**Abstractions that do not yet earn their keep (keep for now).**
- `edition_bodies` beyond `ambiguous_bodies` adds only bodies at other contested endpoints
  with equal text, a small set with candidates narrow. It earns its keep the day the
  candidates widen; keep, since invariant 14 names it and the cost is a line.
- `text_head` at 2 KB per page reading (about 100 MB per parser version) exists to keep
  error-word markers out of the parser. The alternative, markers in the parser, is the
  layering the owner rejected; keep, cost stated.

**Missing abstraction (add).**
- `copy_urls` (S2). The one relation the three joins should share.

**The next likely changes, costed.**
- *New publisher:* registry edits only (capture scope, host pacing, publisher kinds; perhaps
  file shapes, error URLs). Cheap, as designed.
- *New registry entry:* one file edit with a sample, a profile change, a publish. Cheap.
- *New receipt shape or field:* a new ingest mapping version, a new `captures` table rebuilt
  in minutes, downstream tables untouched (body- and pair-keyed). Cheap.
- *New file format* (an EPUB, a PPTX): a `format` value in DM §6.2, a sniff signature, and
  therefore a new sniff version, which DM §6.2 says re-reads about 1.04M bodies by ranged GET;
  plus the document-extension list hard-coded in DM §7.5 (b) (`pdf, xml, htm, html, doc, docx,
  txt`), which is not a registry. The re-sniff is a stated, bounded cost (under an hour,
  about $0.40); the hard-coded extension list is a spec edit that could be the format-preference
  registry. Reshape the list into that registry; accept the re-sniff.
- *New grouping element* (a publisher that lists renditions under `<article>`): `group_path`
  is computed by the parser from a fixed ancestor list (`li`, `tr`, `meeting-document`,
  `witness-document`, `document`), so it costs a parser version and a re-parse of 287,765
  pages, where the full indexed link path would make it a registry entry at the price of longer
  strings on 5.5M targets. Hypothesis, not a finding; the trade was made knowingly.

## Numbers checked this round

| Claim | Where | Result | Status |
|---|---|---|---|
| Parent array 32 MB at 4M nodes | A §9.3 | 4M × 8 bytes | arithmetic consistent |
| `text_head` and links *est.* 100 MB per parser version | DM §6.2 | 287,765 × 2 KB ≈ 575 MB raw plus about 4.2M link structs; 100 MB compressed is plausible | estimate |
| Fingerprint widening *est.* 8–45 GB | P §5.3 | same-stem proxy over today's catalog: 17,085 bodies, 7.0 GB | estimate; low end matches |
| Feed-like bodies that would list as documents | new (N2) | 6 URLs among good fetches (1 by media type), all 6 rows of today's catalog | measured |
| PDF bodies the `intact` rule governs | DM §7.3 | 261,056 of 1,036,256 distinct bodies | measured |
| 62 to 64 cut-off URLs | P B14 | 62 and 59 by my two definitions; the plan now states the range | measured |
| 95,664 header-named files; 277,642 contexts; 1,695,040 occurrences | unchanged | unchanged | measured earlier |
| `intact` seed: `%%EOF` in the last 8 KB, else a bounded reader | B §4 K14 | `capture_inspection.py:89-99` does exactly that on the body in memory; `pdf_tools.py` is the bounded Poppler fallback | verified in code |
| "Only 200 counts as success" defect | B §3.1 | `capture_inspection.py:37-41` tests `http_status != 200` | verified in code |

## Checks that passed

- Cross-references the edits touched resolve: A §3 → DM §7.1–7.3, §7.5, §8.2–8.3; A §7.1–7.2
  → DM §5.1–5.3, §7.1; A §8.7 → DM §7.1; A §9.4–9.5 → §11.6; DM §5.3 → §7.4, §7.5, §7.8–7.9;
  DM §6.2 → §7.1, §7.3, §7.5; DM §7.2 → §7.3; DM §7.4 → §7.8; P → A §6, §7.1–7.2, §8.1, §8.7,
  §10.3.5, §10.3.7, §11, §11.6, §12, §13, §15; B → [[INVENTORY]] by section.
- Invariants 3, 4, 13 and 14 match the derivations they name; invariant 4's byte-identical
  rebuild clause has its fixture (P §5.3).
- The three documents agree on the endpoint `(context_url, member_path)`, `entry_index` as
  evidence, the narrow fingerprint candidates with page fingerprints from the page parsers, the
  per-prefix lock order (bodies and provenance first, receipts after B0), the one-off rewriter
  outside the body store, and the untouched backup.
- The bindings Note names functions as well as lines, proposes a use for each dormant piece,
  and lists the defects the plan fixes with the step that fixes each.

## What remains before building

1. N1 before D2 and E1: record `intact` in the capture entry and coalesce it, or fold it into
   `record_role` as S1 proposes.
2. S1–S5 in S, when the SQL is first written: one body classifier, one `copy_urls`, `repair`
   out of `url_key`, the sniff pass's real cost, one home for the 206 rule.
3. The reshape items (A §9 trimmed to intent; the registry table split by owner; the
   effective-filename chain as an ordered table; the extension list as a registry) whenever
   the documents are next edited; none blocks construction.
