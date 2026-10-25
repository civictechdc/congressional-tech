# Final evolutionary review of the specs at c3b067c4

Mode: audit, read-only. Read in full: A = `docs/engine-first-architecture.md` (558 lines), D = `docs/engine-first-data-model.md` (664), P = `docs/plans/simplification-plan-20261024.md` (288), all at c3b067c4. Line numbers below are from those files. No scripts were run; nothing here is a measurement.

## Verdict

**Sound enough to build from.** "One home per rule" landed: the data model owns every schema, derivation, order and registry; the architecture's §9 is intent and cites; the plan lists work. Of my 18 findings, 15 are fixed, 3 partly; of the 16 bolted-on items, 12 fixed, 3 partly, 1 not. Every cross-reference I followed resolves to the right renumbered section. The next-change question ("where is a new parser version or registry added?") now has one answer: D §7.1.

Eight new items remain, two of them substantive (a reading that is not a pure function of its body, and a sentence that contradicts the publish-refuse rule). None blocks starting M1, M2 and S; all should be fixed before track D is built.

## 1. Verdict on the 18 earlier findings

| # | Finding | Verdict | Where the fix is |
|---|---|---|---|
| 1 | Publish sequence and input identity stated four times | **Fixed** | D §8.3 owns the identity (D:565); A §10.3.1 is one sentence citing it (A:396); old D §8.4 deleted; A §12 carries the order once (A:460–468). |
| 2 | `record_role` owned in seven places; listing bullet bolted on; inv. 22 redundant | **Fixed** | D §7.3 decision ladder (D:352–361) is the sole owner; A §3 cites (A:92); A §9.2 is non-normative prose; inv. 8 absorbs listing (D:624); inv. 22 gone. Residual: A:287 and D:191 carry the same sentence ("parsers record facts … the model classifies with registries"); see new item 7. |
| 3 | `fingerprint` producer crosses the lake/model boundary; ordering repeated five times | **Partly** | The dependency now has an owner, D §7.3 last bullet (D:388), and D §6.2 names `real_files` as its scope (D:213). But the ordering is still said in A:156 (Principle 4), A:292, A:468 and D:388, and D:388's second sentence conflicts with the refuse rule; see new items 1 and 3. |
| 4 | Parser-version completeness carried a daily-run workaround | **Partly** | Reshaped as recommended: the model profile pins versions (D:292–296); "newest complete" is gone. But the refuse rule is normative in two places (D:296 MUST, A:396 MUST) and restated at D:567 and A:294; see new item 2. |
| 5 | Registries defined in Conformance, named ad hoc, enumerated three ways | **Fixed** | D §7.1 table (D:300–314); A §2's sentence removed; A §3 defines the term and cites (A:85–86); every site now says "the X registry" (D:302–314, D:362–366, D:385, D:424, D:493, D:508); P:111 cites §7.1. |
| 6 | Recovery attachment stated six times | **Fixed** | D §7.8 "Attachment" (D:510) owns it; D:405, D:558, inv. 19, P:135 cite; A §9.6 is non-normative. |
| 7 | Saved-file order stated five times | **Fixed** | D §7.5 "saved-file order" (D:432–436) owns it; inv. 10 refers to it by name; A:109–110 cites; A §9.4 is prose. |
| 8 | `list` order stated five times | **Fixed** | D §8.1 "Order" (D:534); inv. 17 says "sorted by its order"; A §10.1 table has no order column. |
| 9 | `alternates` had no tie-break within a format | **Fixed** | D:439–440: "for each other format, its first real source file in the saved-file order"; the order gained `source_id` as a final key (D:432). |
| 10 | `url_variants` had no consumer | **Fixed** | D:325–326 makes it `url_key`'s last step; D:138 names that consumer. |
| 11 | Completion rows used a boolean and per-table sentinels | **Fixed** | One rule in D §6 (D:150) with "type's zero value"; per-table notes are "§6" (D:254, D:275). `is_completion` is kept beside zero-value PKs, which is still two signals for one fact, but defined once; acceptable. |
| 12 | Release-rerun HEAD carve-out stated twice with an untestable claim | **Fixed** | A:408 keeps the rule without "the only HEAD"; capability 5 says "except as §7.1 and §10.3.4 allow" (A:485). |
| 13 | `first_run` had no consumer | **Fixed** | Column deleted (D §7.4); P no longer names it. |
| 14 | `date_kind` stored as a derivable outside `list` | **Fixed** | Defined only in the `list` row (D:542); gone from `documents` columns (D:481) and the `detail` fold (D:543). |
| 15 | Terminology entries carried rules | **Fixed** | Every entry is identity plus a citation (A:61–149). |
| 16 | Plan E1, D2 and B2 restated the model and schemas | **Fixed** | E1 is two lines citing S (P:214); S cites D §7 (P:111); D2 lists steps, not columns (P:200–204); B2 is framed as "what changes from today" (P:150). |
| 17 | A §16.2 duplicated plan §5 | **Fixed** | One sentence (A:534). |
| 18 | Non-sizing numbers, several duplicated | **Partly** | "25 URLs in 7 lists" gone; 1.26M/456 gone; list-size and hex-size numbers gone (A:374, A:376); the catalog-row breakdown is in D:456 only, with A §5 citing it (A:173); "about 34,000" once (D:387). Residual: A:228 "The 201 bodies" (a count of evidence, not a size), D:236's 498/955/2 counts (rationale for a rule, not a size). |

