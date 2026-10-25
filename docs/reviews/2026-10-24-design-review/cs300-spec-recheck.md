# CS 300 Recheck: Congressional Document Archive specifications (commit d9730967)

Rechecked 2026-10-25 against `d9730967` ("apply the five final spec reviews") in
`/Users/mikewolfd/Work/wt/ct-ticket-audit`: `docs/engine-first-architecture.md` (A, 570
lines), `docs/engine-first-data-model.md` (DM, 674 lines),
`docs/plans/simplification-plan-20261024.md` (P, 295 lines). My previous round is the final
review of `c3b067c4` (finding IDs F1–F22).

Method. I read all three documents in full again, kept the diff from `c3b067c4` beside me
(`specrc_docs.diff`, 639 lines), re-walked the cross-references the edits touched, checked
the new derivations against the invariants that name them, and re-measured every number
the edits changed on the read-only 2026-10-19 snapshot with DuckDB through the project venv
(`specrc_numbers.py`, output `specrc_numbers.out`). Nothing outside this scratch folder was
written.

## Verdict

**Ready to build from.** No must-fix item remains. F1 is closed the way I asked: a reading is
now a function of its body and parser version (`href` and `base_href` stored as written,
resolution in the model per fetched context, RFC 3986 cited, the engine asked for the URL
functions), so invariant 1, principle A §4.1 and the DM §8.3 identity argument hold again.
Of the 22 items from the final review, 20 are fixed, one is partly fixed (F5: XML-discovered
URLs now reach the queue, API-JSON-discovered URLs still do not) and one no longer applies
(F13: link URL keys now hash the exact URL, so there is nothing to freeze).

The edits introduced five should-fix items and ten minor ones. Two of the five should land
before the work that depends on them: the `detail` and `occurrences` writer settings
dropped their page byte limits, and with only a 1,024-row page limit a fold page is about
1.2 MB uncompressed (measured 1,172 bytes of value text per row), so the 70–90 KB per-view
claim cannot hold; and the extended edition guard (`edition_bodies`) reaches only bodies that
have a fingerprint, while `fingerprint` runs only at contested endpoints, so the guarantee
"not even a re-packaged copy with the same text" is not delivered and the plan's own fixture
for it would fail.

## Regrade

| Area | Final review | Now | Why |
|---|---|---|---|
| Correctness and completeness | A− (90) | A− (92) | F1–F8 closed; residue is the fingerprint scope behind `edition_bodies`, API-JSON links, and a relative `<base href>` |
| Efficiency (Big O) | A (94) | A (93) | Occurrences re-sized at the real grain; page byte limits dropped from `detail`/`occurrences` (3–4× more bytes per view); link targets multiply by contexts for mirrored bodies |
| Determinism and failure behavior | A− (91) | A (94) | Gate/fingerprint race removed by construction, total recovery order, review precedence that keeps every merge, exact-URL link keys, pointer bootstrap |
| Data model quality | A− (90) | A (93) | Readings are pure functions of body and version; `suffix(body)` one rule; fold enumerated; occurrences 1,695,040 and 8–12 MB |
| Specification craft | A (93) | A (94) | UI rules moved to a normative A §11.6; registry renamed to match its polarity; one "ingested only by publish" overstatement |
| Plan | A (93) | A (93) | Fixtures cover the new cases, M2 numbers corrected, C8 added, B14 honest about what the index cannot decide |

**Overall, the two specifications: A (93), up from A− (91). The plan: A (93).**

**Counts over the 22 items (F1–F22): 20 fixed, 1 partly (F5), 1 no longer applies (F13), 0 not fixed.**

## Verdicts per item

