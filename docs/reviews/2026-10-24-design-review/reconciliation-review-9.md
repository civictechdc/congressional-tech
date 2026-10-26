# Review 9 reconciliation: implementation plan and bindings

**Reviewers:** Codex (gpt-6-astra, max effort) gave the plan **70/100** and Opus (max effort) gave it **63/100**; both say it is not ready to execute.
**Validators:** the code-claim validator scored the reviewers' accuracy at Codex 95, Opus 93. The data-claim validator scored them Opus 80, Codex 70. The lead re-derived the claims marked *(lead)*.
**Snapshot:** docs at `d4a18af2`.

## Patterns

### 1. Phase 1 is not closed (both reviewers; my phase-split errors)
- The dependency table still has D and F waiting on B13. B9 waits on B10. The receipt-key lists sit in phase 2. A §7.4's skip rule would skip bodies that have only a listing baseline.
- Phase-1 model inputs come from phase-2 work: `chambers` (committees, meetings), recheck bands (meeting dates), `meeting_refs` via transcripts, `witness_keys`.
- Phase-1 capture discovery: today's daily capture is seeded from the weekly inventories (`capture-raw-sources.yml:326-334`). F2 drops those seeds, but B15 is in phase 2.
- C's done-when needs the full export before D and E exist, which is a cycle. B11 is missing from phase 1.
- Phase 2 is not purely additive: new evidence can change dates, membership, copies and IDs.
- **Fix:** rewrite §4 and the done-whens. Phase 1 names its exact inputs. Chambers come from the committee code's first letter. Undated families use the shortest band. Meeting refs and witnesses are empty. The receipt-key lists and B11 move to phase 1. The listing baseline becomes B9's first run.

### 2. Raw safety
- **B0 misses cookies.** There are 534,733 keyed values plus 603,497 `{name, value}` header items (validated exactly). Both reviewers missed `x-archive-orig-set-cookie` (268 items plus 256 keyed). The fix is a field-agnostic scan with a suffix match on `set-cookie`, covering path key names (3,037 lines) and embedded paths (12 lines). The 160 `/home/` hits are URL paths in error text and must not be cut.
- **B0 mechanics.**
  - Rewrite only the 886 receipts that change (901,568 lines).
  - Choose `ensure_ascii` per line: under one fixed setting, 228 lines (ensure_ascii off) or 31,098 lines (ensure_ascii on) fail the byte round trip, and no line fails both.
  - Drain old writer revisions, and pause writers for the final delta (Codex S1).
- **Lock semantics are unmeasured.** No local doc states how a locked key answers a create-only PUT. Probe it on a scratch bucket before the owner locks (Opus MR-6).
- **`provenance/` at lock.** `provenance/recoveries/accepted-<sha>.json` (9.6 MB, a one-off) breaks the `<kind>/<ts>.jsonl` layout. List the prefix before locking. B7/B8 records stay in scratch until E4 accepts them.
- **The old capture decides existence by index lookup** (`raw_archive.py:660`). Until the switch, one LIST of `bodies/` is joined to the index.
- **Overwritten source records** *(lead, widened from Opus MR-2)*:
  - The weekly job keeps Congress.gov meetings and committees, YouTube API data, GPO evidence and the meeting inventories only on `pipeline-data`, which `save-pipeline-data.sh` replaces with an orphan commit on every push. Raw holds only the one-time `assemble-20260930` import.
  - GitHub's events still list 32 replaced snapshots (2026-10-05 to 10-25), and all 32 trees are retrievable by SHA. They hold 226 distinct source files, 1.18 GB: 4 meeting versions, 4 committee versions, 3 inventory versions, 3 GPO-evidence versions and 208 YouTube files.
  - The window closes as events age out (90 days or 300 events) and as GitHub garbage-collects.

### 3. Verification and borrowed evidence
- **The listing baseline checks nothing.** The index already holds a `stored_bytes` and `stored_sha256` for all 1,036,256 older bodies; the receipts hold them for only 672,063, and those agree with the index. The baseline compares each listing size with the index. The full re-hash later skips only `sha256_verified = true`.
- **Borrowed PDF opens** *(lead)*. Of the 28,076 PDFs the plan borrows from the old reader alone, only 5,978 carry `content_document_kind`, the only stored proof that a page was read. The other 22,098 (69 GB stored) have no such proof. They might never have opened (a BOM or preamble), be encrypted, or be opened files that abstained, and the stored data cannot tell these apart.
- **The unchecked population differs from the sample.**
  - The 3,061 real unchecked PDFs have a median of 28.5 MB, and 89% are over 10 MB. Checked PDFs have a median of 0.19 MB.
  - The plan's 3,104 adds 43 PDFs whose only check found them broken.
  - Both 117 GB (stored) and 129 GB (content) are right.
  - The sample must be stratified.