Totals: fixed 15, partly 3, not fixed 0, no longer applies 0.

## 2. Verdict on the bolted-on list

| Item (old location) | Verdict | Now |
|---|---|---|
| A:232 sniff clause on the stored-bytes paragraph | Fixed | A:220 ends at "receives the original bytes"; D:211 holds the decompression note once. |
| A:268 "the lock, not the token" | Partly | A:255 still says "it is what stops deletion and overwrite (§14)" and §14 says it again (A:495–497); harmless but two. |
| A:315 / A:317 fingerprint and version sentences | Partly | See findings 3 and 4. |
| A:325 "producer applies the effective-filename rule itself" | **Not fixed** | Still in both A:298 and D:239, each a full sentence. Keep D:239 (it is the work-list definition); A:298 can end at "…cannot live in `readings`". |
| A:380 third bullet under "two checks" | Fixed | Gone. |
| A:399 largest components sentence | Fixed | Once, at D:455. |
| A:486 "only HEAD the system makes" | Fixed | A:408. |
| A:510 "33,479 occurrences" | Fixed | A:430 drops the number; D:545 keeps it. |
| A:514 "about twice the target row count" in a spec | Partly | Gone from A; now twice in P (P:120 and P:139). Keep P:120; P:139 can say "F0 is oversized (§5.4)". |
| D:195 "now" | Fixed | D:204. |
| D:229 / P:205 superseded versions kept | Fixed | D:152 only. |
| D:380 ID serialization bullet | Fixed | Merged into the `source_id` row (D:396). |
| D:597 invariant 22 | Fixed | Gone; split into inv. 8 and 17. |
| P:90 remote write cap argument | Fixed | P:92 is one action with a decision rule. |
| P:110 rubric contradiction | Fixed | P:113: "identical bytes, the same text at one address, or one text in different formats". |
| P:138 "waits for B13" | Fixed | Replaced by the switch checklist (P:253–259) and the F dependency on B13 (P:80). |

Totals: fixed 12, partly 3, not fixed 1.

## 3. New problems

Ranked. Items 1–3 should be fixed before track D; the rest are tidy-ups.

### 3.1 `base_url` makes a reading depend on `captures`, so a reading is no longer a pure function of its body
- D:205: `base_url` is "the page's `<base href>`, else the URL of the body's first capture row in the order `(retrieved_at nulls last, receipt_key, receipt_line, capture_index)`"; D:206: `child_url` "is resolved against `base_url`".
- Mechanism: `readings` is keyed by `(body, parser, version)` and D:191 says parsers record facts about the body. With this fallback, the same body produces different `links[].child_url` depending on which capture row ingested first, and a late receipt with an earlier `retrieved_at` changes the answer after the row is written. Invariant 1's new clause ("a parser version re-run on a sample reproduces its rows, links included", D:614) would then fail on any such body, and the model profile's claim that readings are "a deterministic function of a body … and a version" (D:567) would be false. Bodies with relative links and no `<base>` fetched at several URLs are exactly the mirrored pages the design cares about.
- Change: store links as written, plus `<base href>` when present (`base_href string, nullable`); resolve `child_url` in the model against the capture row's URL at join time, where `captures` is already in the plan. Delete the capture-row fallback from D:205. This keeps the reading pure and costs one string op in SQL the model already recomputes each run.