| ID | Finding | Verdict | Location and note |
|---|---|---|---|
| F1 | `base_url` made readings depend on `captures` | **Fixed** | DM §6.2 `base_href` "as written", `links[].href` "as written", "A reading depends only on its body and its parser version"; DM §7.2 "Link targets" resolves per fetched context by [[RFC3986]] §5; A §8.3 and A §13.8 (engine URL functions); P C8 with RFC 3986 §5.4 vectors. The fix I asked for. |
| F2 | Null `group_path` could form a group | **Fixed** | DM §7.5 (a) "the same non-null `group_path`". |
| F3 | `page_shaped` polarity | **Fixed** | Registry renamed "file shapes"; `real_files` uses `not file_shaped(locator)`; "`file_shaped(locator)` is true when an entry … matches" (DM §7.1, §7.3); A §3, A §15.2 and P follow. |
| F4 | Gate contradicted "one run later" | **Fixed** | The sentence is gone from DM §7.3; A §12 "Captures are ingested only by publish, so nothing lands between the lake steps and the pin" (see R6 for the wording). |
| F5 | Queue blind to XML- and API-discovered URLs | **Partly** | DM §7.7 now takes targets "from a good-fetched page whose role is not `error_response`", so meeting-XML `source_record` links count. API JSON still yields no `links` (DM §6.2: "in an HTML or XML page"), and A §12 still presents `url_state` as capture's queue (R3). |
| F6 | HTML-signal invariant lost | **Fixed** | Invariant 1: "Every completed HTML reading has `text_bytes`, `link_count` and `link_text_bytes`." |
| F7 | `detail` fold's `r.*` included `links` | **Fixed** | DM §8.1: "`r.title`, `r.heading`, `r.content_date` and `r.fields`, not its links". The 55–70 MB figure is still unexplained (R15). |
| F8 | Occurrences sized at the old grain | **Fixed** | DM §7.10 "1,695,040 occurrences today; the largest document has 455"; DM §8.1 8–12 MB; P §5.2 "the 1.7M `occurrences`". 1,695,040 reproduces exactly. |
| F9 | `url_state` count excluded the queue | **Fixed** | DM §7.7 "1,158,426 rows plus the queue". |
| F10 | "1.7M source URLs" | **Fixed** | P §5.2 "1.31M source URLs". |
| F11 | `outcome` order unnamed | **Fixed** | DM §7.10 "in `url_state`'s attempt order (§7.7)". |
| F12 | Model SQL version undefined | **Fixed** | DM §7.1 "the SHA-256 of the model's SQL files". |
| F13 | Frozen `link_url_key` registry versions not in the profile | **No longer applies** | DM §8.2 keys the exact original URL; nothing to freeze. |
| F14 | Sniff-version bump cost unstated | **Fixed** | DM §6.2 "A new sniff version re-reads about 1.04M bodies … so the profile moves them together." |
| F15 | `suffix` for alternates and recoveries | **Fixed** | DM §7.5 `suffix(body)` "used for the saved file, alternates and recoveries alike". |
| F16 | Directory comparison undefined | **Fixed** | DM §7.5 (b) "the source URL's path up to its last `/`". |
| F17 | Absent reading not covered | **Fixed** | DM §7.3 "the reading is missing or not completed". |
| F18 | `parent_system_code` nullability | **Fixed** | DM §6.4. |
| F19 | Embedded-PDF-title rule dropped | **Fixed** | DM §6.2 and A §8.3. |
| F20 | 287,765 unlabeled | **Fixed** | DM §6.2 and P §6.4 "bodies the server labels HTML or XML". |
| F21 | Archive-member `base_url` | **Fixed** | DM §7.2 resolves against "its member path for an archive member, which gives an endpoint in the same container". |
| F22 | A §9.2 summary omitted placeholders | **Fixed** | A §9.2 "that is not a placeholder". |

## New problems

### Should fix

**R1. The `detail` and `occurrences` writer settings dropped their page byte limits, and the
per-view estimate did not follow.** DM §8.1 `detail` now reads "65,536-row groups; an offset
index, a 1,024-row page limit and 1,024-value write batches on every leaf" where it read
"16 KB pages for the incompressible key columns … and 64 KB for the rest"; `occurrences`
likewise lost its 64 KB pages. A row limit alone sizes a page by its widest leaf: a
`saved_body` page is 32 KB of incompressible bytes, and the fold's `value` leaf holds 1,024
rows × 1,172 bytes (measured mean over 50,000 source files; p95 1,983) ≈ 1.2 MB
uncompressed, perhaps 150–250 KB after ZSTD. A detail view is then roughly 250–350 KB, not
the "about 19 pages, 70–90 KB" of DM §8.1 and A §16.1. `links.parquet` kept its 16 KB
pages, so a per-column limit was not the obstacle. *Fix:* keep the row limit and restore a
byte limit (16 KB for the key leaves and 64 KB for the rest, or one global 16–32 KB limit,
which small leaves never reach), then re-derive the per-view figure; "1,024-value" should
read "1,024-row". Settle it before F0, which writes "the final writer settings".

