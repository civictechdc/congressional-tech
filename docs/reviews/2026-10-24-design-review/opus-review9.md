# Review 9: implementation plan (P) and bindings (B)

Reviewed cold: P (`plans/simplification-plan-20261024.md`) and B (`plans/bindings-20261025.md`), with A and DM where they mislead the plan. Code at congressional-tech `d4a18af2` (its code tree equals B's `d9730967`) and docspec-rs `d9c6719`.

## Bottom line

- **Not ready to execute.** The strategy is sound: lock first, borrow per-item results, switch then delete, one implementation per component. B's code citations hold up well.
- **Six must-revise items:**
  - B0's cleanup misses half the cookies, and its check cannot see them.
  - Phase 1's capture switch depends on phase 2.
  - The dependency table and the raw-verifier steps contradict the phase split.
  - S1 and M2 need the parsers and extractor that D2 builds later.
  - The engine lacks the functions the shared filename SQL needs.
  - The lock's effect on create-only writes is unmeasured, yet locking is step 1.
- **Everything below can be fixed in one editing pass.** Each fix rewrites the step it changes.

Tags: **(meas.)** measured by me; **(sub.)** from the submission; **(est.)** my estimate.

## 1. Findings

### Must-revise

**MR-1. B0 misses most recorded cookies, and its done-when only re-checks the fields it already listed.**
*Location:* P §6.2 B0 ("The fields", run step 2, "Done when"); DM §5.2, "The one-time cleanup".
*Failure (meas., mirror of all 2,289 receipts, 2,596,054 lines; field-agnostic JSON walk):*
- Set-Cookie is recorded in two shapes.
  - The plan's 534,733 is exactly the keyed form (`response_headers.set-cookie` plus two rare objects).
  - A further **603,497** entries are `{name: "set-cookie", value: …}` items: `response_header_items[]` (587,446), the provider's `provider_response.httpResponseHeaders[]` (16,037) and `source.headers[]` (14). That is 32 JSON paths in all.
  - Today's writers produce both shapes (`transport/http.py:117`, `transport/source_capture.py:108-110`, `source-fetch/main.rs:173`).
  - A rewriter that removes `set-cookie` keys passes B0's re-scan ("in the listed fields") and leaves 603,497 cookies to be locked in public permanently.
- Local paths appear at **3,510** normalized JSON paths (1,541,926 values on 660,299 lines). Another 3,037 lines hold paths as key names.
  - **10** lines embed a path inside a longer string (`movie=/Users/…/sample.ts`, an error message, a traceback). A "value looks like a path" test misses these.
  - No owner can meaningfully confirm a 3,510-entry field list.
- Already clean today (meas.):
  - No credential parameter in any URL-looking string; only the 3,944,944 YouTube `key=` constants the registry exempts.
  - Cutting path key names causes no collision inside an object.
  - No `pointer` passes through a path key.

*Fix (rewrite B0 "The fields" and "Done when"):*
> **What is cut:** every Set-Cookie value in either shape (a keyed header object or a `{name, value}` header item), anywhere in a line, and every absolute local path, as a value, a key name or a substring, cut to its last segment. The read-only scan reports each by JSON path with counts and examples; the owner confirms the two patterns and that report.
> **Done when:** immediately before the owner locks `receipts/`, a field-agnostic re-scan applies the same patterns to every string and key of every receipt, including those capture wrote after the cleanup, and finds nothing. Capture pauses from that re-scan until the lock.

In DM §5.2, rewrite bullet 2 as "cuts absolute local paths to their last segment wherever they occur in a value or key name, never in a key a `pointer` passes through".

**MR-2. Phase 1's capture switch depends on phase 2.**
*Location:* P §6.6 F2; P §4 phase 2 and B15; DM §7.7 `next_attempt_at`.
*Failure:*
- **Discovery.** Today's daily capture is seeded from the weekly meeting inventories.
  - `capture-raw-sources.yml:326-334` passes `pipeline-data/congress_meetings.jsonl.gz`, `gpo-evidence.jsonl.gz` and `meeting-inventory/{house,house-sites,senate}.json.gz` as `--seed`. `acquisition/raw_sync.py:134` queues their links.
  - F2 builds the queue from `url_state` alone and names no seed. B15, which moves the inventories into the fetcher, is phase 2.
  - So after the phase-1 switch, a new hearing reaches capture only if a re-fetched listing page links to it.
  - Committees remove documents (`removed_on`), so anything posted and removed in that gap is never captured.
- **Bands.** DM §7.7 bands a family by "the age at `last_attempt` of the URL's earliest meeting". A meeting's date comes only from `meeting_records` (D4, phase 2), so phase 1 has no rule for any banded family.
- **A gap in raw already exists.**
  - Congress.gov meeting records go to the `pipeline-data` git branch (`update-data.yml:102`), not to raw.
  - The mirror's last `congress/meetings` receipt is dated 2026-09-30 (meas.).
  - Nothing in B15 imports the versions written since.

*Fix (rewrite F2, B15 and DM §7.7):*
> **F2.** Capture reads `url_state` from the live release, including its queue, stops reading the raw index and drops replay; until B15 lands it also takes today's inventory files as seeds, which `update-data.yml` keeps producing.
> **B15 (phase 2).** Meeting fetches through the fetcher …; its first run imports the `pipeline-data` meeting records written since 2026-09-30 as one import run.
> **DM §7.7.** For a banded family, the band is the age at `last_attempt` of the URL's earliest meeting date, else of the date in its docs.house.gov meeting URL, else the family's shortest band.

If the owner prefers no bridge, the alternative is to move B15's fetching (it needs only B2) into phase 1, leaving D4 and the relations in phase 2.

**MR-3. The dependency table and the raw-verifier steps contradict the phase split.**
*Location:* P §4 track table; P §6.2 B9, B10 and the B done-when; A §7.4.
*Failure:*
- The table has "D … B13 for D2" and "F … A, E, B13". But B13 is phase 2, and §2 says no PDF is read whole in phase 1. Read literally, the switch waits for a 403 GB copy job. F also omits B, although capture at the switch runs on B2–B6.
- B9 says both "first run after B10" (phase 2) and "joins to the old capture index until D1 exists" (phase 1); both cannot hold. As written, phase 1 has no weekly raw check, during exactly the period when B0 rewrites receipts and old and new writers run.
- B's done-when needs "a listing baseline at least" for every older body, but no step writes one.
- A §7.4 says the full re-hash "runs once before the first raw check", and the raw check re-hashes "a body with neither" record. So moving B9 into phase 1 without a baseline would trigger the 0.7 TB re-hash the owner deferred.

*Fix:*
- **Table:**
  - D: "C; B2 for D1's line shapes".
  - F: "A, B2–B8, E".
  - Delete "B13 for D2".
  - Add a row: B13 depends on "B1, B3 (phase 2)".
- **B9:**
  > Raw verifier in the maintenance job. Its first run records the listing baseline (DM §5.3), checking each listed size against the older lines' `stored_bytes` (SR-1); it then runs weekly, joining to the old capture index until D1 exists.
- **B10:** delete its last sentence.
- **A §7.4:**
  > The full re-hash runs once after B13, skipping keys a whole read verified; until then a listing baseline records each older body's size and ETag, so the raw check re-hashes nothing.

**MR-4. S1 and M2 need the parsers and the extractor that D2 builds after track C.**
*Location:* P §5.2 ("links parsed from a sample of pages"); §5.3 (real slices including "the pages saved twice in one fetch" and "the short-page sample"); §6.4 D2 (extractor "chosen by measurement"); the §8 extractor row.
*Failure:*
- S1's real-slice run needs page readings: titles, `text_head`, `group_path` and main-content fingerprints. M2 needs parsed links. Both come before track C.
- D2, the only step that writes those parsers and picks the extractor, comes after track C.
- An executor would have to invent a throwaway parser and extractor. S1's row "equal main-content fingerprints" could not be checked until after C, which defeats S1's purpose ("before any further change to the rules").

*Fix (rewrite S1's lead bullet, D2 item 2 and the §8 row):*
> **S1** … writes the sniff, html, xml and json parsers (the D2 code, not yet bound to the lake) and picks the main-content extractor on the ~2,250 pages saved twice in one fetch, recording its time per page; S1's slices and M2's links run on them.
> **D2.** The parsers S1 wrote, appending through the engine: first `sniff` …
> **§8:** "Which maintained extractor gives stable main content | S1".

**MR-5. The engine lacks the functions the shared effective-filename SQL needs.**
*Location:* P §6.3 C8; B §3.3 C8; DM §7.4 (effective filename and decoding) and DM §6.3 (work list).
*Failure:*
- DM §7.4 requires percent-decoding "once as strict UTF-8, `+` kept literal, an invalid sequence stays encoded" and the RFC 6266 `filename*` name. Both must be in "one SQL definition that the filename producer and the model share".
- DataFusion 53.1's `decode()` supports only base64 and hex (`datafusion-functions/src/encoding/inner.rs:326-337`). docspec-rs `src/` has no percent-decoding or Content-Disposition function.
- C8 adds only WHATWG resolution, RFC 3986 normalization and `json_array`.
- So D3's work list and every `source_id` cannot be computed in engine SQL. Doing it in Python would break "one SQL definition" and the engine-first rule.

*Fix (rewrite the C8 row; B §3.3 C8 gains the same bullet):*
> **C8: URL, filename and JSON functions** (ss-7qz3, ss-e53d): WHATWG resolution, RFC 3986 normalization, strict-UTF-8 percent-decoding that keeps invalid escapes, the RFC 6266 download name (`filename*` first) and `json_array` | the WHATWG suite; golden vectors from today's `url_filename` and `disposition_filename` (`ca/retention/index/sources.py:30,86,119-145`) and fetcher URL handling; `json_array` against `json.dumps`; M2's `url_key` timing.

**MR-6. Step 1 locks `bodies/` without measuring how a locked key answers a create-only PUT.**
*Location:* P §4 item 1; B1; A §7.1, write step 3.
*Failure:*
- Both writers treat only a 412 as "already stored":
  - the old capture: `R2Store.put` (`retention/r2.py:385`), `put_file` (`:439`) and `AsyncBodies.put`;
  - the target body store: A §7.1 says "A 412 means the body exists".
- If a locked key answers `If-None-Match: *` with any other status, two things break:
  - The old capture, which runs until the switch, raises on its first unchanged body every day from the lock onward. Nothing new is captured until someone notices.
  - A §7.1's contract is wrong.
- Nothing measures this. Ticket ct-1l1h only reads the rules back, and B3's refusal matrix runs later, on an unlocked scratch bucket.

*Fix (rewrite §4 item 1):*
> On a scratch bucket with the same lock rule, record the status of a create-only PUT to an existing key, an unconditional PUT, a DELETE and a multipart create (about 10 minutes); if the first is not 412, B3 and A §7.1 change before any lock. Then the owner locks `bodies/` and `provenance/` (B1); then the old writers are patched and B0 runs; then `receipts/` is locked.

### Should-revise

**SR-1. The listing baseline checks nothing, although every older body's stored size and SHA-256 are already recorded.** *(P §2 "deferred"; B10; A §7.4.)*
- *Failure:*
  - A baseline taken from a LIST and later compared with a LIST is a digest supplied by the thing being checked. It sees only later changes, which the lock already prevents.
  - In the pinned index, all **1,036,256** older bodies carry exactly one `stored_sha256` and one `stored_bytes`; none equals the content hash (meas.). These come from the receipts.
  - On a 412 the old writer computes them from the stored object itself (`raw_archive.py:236`). `verify-capture-run.py:227` checks each run's bodies against them.
  - DM §6.1 keeps `stored_bytes`, but the plan never compares against it.
- *Fix:* B9's first run compares each listed size with `stored_bytes` before recording the baseline (already folded into MR-3). In A §7.4, rewrite "because no older line records an MD5" as "because older lines record the stored bytes' SHA-256 and size, not their MD5". No new column is needed.

**SR-2. The unchecked PDFs are a different population, and the plan's sample cannot see them.** *(P §2 first bullet; §8 "Borrowed PDF checks" row; DM §6.1 `intact` and §6.2 sniff; B13.)*
- *Failure (meas.; pinned index and old readings via duckdb, cross-checked against the receipts in Python):*
  - The plan's figures reproduce only if "final-content entry" means the line's final response:
    - 228,969 PDFs are capture-checked; legacy opens add 28,076.
    - 198,612 carry both checks (the plan says 198,679).
    - 4,011 are unchecked, but 950 of those are HTML, leaving **3,061 real PDF candidates totalling 129 GB** (the plan says 3,104 and 117 GB).
    - 15,475 rest on 2026-10-01 lines alone by the index, exactly matching the plan (15,507 counted from the receipts).
  - Read as "any entry with a `saved` outcome", DM §6.1's wording gives 259,748 checked and only 1,308 unchecked, and legacy opens then add nothing. So the wording is load-bearing.
  - The populations differ:

    | | Count | Median size | Over 10 MB |
    |---|---|---|---|
    | Checked PDFs | 257,045 | 0.19 MB | 1.6% |
    | Unchecked PDFs | 3,061 | over 22 MB | 89% |

    Of the unchecked, 2,379 were refused for size by the old reader and 396 are over 64 MiB.
  - A 1,000-PDF sample drawn from borrowed checks says nothing about this group, yet §8 claims it decides "how many unchecked PDFs to expect broken".
- *Fix:*
  - In DM §6.1, write "the entry for its line's final response" in place of "its line's final-content entry".
  - Rewrite the §8 row and place it in D2's sniff item:
    > Borrowed checks agree with a fresh read, and how many unchecked PDFs are broken | a whole read in phase 1 of 1,000 borrowed-check PDFs and 100 unchecked ones (about 3 GB, est.), each also checked against its key | whether the borrowed basis stands; the owner revisits the unchecked listing if more than a few of the 100 are broken.
  - State the counts once, in DM §6.2, with the committed SQL; P §2 and B13 cite it.
  - This keeps the owner's decision and measures the reader harm it carries.

**SR-3. Until the switch, the old capture decides body existence by index lookup.** *(P B5 and B12; B §3.1 body store.)*
- *Failure:*
  - `Archive.body_info = _BodyLookup(self.selected)` (`raw_archive.py:660`) is backed by the raw index, and `put_body` skips the upload for any digest the index holds (`:376`).
  - An index row without its object makes daily capture fetch a body and then drop it. That is the kind of row ct-63hg fears from the local runs of Oct 22–24 against the production index.
  - B5's rule covers only new components. B12 repairs `stored_sha256` values, which no upload decision reads.
- *Fix (rewrite B12):*
  > Owed while the old capture path runs: one LIST of `bodies/` joined to the old index confirms every digest it holds has its object, since the old capture skips uploads for indexed digests; rows that fail are repaired, and wrong `stored_sha256` rows are repaired in place (owner decision 7). These matter only until the switch.

**SR-4. B0's mechanics: rewrite only what changes, prove the backup first, and compare values rather than bytes.** *(P B0 "The input" and "The run"; DM §5.2 bullet 3.)*
- *Failure (meas.):*
  - Only **886 of 2,289** receipts (813 MB) hold anything to cut. Yet step 1 rewrites every receipt, including the 1,403 (270 MB) that hold nothing.
  - **228** lines that must be rewritten do not survive `json.loads` then `json.dumps` byte for byte: they escape non-ASCII as `‑`. So DM's rule that every other value and key stays "byte-identical" fails unless the rewriter splices bytes, and a byte-wise step-2 check would halt B0.
  - The backup is only checked for missing keys, never for content equal to the live original.
- *Fix (rewrite the run):*
  > For each receipt: if the scan finds nothing to cut, record that and write nothing; else (1) confirm the backup copy has the live object's size and MD5, copying it if not; (2) write the cleaned bytes with `If-Match` and `Content-MD5`; (3) re-read and check that each line parses to the original minus exactly the cut items, with uncut lines keeping their bytes, …
  
  In DM §5.2, change "byte-identical" to "unchanged (a rewritten line may re-escape characters)".

**SR-5. Locking `provenance/` freezes whatever is there now, and B7/B8 then write permanent records before anything validates them.** *(P §4 item 1, B7, B8; DM §5.3.)*
- *Failure:*
  - `provenance/recoveries/accepted-00922c1e….json` (ct-ja0f) is a whole copy of `accepted.json` in its own schema; its `kind` is a file type (`filename_recoveries.py:11,26`).
  - It sits under the `recoveries` kind, which DM §5.3 defines as `<ts>.jsonl` decision records that the model reads and the publish pins. Once locked, it can never move.
  - B7's 12k+ recoveries and B8's 86 overrides go into the locked prefix before E4's parity reads them, so one bug becomes thousands of superseding records.
- *Fix:*
  - §4 item 1: "list `provenance/` before the lock; DM §5.3 names each object there that is not a record, and the model reads only `<kind>/<ts>.jsonl`".
  - B7 and B8: "write their records to a scratch prefix that E reads during parity; they move under `provenance/` once E4 passes".

**SR-6. Phase 2 is not purely additive.** *(P §4, phase 2 lead.)*
- *Failure:*
  - B13 can turn an unchecked PDF into `damaged`. That removes it from the list and its link key from `links`, since a body that is not real gets no key (DM §8.2), so phase-1 links to it open the not-found notice.
  - S2's widening and a fingerprint parser can split rendition groups.
- *Fix:*
  > Phase 2 adds files and facts; three items can also change the document core: B13 (unchecked PDFs found broken leave the list, and their links open the not-found notice), S2's widening and a fingerprint parser (editions can split).

**SR-7. M1 and M2 cannot decide as written.** *(P §4 item 2, §5.1, §5.2, §8 link row.)*
- *Failure:*
  - M1 decides on a ten-year full-scan time, but its tests produce file counts. Nothing turns a projected count into a scan time, and that time depends on scan concurrency, which is 1 today (`ds/storage/schema.rs:101`).
  - M1's ten Basin maintenance runs are bound by wall-clock time, yet M1 is queued behind the lock and B0, which both wait on the owner. M1, M2 and S1 touch no raw data.
  - M2 sizes the link join from 4.2M links estimated "from 80 pages". With heavy-tailed link counts, an 80-page mean is uncertain by roughly a factor of two (est.). §8 settles it only at D2, after track C is built on M2's verdict.
  - M2 states no decision thresholds, against §3's rule that the decision rule is recorded first.
- *Fix:*
  - §4 item 2: "M1, M2 and S1, beside item 1".
  - M1 test 2 ends: "…then time a full scan of a scratch table with the projected ten-year file and manifest counts through the static provider at the runner's scan concurrency".
  - M2 inputs: "links parsed from a stratified sample of at least 2,000 pages", plus:
    > Decides by: peak RSS within the pool limit set for the 16 GB runner; named steps win if they cut peak memory or time by a fifth.
  - §8 link row: "Settled by M2's sample; D2 confirms".

**SR-8. The switch has no cut-over order and no per-run budget.** *(P F2 and F done-when; the B done-when.)*
- *Failure:*
  - B2–B6 are built in phase 1, but nothing says when they first write production raw. So "one capture run's stored lines carry MD5s" can only be met on an unnamed run.
  - At the switch, every saved URL becomes due at `last_attempt` plus its interval. Today's state holds 1,298,420 URLs, of which 23,897 are pending and 444,989 are saved with no next attempt (meas.).
  - The old capture caps a run at 20,000 URLs (`capture-raw-sources.yml:340`); F2 names no cap and no order.
- *Fix:*
  - F2 gains:
    > …with a per-run limit and an order (queue first, then the oldest `next_attempt_at`), sized from the due rows of the first engine-built `url_state`.
  - The F done-when's first bullet:
    > the cut-over ran in order: old capture disabled; final ingest and publish; flip; the new capture's first run on the target writers, whose `stored` lines carry MD5s matching their ETags.
  - Delete the duplicate bullet from the B done-when.

**SR-9. Two parts of phase 1's scope are left implicit: C4 and the chamber facet.** *(P §6.3 C4; §4 "the memory work of ss-6jg6"; DM §7.5 `chambers`.)*
- *Failure:*
  - C4 *is* ss-6jg6, and phase 2 takes "its memory work", so phase 1's part of C4 is undefined.
  - The true-heap reservation is what keeps a 4M-node graph from silently exceeding the pool: today's maps cost about 712 B a row against the third the pool reserves (`topology.rs:81-89`; sub.).
  - `chambers` comes from spicy-regs committees and meeting records, both phase 2, so the phase-1 chamber facet is empty without saying so.
- *Fix:*
  - C4 row: "phase 1: input from a plan, the node-cap refusal and a true-heap reservation; phase 2: interned dense IDs".
  - DM §7.5: "chambers := the chambers of its committee_keys, by the system code's first letter (h, s, j), and of its meetings".

**SR-10. Two repeated costs grow with history.** *(DM §5.3; DM §6.2 sniff; B13.)*
- *Failure:*
  - DM §5.3 does not require batching. Written one object per record, the listing baseline (1.04M records), B13 (about 520k) and B10 (about 0.78M) would put about 2.3M objects into `provenance/` permanently (est.).
  - Every publish then pins every provenance key with its ETag (A §10.3.1), and the model reads those records for `suffix(body)`.
  - A copy's intact result reaches the model only "at the next sniff version", so B13 forces about 1.04M re-reads to refresh about 3,100 rows.
- *Fix:*
  - DM §5.3: "`provenance/<kind>/<ts>.jsonl`, append-only; each job writes its records in batched files".
  - DM §7.3: "intact := the `.pdf` copy's verification record, else r[sniff].intact at the pinned sniff version, else …".
  - Drop "at the next sniff version" from DM §6.2.

**SR-11. The owner-action list is incomplete and not placed where each action blocks.** *(P Abstract.)*
- *Failure:* it omits these owner actions:
  - the credentials (B0's rewriter credential, and the capture, publish and maintenance tokens of A §14);
  - the real-device speed runs that the switch checklist needs (A11);
  - the 123 `direct_official_package` lines (§8), which block D1's mode table.
  It also places the six-excerpt review (B7) at no gate.
- *Fix (rewrite the Abstract bullet):*
  > Owner actions: the bucket lock (B1); B0's patterns and report; the credentials (B0's rewriter; capture, publish and maintenance tokens, before F1); the 123 import lines (before D1); six recovery excerpts and facts only derived tables hold (before the switch); real-device speed runs (A11); widening fingerprint candidates (S2).

**SR-12. The merge check runs at the wrong time.** *(P §3, merge check 1.)*
- *Failure:*
  - Listing `receipts/` and `bodies/` before and after a merge compares two listings with no run between them. Raw only changes when a merged writer runs.
  - After the locks, the lock itself refuses what the check looks for.
- *Fix:* "Until `receipts/` is locked, list it before and after the first run of each merged raw-writer change; after that, the weekly raw check replaces this."

**SR-13. The titles decision is measured on a list twice the target's size.** *(P A11; the §8 titles row.)*
- *Failure:* F0 keeps all 1.24M catalog rows, about twice the target `list` (sub.). A heap test on F0 overstates the cost of titles and pushes toward taking them away from readers.
- *Fix:* §8 row: "Settled by A11 on the first engine-built release; F0 sets a provisional budget."

### Minor

- **D done-when:** in phase 1, "every lake table" means `captures`, `readings` and `filename_readings`.
- **C done-when:** "the full export" means M2's export as a CLI job spec (C7). E's model does not exist yet.
- **S1 table, misplaced rows:**
  - "Byte-identical releases" needs C and D, so it belongs to invariant 4's test after E.
  - "Ranges whose entity changed" belongs in B2's fetch contract suite, not in SQL.
- **S2 table:** mark the phase-2 rows (witnesses, meetings, spicy-regs). §4 item 2 asks only for "S2's document fixtures" in phase 1.
- **B13:**
  - Take candidates from phase 1's sniff (`format = 'pdf'` on older `.gz` bodies), not from media type or the old catalog.
  - State that each copy is checked against its key. The adapted code does this (`pdf_backfill.py:118-125`), but it raises on a mismatch, so it should record the mismatch and continue.
- **E4 cause list:** delete "source IDs change where B0 removed a credential parameter". There are none (meas.).
- **Duplication:**
  - The PDF counts appear in P §2, P §8, B13 and DM §6.2; keep one home.
  - B7 and B8 are described in both P and B.
  - E4's 15-bullet cause list and the 50-row fixture table belong in the parity script and the fixture file. Moving them would cut about 1,800 of P's 8,123 words.
- **F0's upload location:** the canary reads "the uploaded candidate over HTTPS". Name the scratch prefix F0 is uploaded to.
- **M1:** also count `metadata.json` files. Today's tables set `write.metadata.delete-after-commit.enabled=false` (`ds/storage.rs:132-141`), and DM §6 does not reset it.
- **Number check:** I count 135,898 body keys shared across old document rows, against P §5.4's 141,762 (meas.). This is not load-bearing.
- **Loose wording in B:** `meetings.py:125-127` maps `joint` to `nochamber` for URL matching. The work item is right; the description "maps NoChamber to joint" is loose.
- **Not checked:** I could not see whether `quarantine/` holds bodies. If it does, B4 should say what happens to them.

## 2. Cost on the smallest runner (4 vCPU, 16 GB)

All runtimes are estimates. Sizes are tagged.

| Step | Reads | Writes | Runtime | Big O / note |
|---|---|---|---|---|
| Lock probe (MR-6) | — | a few scratch objects | ~10 min | O(1) |
| B0 | 1.08 GB compressed / 13.78 GB raw JSON (meas.) | 886 receipts, 813 MB (meas.) + batched records | 5–10 min; my parse and re-dump of all lines took 95 s of CPU | O(receipt bytes) |
| M1 | scratch | ~315 KB/day batches (sub.) | bound by the wall-clock time of ≥10 Basin maintenance runs | start first (SR-7) |
| M2 | 1.08 GB receipts, 1.09 GB catalog pair (meas.), page sample | none | minutes; peak memory is the result | hash joins O(n+m), sorts O(n log n) |
| F0 | 1.09 GB catalog pair (meas.) | release, about 2× the target list (sub.) | minutes | O(n log n) |
| D1 | 1.08 GB (sub., meas.) | ~157 MB (sub.) | ~1–3 min | O(new receipts) daily |
| D2 sniff | ~1.04M range GETs (sub.) | 1.04M rows | 15–30 min at 64 in flight | O(bodies); repeated per sniff version |
| D2 pages | 289,179 bodies, 5 GB (sub.) | ~100 MB per version (sub.) | 30–90 min, bound by the extractor; unmeasured (MR-4) | O(pages) per version |
| D3 | `captures` | ~32 MB (sub.) | 7–18 min (sub.) | O(pairs) |
| Listing baseline | ~1,040 LISTs | ~1.04M records, batched | minutes | O(bodies), once |
| Whole-read samples (SR-2) | ~3 GB | records | minutes | O(sample) |
| Model and export | lake | ~95 MB/day (sub.) | minutes | O(N log N) every publish; accepted |
| Raw check | ~1,300 LISTs (sub.) | report | minutes | O(history) metadata, weekly |
| B13 (phase 2) | ~365 GB (sub.) | 260,175 PUTs, 403 GB (sub.) | 2–6 h, network-bound | O(PDF bytes); permanent, ~$72/yr (sub.) |
| B10 (phase 2) | ~335 GB of non-PDF bodies | ~0.78M records | 1–4 h | O(bytes) |

No path is superlinear. The ones that grow without bound or repeat per item:
- per-publish provenance pins (SR-10a);
- a full sniff version to refresh about 3,100 rows (SR-10b);
- the first capture run's due set (SR-8).

## 3. Numbers re-derived, and what each check could not see

| Claim | My value | Source and tool | Could not see |
|---|---|---|---|
| 534,733 cookies on 242,438 lines; 241,328 of 530,081 lines in the last two weeks (sub.) | Same, keyed form only, plus 603,497 in name/value form (meas.) | mirror; Python walk of every value | receipts after 2026-10-16; cookies not shaped as headers |
| 279,549 absolute `file_references[].original_path` (sub.) | Same, plus 3,509 other paths; 10 embedded (meas.) | mirror | relative local paths; receipts after 2026-10-16 |
| No credential parameters (implied) | None in any URL-looking string (meas.) | mirror | credential names outside my 10-name list |
| One 188 MB line (sub.) | 187,661,340 bytes, `house/meeting-xml/undated` (meas.) | mirror | — |
| 258,021 / 261,125; 3,104 unchecked, 117 GB; 15,475 on 2026-10-01 only (sub.) | 3,061 real unchecked PDFs, 129 GB, with the final-entry reading; 15,475 exactly by the index, 15,507 from the receipts (meas.) | pinned index and readings (duckdb); receipts (Python) | the plan's own SQL, which sits under `docs/reviews/` where I may not look; actual breakage, since I read no body bytes |
| 198,676 agree, 3 disagree (sub.) | 198,612 with both checks (meas.) | same | same |
| Every older body has `stored_sha256` and `stored_bytes` | 1,036,256 of 1,036,256, one value each (meas.) | pinned index | whether the stored objects match (no bucket access) |
| Content-Disposition sources | 0 of 96,773 lines hold it only in the provider list (meas.) | mirror | — |
| Due set at the switch | 1,298,420 URLs; 23,897 pending; 444,989 with no next attempt (meas.) | `state.parquet` | target intervals (the registry is unwritten) |
| B's citations | About 35 spot checks in both repos and the cargo registry, all found; one loose description | sed, grep, crate sources | runtime behavior; R2 lock semantics |

Disclosures:
- One script ran once without `-I`. It only read the mirror; I deleted it and re-ran a self-contained version with `-I`, which gave the same result.
- I did not open `docs/reviews/` or any credential file.
- All scripts are `r9o_*.py` in this directory.

## 4. Grades

| Area | Grade | Why |
|---|---|---|
| Ordering and dependencies | 60 | Coarse order right. Table contradicts the phases; S1 and M2 need D2's outputs; B9 waits on B10; the baseline has no step. |
| Phase split | 56 | Phase-1 capture needs phase-2 seeds and meeting dates; chambers facet empty; C4 scope undefined; phase 2 not additive. |
| Risk front-loading | 62 | Right three measurements, but M1 is queued behind owner waits; the lock probe, the link-count sample, the unchecked stratum and M2's thresholds are missing. |
| Reuse decisions | 72 | Borrowing is sound and the numbers roughly reproduce. Misses `stored_bytes`/`stored_sha256`; the sample cannot see the unchecked population. |
| Executability and acceptance | 60 | Most done-whens are observable, but unnamed runs, no cut-over order, B0's rewrite semantics and owner actions are left to the executor. |
| Cost | 72 | Linear throughout; three costs repeat or grow unbatched; extractor and B13 runtimes unestimated. |
| Raw-data safety | 56 | Good lock order and rewriter isolation, but B0's cookie gap, lock semantics, index-based existence and `provenance/` contents at lock are unaddressed. |
| Bindings | 80 | Citations accurate; good reuse (`put_file`, arrow-json's type-conflict switch, opendal MD5, `os.link`); one engine gap (MR-5); the receipt reader is written twice (M2 and C1). |
| Simplicity | 70 | Delete-first intent and one implementation per component. Counts repeated across documents; fixture and cause tables live in the plan; 1,403 needless rewrites; the M2 reader is throwaway. |
| **Overall** | **63** | |

## 5. Verdict

**Not ready to execute.** These remain:
1. **MR-1:** rewrite B0's patterns and re-scan to be field-agnostic, covering cookies in both shapes and embedded paths.
2. **MR-2:** keep the inventory seeds until B15, give phase 1 a band rule, and import the meeting records kept since 2026-09-30.
3. **MR-3:** fix the dependency table, give the listing baseline a step (B9's first run), and align A §7.4.
4. **MR-4:** move parser writing and the extractor choice into S1.
5. **MR-5:** add percent-decoding and the RFC 6266 name to C8.
6. **MR-6:** probe lock semantics on a scratch bucket before the owner locks.

The should-revise items are single-step rewrites and can land in the same pass. With those done, the plan is executable without inventing policy.