### 3.2 D:388 contradicts the publish-refuse rule
- D:388: "`real_files` is evaluated twice per publish … A body that lands between the two gets its fingerprint one run later." D:296 and A:396: publish MUST refuse when any pinned version's work list is not empty at the pinned snapshot.
- Mechanism: if a candidate can lack a fingerprint at the pin, the `fingerprint` version's work list is non-empty and publish refuses; it does not "wait one run". Inside one publish run nothing lands between the lake steps and the pin (captures is ingested first, A:460), so the sentence describes a case that cannot occur and, if it could, would be handled by refusal. It reads as a defensive patch.
- Change: delete the second sentence of D:388, and reduce the first to "`fingerprint`'s work list is `real_files` over the current lake, so it runs last among the lake steps ([[ARCHITECTURE]] §12)". If a race between concurrent lake writers is the real worry, say that publish owns all lake steps in one job (A §12 already implies it) and stop.

### 3.3 Two normative homes for "publish refuses an incomplete pinned version", and the fingerprint order said four times
- Refuse: D:296 (MUST), A:396 (MUST), D:567 (restated), A:294 (restated), inv. 4 (test form, fine).
- Fingerprint last: A:156, A:292, A:468, D:388 (plus D:213 implicitly).
- Change: D §7.1 owns the refuse rule (it is a profile rule); A §10.3.1 says "refuse per [[DATA-MODEL]] §7.1"; delete the clause at D:567 (it already cites §7.1). For the order, A §12's "Order" bullet (A:468) owns it; cut the clause from Principle 4 (A:156, where it is an implementation detail inside a principle) and shorten A:292 to "its work list is `real_files` over the current lake (§12)".

### 3.4 The CI concurrency group contradicts "correctness MUST NOT depend on a CI feature"
- A:422 (§10.3.7) makes the shared group "what keeps retention from deleting a release a publish run is about to make live"; A:475 then adds an exception to the local-runs principle and a MUST on humans running jobs by hand. P:157 and P:233 repeat the group.
- Mechanism: retention already deletes only prefixes that are neither live nor last good *and more than a day old* (A:424), and publish never deletes (A:422). A candidate uploaded, canaried and flipped within a run is minutes old, so retention cannot touch it; the outgoing last-good is demoted by the flip and becomes deletable only a day later. I cannot find the race the group prevents. If one exists (for example a candidate that sat failed for over a day and is then retried under the same release ID), name it; otherwise drop the exception at A:475 and keep the group as an operational convenience, not a correctness dependency. Hypothesis: confirm with the owner before changing.

### 3.5 `link_url_key` freezes registry versions forever
- D:558: a recovery's link URL key uses "`url_key` under the URL-wrapper and strip-list registry versions fixed when link keys were first published; later versions change joins, never published keys".
- Mechanism: the model must carry two registry versions for `url_key` indefinitely, and the profile must distinguish "join" versions from "key" versions, which D §7.1 does not describe. The stability goal is right; the mechanism is heavier than needed.
- Change: derive the key from the exact `original_url` string of the provenance record, which identity rules already keep exact (D:342): `sha256('url:' || original_url)`. It is stable by construction with no frozen versions. Cost: two recovery decisions that spell the same link differently get two keys, each resolving to the same document by the attachment rule, which is harmless. If the owner prefers one key per link, keep the current text but add the frozen versions to the profile table in D §7.1 so the rule has a home. Hypothesis, not a defect.

### 3.6 A failed or oversized reading now silently drops a body from documents
- D:355: `record_role` is null "when format in ('html', 'xml', 'json') and reading.status <> 'completed'", and D:383: "A parsed format whose reading did not complete has no role, so it is never a real file." D:198 lists `size_limit` among reading statuses.
- This is a meaning change from 39ae52d2, where an HTML body with a failed parse still had `record_role` from the parser or none, and the real-file rule did not mention reading status. A large real HTML document whose parse hit `size_limit`, or an XML bill whose parser errored, is now excluded from the explorer with no report. The rule may be right (no facts, no classification), but it is new behavior.
- Change: keep the rule and add one reporting line to D §7.3 ("the model reports bodies with no role by format and error type") so the exclusion is visible, and add "failed reading" to the parity causes at P:218–223. Behavior change to confirm with the owner.