**R2. `edition_bodies` cannot reach the copies it is meant to reach.** DM §7.5 defines
`edition_bodies := ambiguous_bodies, plus every real body whose fingerprint equals that of a
body in ambiguous_bodies`, and claims "No body of a contested edition takes a rendition edge,
not even a re-packaged copy with the same text, so neither mirrors nor copies can join two
editions through a shared XML." But `fingerprint` runs only for "bodies at endpoints with two
or more distinct real bodies" (DM §6.2), so a re-packaged copy of a contested edition sitting
alone at a mirror has no fingerprint, is not in `edition_bodies`, and takes rendition edges;
two such copies, one per edition, pairing with one XML merge the editions. Invariant 14 as
written stays true (it is defined over `edition_bodies`), but the prose guarantee is not
delivered, and P §5.3's fixture "re-packaged copies of each edition paired with one XML"
would fail under the derivation. *Fix I would accept:* extend `fingerprint`'s scope to every
real body that would share a rendition group (same non-null `group_path`, or same directory
and stem) with a body in `ambiguous_bodies`; that set is small and the work list stays a
function of the lake. Otherwise narrow the claim to fingerprinted copies and change the
fixture.

**R3. API JSON still has no way into the queue (F5 residue).** DM §6.2 emits `links` for
"an HTML or XML page" only, so document URLs listed in Congress.gov API responses never
become queue rows, while A §12 still says capture "builds its queue from the live release's
`url_state`". *Fix:* either the JSON parser emits `links` for URL-valued fields (then DM §7.7
covers them), or A §12 states that fetchers keep their per-family discovery and `url_state`
supplies the recheck schedule plus the page-derived queue.

**R4. A relative `<base href>` is not resolved.** DM §7.2 resolves each `href` "against the
reading's `base_href` when present, else against each context". `<base href="/">` and other
relative bases are common; the base must itself be resolved against each context before the
`href` is resolved against it. One clause.

**R5. Link targets multiply by contexts for widely mirrored bodies.** Resolution "against
each context the page body was good-fetched at" makes a body's targets grow with its distinct
addresses. Placeholder bodies are excluded from `real_files` but not from link resolution;
the 1,245-byte HTML body at 24,387 URLs would yield 24,387 × its link count. *Fix:* exclude
placeholder bodies' links from resolution (they "connect nothing"), or cap the contexts a
body contributes and report the cap.

### Minor

- **R6.** A §12 "Captures are ingested only by publish" contradicts A §8.2, where the weekly
  check "appends anything a late receipt left behind". Say "only by publish and the weekly
  check, which never overlap (§10.3.7)".
