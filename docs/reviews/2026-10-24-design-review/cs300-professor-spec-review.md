# CS 300 final review: the adopted specification set (39ae52d2)

Reviewer role: systems / data-intensive software engineering, final thesis submission.
Date: 2026-10-24. Reviewed at `39ae52d2`: *Architecture* (Editor's Draft; cited **A §n**),
*Data Model* (Editor's Draft; **DM §n**) and *Implementation Plan* (Note; **P §n**), against my
four earlier reviews and, where needed, the last drafts at `c466a45e` (design rev 9, data model
rev 7, plan rev 6). Not read: pipeline code, tickets, other reviewers' files. Measurements ran
on the read-only Oct 19 snapshot through the project venv (`prof_spotchecks.py`,
`prof_detail_bytes.py` in this folder; earlier files reused from the session scratchpad).

## Verdict

**Accept with four small corrections.** The rewrite lost nothing my reviews required; it
tightened several items beyond what I asked (a `real_body` definition, registries with sample
tests, completion rows, a pointer that names the last-good release, a semantic checkpoint
before engine work). Every recurring cost is O(change) or is named as an accepted pass over
history. Of the numbers that carry weight, every one I could test matches the snapshot. One
normative writer setting is missing and makes a stated cost wrong by about 2.5×, one
normative size is out of date against an open measurement, one invariant is missing, and one
MUST has an unspecified parameter. None changes the design.

**Grades.** Architecture **A− (92)**, +1 from A− (91). Plan **A− (90)**, +3 from B+ (87).

## 1. What the rewrite kept, lost or changed

### 1.1 Kept (traced from my reviews to the specs)

| My finding | Where it lives now |
|---|---|
| F1 filename readings as a lake table keyed by `(filename, source_url, catalog_version)` | A §8.4; DM §6.3 (with `coalesce(source_url, '')` for the 331,985 URL-less rows) |
| F2 verification by LIST + ETag, no HEAD, no daily re-hash; MD5 in receipts | A §7.4, §7.2; invariant 2 |
| F3/F4 Basin named; compaction gated by measurement; dated-Parquet fallback | A §8.8; P §5.1 |
| F5 no ID in `list` | A §10.1 |
| F6 offset-index page reads, folded detail, 16 KB pages for key columns, `document_id` in the fold | A §10.1; DM §8.1 |
| F7 in-memory CC with a cap; placeholders at *k* = 100; star nodes per body/fingerprint/group | A §9.3 |
| F8 readings scope by family; sniff for every older body | A §8.3; DM §6.2 |
| F9 determinism is not dedupe | A §10.3 |
| F10 date-shaped receipt prefixes; backfill reads the non-date segments | A §7.2, §8.2 |
| F11 parity against the pinned catalog, reported by cause | P §6.5 |
| F12 Node canary; three scheduled jobs | A §10.4.5, §12 |
| rev-5: endpoint `(context_url, member_path)`; `capture_index` in the key; record roles; `page_links`; recovery-kind mapping; import day by run; `url_state` without a hash; early skip on content identity; content-only manifest with inputs records; two releases and the 404 reload | A §3, §8.2, §8.5, §9.6, §9.4, §10.4.1–10.4.7, §11.3; DM §6.1, §6.4, §7.6–7.7 |
| sanity: six tables everywhere; per-view numbers restated; `ordinal` int32; one name for the `url_state` key; "at least two" releases; `real_body` and per-row real files; API-endpoint registry; recovery-only documents; recheck-interval table; total orders for `linked_from` and `first_run`; fixed list orders; Senate codes only with sample tests | A §1, §9.1, §9.2, §9.3, §9.5; DM §6.1, §7.2, §7.3, §7.4, §7.6, §8.1, §8.3 |

### 1.2 Lost or weakened

Nothing required was dropped. Two optional items were not adopted and are listed again below
as nice-to-have: filtering a losing conflict-retry's already-parsed rows instead of
re-parsing (A §8.1 still says only "write only what is still missing"), and a page row limit on
`detail` (I asked for 16 KB pages, which the set adopted; the row limit is the gap that
§2.1 below measures). Numbers I had questioned (meeting coverage, the 99.7 % claim, the
"dozens" of fingerprint candidates) were removed or corrected rather than restated; under the
owner's rule that only sizing numbers stay, that is the right outcome.

### 1.3 Changed meaning, deliberately

- The 87,161-URL placeholder is now correctly identified as a 57-byte caption file, not an
  error page (A §9.3). Measured: `text/vtt`, 57 bytes, 87,161 distinct context URLs. My earlier
  reviews had it wrong.
- Publish no longer deletes failed candidates; only maintenance deletes, after re-reading the
  pointer (A §10.4.7, §14). This closes the token-scope contradiction I raised in rev 5.
- `list` now sorts editions by document date before capture date (A §9.4, §10.1; DM §8.1;
  invariant 14), following the owner's document-date decision.
- `url_key` drops the scheme instead of lowercasing it, and decodes unreserved percent-escapes
  (DM §7.1).
- Recovery links get their own URL-derived link key, so a recovery-only page keeps its link
  when the original finally downloads (A §3, DM §8.2).
- The decision table, revision notes, estimates and schedule are gone by design.

## 2. Review on its own terms

### 2.1 Correctness and consistency

Cross-document consistency is good: six lake tables everywhere (A §1, §6, §9.1; DM §6; P §6.4);
22 invariants (A §15.7; DM §10); the `list` order, the saved-file order, the real-file rule,
the edge set, the input identity and the retention rule each appear in both specifications
with the same wording. The findings:

1. **`detail` has no page row limit, so its per-view cost is understated (must-fix).** DM §8.1
   gives `detail` "16 KB pages for the incompressible key columns … 64 KB for the rest; write
   batches of 1,024 rows", and `occurrences` "a page row limit of 512–1,024". A write batch
   does not end a page; only a page size or a page row limit does. A sparse typed-core column
   (`meeting_refs`, `measure_keys`, `recoveries.*`, `occ_len`) therefore becomes one page per
   column chunk, and a point read fetches the whole chunk. Recomputed from the files I built
   earlier, under the adopted page sizes with `document_id` moved to the fold: 17 leaves,
   **≈308 KB per view at 1.24M rows** (`occ_start` 49 KB, `meeting_refs` 56 + 40 KB,
   `occ_len` 30 KB, the two hash columns 16 + 6 KB, the fold 24 KB), against "about 15 page
   reads, roughly 120 KB" (A §10.1, §16.1). With a 1,024-row page limit on every `detail`
   leaf, the sparse columns cost under 1 KB each and the view is ≈70–90 KB. The engine
   capability already lists page row limits (A §13.3). Fix: one phrase in DM §8.1 and A §10.1.
2. **`detail` size (nice-to-have, a number).** "30–50 MB" (A §10.1; DM §8.1) scales my
   measured core-without-`document_id` plus fold to **≈65 MB at 0.65M documents** (124 MB at
   1.24M). DM §8.1 already says "measured in F0"; say 55–70 MB, and "about 90 MB of uploads"
   (A §10.3, §16.1) becomes about 105.
3. **Lake row-group sizes conflict with an open measurement (must-fix).** DM §6 states
   normatively that row groups hold 131,072 rows (`captures`, `page_links`) and 65,536 (others),
   while P §5.1 item 3 says the engine caps every R2 file at 2 MiB and every row group at 2,048
   rows and keeps the cap "only if it measurably helps". Either the cap goes (then say so as a
   C-track requirement) or DM §6's numbers are conditional on M1. As written, a conforming
   engine could not write the data model's tables.
4. **A saved file's physical object is never checked to exist (must-fix, one invariant).**
   `saved_body` + `saved_suffix` is the physical key (DM §7.4, §9). Invariant 2 covers bodies
   in `captures`; nothing covers the `.pdf` copies that B13 creates over "a few hours" for
   261,055 objects, and the canary opens one saved copy (A §10.4.5). A document whose
   `saved_suffix` is `.pdf` can 404 for every user until B13 finishes or if it skipped a body.
   Add to invariant 17 (or the weekly LIST join, which already lists `bodies/`): every physical
   key a release names exists.
5. **"Retry a bounded number of times" (A §8.1) has no bound.** A MUST with an unnamed
   parameter is not testable; name it (three is plenty for a compaction race).
6. **Small inconsistencies.** Invariants 20 and 21 both forbid a rendition edge at an
   edition-ambiguous endpoint (20 also carries the hidden-document rules; split it). DM §6.3
   says the catalog qualifies "25 URLs in 7 lists"; `guide.json` 3.2.7 has 25 URLs in 9
   `source_urls` lists. A §7.4's "about 1,000 list requests" becomes about 1,300 once the
   261,055 `.pdf` copies sit under `bodies/`. P §6.2 B14's "62 URLs" is 59 by the snapshot's
   own cut-off rows (201 bodies, 207 attempts). None of these changes a decision.

### 2.2 Efficiency in Big O

Recurring work: capture O(new attempts); ingest O(new receipts) read plus an anti-join over
ingested keys; readings and filename readings O(new items); fingerprints O(candidates: 148
endpoints, 297 bodies, 1.4 GB measured); publish O(release size); detail views O(1) pages per
leaf. The accepted passes over history are named in principle 4 (A §4): work-list anti-joins,
the daily model recompute (O(N log N), 3.7 s proxy), and the weekly LIST of body metadata. The
grouping is linear by construction (one node per body, fingerprint or rendition group, A §9.3),
`url_key`'s unwrap loop is bounded by wrapper nesting, and every join named in DM §7 is a hash
join on a key. I found nothing superlinear.

Three items are repeated or history-shaped and should be named rather than hidden:

- The `fingerprint` producer "evaluates the model's real-file rule over the current lake" every
  publish (A §8.3; DM §6.2), and the model evaluates it again after the pin: the same O(N) pass
  twice per run. Seconds, and it buys fingerprints that are never a run behind; name it in
  principle 4. A backfill that lands between the fingerprint pass and the pin leaves those
  bodies one run behind; say that too.
- `page_links` grows with page *re-fetches* × links per page, not with documents (A §8.5).
  It is bounded by the recheck policy (DM §7.6), which is why that policy table should exist
  before track F; add it to principle 4's list.
- Superseded `filename_readings` versions are kept (DM §6.3, "that cost is accepted"): O(versions
  × pairs) storage, ≈32 MB per version. Fine; it is already named.

A losing conflict retry re-parses its batch if "write only what is still missing" is read
literally (A §8.1); filtering the parsed rows by the new work list keeps do-once without
changing correctness (nice-to-have).

### 2.3 Is every normative requirement testable?

Almost. Each MUST maps to a test, a registry sample test, or an invariant: create-only PUTs and
412 handling (weekly join, invariant 2–3), date-shaped keys (invariant 3), commit
requirements and conflict retry (P §5.1 tests), completion rows (invariant 19), version
completeness (invariant 4), real-file conditions (invariants 5, 8, 22), `real_body`
uniqueness (7), ID formulas (9 with golden vectors), saved-file order (10), `url_state`
(11), recoveries (12), release structure and the pointer (13–17), the 404 reload (18), review
semantics (20), rendition groups (21), `url_key` on every link join (DM §7.1, sample tests
per registry entry), the fold holding display-only facts and the model never unnesting
`fields` (DM §4, §6.3: checkable by inspecting the model SQL). Four requirements lack a
stated check:

- the retry bound (§2.1 item 5);
- "writers MUST NOT use multipart upload" (A §7.1): add to invariant 2 that no ETag in the
  weekly LIST contains `-` (the multipart marker);
- principle 5, "application policy MUST NOT be compiled into the engine": a review property;
  a ratchet test that the engine crate contains no application identifiers (committee codes,
  family names, registry values) would make it one;
- speed targets (A §11.2) are deliberately measured first, so they are testable once set; the
  plan's A11 does that.

### 2.4 Does the plan front-load the risks?

Yes, better than the draft did. The order (P §4) puts the bucket lock and the cut-off re-fetch
first; then M1 (Basin commits under compaction, the 2 MiB cap), M2 (wide joins and grouping on
the real data in a throwaway DataFusion harness) and S (the grouping rule as SQL, adversarial
fixtures and a hand-labeled sample with a written rubric) before any engine capability is
built; then F0 plus a hand-built fixture so the reader and canary start against the final
writer settings while C runs. B13 waits for the lock and the refusal matrix (P §6.2), which is
the right order for the largest raw write. The parity comparison is many-to-many and keyed by
source evidence (P §6.5), which is what the 141,762 shared body keys require (measured
exactly).

Two things the order does not surface early: the `page_links` volume ("3–5M rows" is an
estimate; D1 will know) and the `meeting_records` sources, which depend on new fetchers (B16)
and are on D's critical path for the hearing pages. Neither is a risk to raw data or users;
both are cheap to measure in S.

## 3. Spot-checks

| Claim | Where | Result | Status |
|---|---|---|---|
| Import day: 708,626 receipt lines, 745,456 capture rows | A §5 | 708,626 / 745,456 | **measured**, exact |
| 2,596,054 lines; 1,041,863 bodiless | A §8.2; DM §6.1 | 2,596,054; 1,041,865 | measured |
| 331,985 source rows with no URL | DM §6.3 | 331,985 | measured, exact |
| Multi-valued facets: 24,202 kinds, 3,637 families, 5,229 committee codes | DM §6.3 | 24,202 / 3,637 / 5,229 | measured, exact |
| *k* = 100 → 18 placeholders (22 at 50, 12 at 200); a 57-byte caption file at 87,161 URLs | A §9.3; DM §7.2 | 22 / 18 / 12; top body 87,161 URLs, 57 bytes, `text/vtt` | measured, exact |
| About 34,000 HTML members inside ZIPs | A §9.2; DM §7.2 | 34,443 bodies at successful `.zip` URLs | measured |
| 141,762 body keys in several old documents | P §5.4 | 141,762 | measured, exact |
| 36,137 documents whose URL last returned 404/410; 3,042 saved files over 50 MB | P §7 | 36,137; 2,811 (primary body, original bytes) | measured; second is definition-dependent |
| 1.7 % of documents with a meeting have several, up to 9 | DM §8.1 | 3,576 of 211,421 (1.7 %), max 9 | measured |
| 25 exact mirror URLs in house-naming 3.2.7 | DM §6.3 | 25 URLs in 9 `source_urls` lists | measured (list count differs) |
| 148 endpoints, 297 bodies, 1.4 GB of fingerprint candidates | A §8.3 | from my rev-5 pass | taken (measured earlier) |
| 1.26M components, largest 456 | A §9.3 | from my rev-4 pass | taken |
| 16,775 file-shaped HTML bodies (narrow list); 44,047 (broad) | DM §7.2 | 16,775 mine; 44,047 the owner's | taken |
| Listed documents 0.6–0.7M | A §5 | my breakdown (1.24M − 454k − 98k − 10k − 1k, before sniff and merges) | estimated |
| `list` about 2.2 MB | A §10.1 | 1.68 MB at 0.5M with meeting ids, delta filenames; scales to 2.2 | estimated, consistent |
| `detail` 30–50 MB; about 120 KB per view | A §10.1; DM §8.1 | ≈65 MB; ≈308 KB per view without a page row limit, ≈70–90 KB with one | estimated; **both off** (§2.1 items 1–2) |
| `links` 7–9 MB; `occurrences` 20–30 MB; `url_state` 10 MB | A §10.1 | 10.7 MB at 963k keys; 22.7–33.6 MB at 4.7M rows; 42.8 MB with a hash, ≈10 without | estimated, consistent |
| 3.7 s / 1.75 GB relational proxy; 1–2 s grouping | A §5 | my first review | taken |
| Filename readings 7–18 minutes per catalog version | A §16.1 | 1.39M × 0.31 ms = 7.2 min single-threaded | estimated, consistent |
| Weekly check about 1,000 LIST requests | A §7.4 | ≈1,300 once the `.pdf` copies exist | derived, slightly low |

## 4. Grades and defense questions

**Architecture: A− (92).** Up one point: the semantic rules are now precise enough to
implement and test, the registries make every list a tested artifact, and the cost model is
honest about its history passes. It is not an A because one normative writer setting is
missing and makes a quoted cost wrong (§2.1 item 1), one normative size contradicts an open
measurement (item 3), and one user-visible failure (a missing `.pdf` copy) has no invariant
(item 4).

**Plan: A− (90).** Up three: with estimates removed by decision, the plan is judged on order,
dependencies and evidence, and it front-loads the right risks (lock, Basin, wide joins, the
semantic checkpoint with a labeled sample). It is not higher because M1's cap decision is not
tied back to the data model's normative row-group sizes, and the `page_links` and
`meeting_records` volumes are not measured before D.

**Three questions for the defense.**

1. *Detail pages.* "Your detail view costs about 120 KB. Which setting bounds the page of a
   sparse typed-core column such as `meeting_refs` or `occ_len`, given that a write batch does
   not end a page? Show the per-leaf arithmetic with and without a page row limit."
2. *Fingerprints before the pin.* "The fingerprint producer evaluates `real_files` over the
   current lake, then the publish run pins snapshots and the model evaluates `real_files`
   again. What guarantees the two evaluations agree, what happens when a background backfill
   commits between them, and why not have the model emit the candidate set for the next run
   instead of evaluating the rule twice?"
3. *Saved files that are not there.* "Invariant 2 proves every body in `captures` exists. Which
   check proves that the physical key a release hands a user, `saved_body` plus `saved_suffix`,
   exists, including the 261,055 `.pdf` copies B13 writes over several hours, and what does a
   user see while it does not?"

## 5. Fix before implementation, ranked

1. **must-fix** — Add a page row limit (1,024 rows) to every `detail` leaf in DM §8.1 and A
   §10.1, and restate the per-view cost (≈70–90 KB with it; ≈300 KB without).
2. **must-fix** — Reconcile DM §6's normative row-group sizes with P §5.1 item 3's 2 MiB /
   2,048-row engine cap: make the sizes conditional on M1 or require the cap's removal in C.
3. **must-fix** — Add an invariant that every physical key a release names (`saved_body` with
   its suffix, alternates, recovery bodies) exists, checked by the weekly LIST join or the
   canary; it covers the B13 window.
4. **must-fix** — Name the conflict-retry bound in A §8.1.
5. nice-to-have — `detail` 55–70 MB and uploads about 105 MB; weekly LIST about 1,300
   requests; 9 mirror-URL lists; 59 cut-off URLs.
6. nice-to-have — Name the fingerprint producer's second `real_files` pass and `page_links`'
   re-fetch growth in principle 4; say the retry filters parsed rows rather than re-parsing.
7. nice-to-have — Make two MUSTs testable: no `-` in any body ETag (multipart), and a ratchet
   that the engine crate carries no application identifiers.
8. nice-to-have — Split invariant 20; remove the duplicate rendition clause in 21.