### 3.7 Small duplicates left after the restructure
- A:287 and D:191: the same sentence about parsers recording facts and registries classifying; D:298 says the lake-rewrite consequence a third time. Keep D:191; A:287 can say "parsers record facts; the model classifies them ([[DATA-MODEL]] §6.2)".
- A:298 and D:239: effective filename computed by the producer (see §2 above).
- A:230 and A:257: the re-hash of a body with no creating line is in both the crash paragraph and the weekly-check paragraph; D:140 says it a third time. Keep A:257 and D:140.
- D:425 and D:453: edition-ambiguous bodies take no rendition edges, as rule then as bullet with rationale. Keep the rule; trim D:453 to the one clause that adds information ("a reviewer's merge still can").
- A:450, D:561, P:130: a link key that no longer resolves opens a not-found notice. A reader behavior; A §11.5 owns it; delete D:561 and shorten P:130.
- A:89 and D:292: the model profile's six components listed in both. A:89 can say "the set of versions one publish reads ([[DATA-MODEL]] §7.1)".
- P:120 and P:139: F0 is about twice the target.

### 3.8 Wording that still reads bolted-on
- A:224: the existence-check sentence is prepended to, and "Every capture entry records the suffix…" appended to, the original Write paragraph; and A:226's rationale ("Over half of body-bearing attempts hit an existing body") now mostly describes the existence check, not the 412. Rewrite §7.1 "Write" as one three-step rule (in-run set, `.gz` check, create-only PUT), with 412 as its last clause.
- A:232: "and the job that writes each copy records a verification record for both the source and the copy (§7.3)" is an appended clause; D:140 owns it.
- A:257: "It reads no body bytes, except that it downloads 25 random bodies …" is a contradiction-shaped sentence; say what it reads.
- A:156: Principle 4 has become a six-item list; principles should not enumerate steps.
- D:236: "Scalars take one value or none" is right, but the three counts are rationale, not sizes.

### 3.9 Citations
Every citation I followed resolves to the intended renumbered section (A §10.3.x, A §8.7, D §7.1–7.10, D §6.6 for `pdf_text`, P's D4/D5 and B10-after-B13 ordering). A:422 cites §12 and A:475 cites §10.3.7 for the same fact, which is circular but not wrong. No wrong citation found.

### 3.10 Over-engineering check on the additions
- **Model profile:** earns its keep. It replaced the dynamic "newest complete version" rule (finding 4) and gives the input identity a two-line definition (D:565). Its one cost is the duplicated refuse rule (3.3).
- **Registries table:** acceptable. Thirteen small versioned files handled one way beat two mechanisms (some in SQL, some in files). "Format preference", "import runs" and "capture scope" are tiny, but uniformity is the simpler rule. The version-as-SHA-256-of-bytes definition is the right level.
- **`meetings.parquet`:** justified. The alternatives (per-document duplication in `detail`, or in `list`) cost more bytes for the same reads; a 1–2 MB file read whole when a hearing is shown is the plain design, and invariant 16 keeps it consistent.
- **`base_url`:** the need is real (relative links); the fallback is the problem (3.1). With the fallback removed it is a nullable string column, which is fine.
- **Fingerprint normalization (D:213):** necessary precision for byte-determinism and cross-format equality; not over-engineered. "Visible text for HTML" is the right choice since `same_text` only applies within one endpoint.
- **Existence check plus `stored_suffix`:** one HEAD per new body (about 1,500 a day) to avoid a second copy under a new suffix; proportionate, and the suffix is recorded where it is known. Fine.
- **`url_state` queue:** fine; it is a derivation plus one registry.
- **`link_url_key` frozen versions:** the one addition I would simplify (3.5).

## 4. Owner decisions, consistency

All still consistent: editions apart (A:332, D:425, inv. 14); ZIP members by own path (D:387); every facet value (D:227); listing pages not documents (D:360, inv. 8); one format per file in a rendition group (D:425–426, inv. 14); a recovery with no single document keeps its page (D:510); document date filename→contents→meeting, separate from capture date (D:445–447, inv. 11); hide leaves a note, duplicate merges (D:517–518); raw on R2 only (A:261); speed after measuring (A:434, P:139); no schedule (P throughout). The new decisions (no `page_links`, `.gz` existence check with `stored_suffix`, the queue, `recoveries.parquet`, ambiguous bodies take no rendition edges, accepted crash attribution gap, shared concurrency group) are each stated in one normative place, except the concurrency group (3.4) and the fingerprint order (3.3).

## 5. Final verdict

Build from it. The structure now has one owner per rule in all but the cases above, the citations are correct, and the next change (a new parser version, registry or release file) lands in one place: D §7.1 or D §8.1. Fix 3.1 and 3.2 before track D exists, decide 3.4–3.6 with the owner, and treat 3.3, 3.7 and 3.8 as a half-hour tidy.

Coverage: all three files read in full at c3b067c4; the commit message was read for the list of folded-in decisions. Not run: any script, test or build.