- **R7.** DM §7.2 "its URL for a top-level page": name the column (`context_url`).
- **R8.** `detail.link_key` for a recovery-only document (DM §8.1) is "a recovery-only
  document's link URL key", but a document with several original-URL spellings has several;
  pick one (the saved recovery's original URL, or the byte-wise least).
- **R9.** `good_fetch` includes import-run rows, so a link context or `linked_from`'s "first
  good fetch" can carry an import time while `first_fetched` excludes import runs; harmless,
  but say it.
- **R10.** No verdict withdraws a review: supersession replaces a record, but there is no
  way to cancel a `hide` or an override other than superseding it with another verdict.
  Define withdrawal (a superseding record with a null `value`, say).
- **R11.** A `review_edge` whose link key no longer resolves is silently dropped; add it to
  the model's reports (DM §7.3, §7.5).
- **R12.** DM §8.1 "1,024-value write batches": batches are rows.
- **R13.** P B14 "The snapshot index gives 64; the receipts decide the two whose status the
  index lost": by my reading of the index, 62 URLs have a cut-off copy and no complete 2xx
  copy of another body (59 have only cut-off copies; the other bodies are 214-byte HTTP 520
  pages), and none of them has another body row with a null status. Close, and the plan
  rightly leaves it to the receipts, but the 64 and "two" do not reproduce from the index.
- **R14.** DM §7.10 "the largest document has 455" reproduces as the largest body-key set
  of an old document (455 body keys); at the new grain it is an occurrence count only if
  every body has one copy. Label it or re-measure in F0.
- **R15.** `detail` 55–70 MB (DM §8.1) is still unexplained after the fold shrank to four
  reading columns; restate its basis or re-derive it in F0.

## Numbers checked this round

| Claim | Where | Result | Status |
|---|---|---|---|
| 1,695,040 occurrences at the `(source_id, member_path)` grain | DM §7.10, P §5.2 | 1,695,040 (1,004,025 single-path source files + 691,015 member paths) | measured, exact |
| Largest document has 455 | DM §7.10 | 455 is the largest body-key set of an old document (largest filename list is 20) | measured; grain differs (R14) |
| 64 cut-off URLs, 2 undecided | P B14 | 62 with no complete 2xx copy; 59 with only cut-off copies; 0 undecided; other bodies are 214-byte HTTP 520 pages | approximate (R13) |
| 1,172 bytes of fold value text per source file (mean), 1,983 (p95), 32.2 values per row | new, for R1 | measured on a 50,000-row sample over 338 house-naming list columns | measured |
| 287,765 bodies the server labels HTML or XML | DM §6.2, P §6.4 | 175,197 + 112,569 = 287,765 | measured earlier, now labeled |
| About 95 MB of uploads per changed day; about 0.7 GB per week | A §16.1, §10.3.7 | 84–109 MB from the DM §8.1 sizes; 7 × 95 ≈ 0.67 GB | arithmetic consistent |
| 1.31M source URLs | P §5.2 | 1,313,678 | measured earlier, exact |
| 70–90 KB per detail view | DM §8.1, A §16.1 | not reachable with 1,024-row pages and no byte limit (R1) | estimate, now inconsistent |
| 55–70 MB `detail` | DM §8.1 | basis unstated | estimate (R15) |

## Checks that passed

- Every cross-reference the edits touched resolves: A §4.6 → §10.3.5; A §9.4 → §11.6; A §13.5
  → §7.1, §10.3.4; A §13.8 and P C8 → [[RFC3986]]; DM §5.3 → §7.5, §7.8, §7.9; DM §6.4 →
  §7.3 (`good_fetch`); DM §7.2 → §7.3, §8.2; DM §7.10 → §7.7; P A6 → A §11.6; P §5.1 → A §8.7,
  DM §6; P §6.1 → A §11; the renumbered A §11.7 has no stale citations.
- Invariants 1, 4, 8, 10, 12, 14, 19 and 20 match the derivations they now name (completed
  HTML readings carry their signals; pinned versions complete; `good_fetch` conditions; the
  saved-file and `suffix` rules; queue rows against fetch rows; `edition_bodies` as defined;
  exact-URL link keys; the pointer with a null `previous_release_id`).
- The identity argument (DM §8.3) is now sound: every lake row the model reads is a function
  of a body or filename pair and a pinned version, including the `captures` ingest mapping,
  which the profile now carries.
- A §11.6 gives the capture-date labels, the document-date source and the hearing filter a
  normative home; A §9 remains non-normative and cites it.
- The recovery order is total (kind, `imported_at` desc, `body_sha`, then the import row's
  PK); the review precedence applies every `duplicate_of` and the latest `hide` or override
  per document; `edition_bodies` and invariant 14 agree.

## What remains before building

1. R1 before F0: restore page byte limits beside the row limit and re-derive the per-view
   figure.
2. R2 before S fixes the rules: extend `fingerprint`'s scope so the edition guard reaches
   re-packaged copies, or narrow the claim and the fixture.
3. R3–R5 in S or E1; the minors whenever the documents are next touched.