### 4. Engine gaps (engine-first: add generically, then file tickets)
- DataFusion 53.1 `decode` handles only base64, base64pad and hex. There is no percent-decoding and no RFC 6266 filename. C8 adds both, with golden vectors from `retention/index/sources.py`.
- C5's `create_bytes_by_key` takes a whole `Vec`. Charge the buffer to the pool. Write a file-backed single PUT only if the largest release file does not fit.

### 5. Measurements that decide
- S1 and M2 need the parsers and the main-content extractor, which D2 builds later. Move the extractor choice into S1.
- M2 needs written ceilings and a decision rule. Its largest receipt line is 187,661,340 bytes, and the receipts expand from 1.08 GB compressed to 13.78 GB.
- The titles heap test runs on a list twice the target's size. The merge check runs at the wrong time.

### 6. Reader gaps
- `detail` lacks the saved file's size, which a reader needs before opening an older gzip.
- `urls` lookup keys cover only final addresses. Add the requested address of every redirect.

### 7. Scheduling and simplification
- The relist checkpoint covers only completed list traversals (phase 2; R6).
- B14 and B16 become capture-scheduler priorities, not separate jobs (Codex S4).
- Sharding waits until F0 or the first release exceeds a limit (Codex S4).
- The ZIP walk gets total-byte and time bounds (S5).
- The switch gets a cut-over order and a per-run budget: 1,298,420 URLs against the old cap of 20,000 (SR-8).
- Provenance writes are batched. `intact` comes straight from the copy's verification record (SR-10).
- The owner actions are listed where each one blocks (SR-11).
- Duplication goes: E1 restates S; the PDF rule appears in four places; B §6 should cite F5 (N1).

## Corrected or rejected
- **Opus 129 GB vs. the plan's 117 GB:** both figures are right, one counting content bytes and the other stored bytes.
- **Opus "meetings stopped on 09-30":** they never flowed into raw at all.
- **Opus "stored values come from the receipts":** true for only 65% of bodies.
- **Codex:** missed the second cookie shape.
- **Opus E4 minor:** no source IDs change from B0, so the cause it names is deleted. This is confirmed.

## Owner decisions needed
1. The overwritten weekly source records: rescue them, and bridge until meeting fetching moves to the new fetcher.
2. The 22,098 borrowed PDF checks with no proof of opening.
3. The Codex S4 simplifications.
4. Whether to apply all confirmed corrections and file engine tickets.

## Owner decisions (2026-10-26) and what was applied
1. **Overwritten source records: rescue now, save weekly.** The rescue is done:
   - 33 snapshots (2026-10-05 to 10-26), 226 distinct files, 1.1 GB;
   - each file matched its git blob SHA at download and was re-hashed by SHA-256 afterwards.
   - The batch is a local content-addressed folder.
   - The plan keeps the weekly job and capture's inventory seeds until B14 (formerly B15). B14's first run imports the batch as one import run.
2. **The 22,098 PDFs checked only by format: listed unchecked until B13.** The legacy selector is now a non-empty `content_document_kind` *(lead)*:
   - 235,016 of 261,125 candidates carry a check: 229,038 from capture and 5,978 from legacy.
   - 26,109 (186 GB stored, about 950 of them HTML) are unchecked.
   - Borrowed checks join in the model (DM §7.3), so a reading again depends only on its body. A copy's record reaches the model with no sniff re-run, which answers both Codex R3's rebuild point and Opus SR-10.
3. **Codex S4, both parts.** B14 (cut-off re-fetches) and B16 (wrapped files) became F2's run order; old B15 is now B14. Sharding waits for A §10.1's growth rule.
4. **Everything else confirmed was applied** in place, and spicy-stack ss-1pg7 was filed (commit 6a83acf).
   - Not applied: Opus's minor suggestion to move E4's cause list and the fixture table out of the plan, a structural move nobody decided on.
   - Not re-derived: Opus's 135,898 shared body keys (not load-bearing).
