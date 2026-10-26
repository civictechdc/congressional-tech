# Review: Implementation Bindings Note (bindings-20261025.md)

Reviewed against congressional-tech `d9730967` (no code change since; `git diff d9730967 HEAD` outside `docs/` is empty) and docspec-rs `d9c6719`. Line numbers below are the Note's (B), unless a file is named.

## Verdict

**Approve with changes.** The references hold, every A §6 component has a row, every knowledge item K1–K34 has a home, and both defects in §8 are real. Fix the two must-fixes before track B binds the fetcher and the body store. Fix each should-fix before the track that uses its row.

| Score | /100 |
|---|---|
| References | 93 |
| Verdicts | 80 |
| Coverage | 86 |
| Fitness | 83 |
| **Overall** | **85** |

Counts: 2 must-fix, 11 should-fix, 10 minor.

## Method

- `bind6_refs.py` (in this folder) parsed every backtick span out of the Note. It resolved `ca/`, `ca-tests/`, `ds/` and bare names from the row's context, and printed the cited lines to `bind6_excerpts.txt`. 318 spans: 183 line-ranged references, all resolving to a file with every range inside it; 103 whole-file references, all existing; 8 directories; 5 bare names resolved by context (`house_sites.py`, `gpo.py`, `assemble.py`, `document-review-identities.json`, `main.rs`); the 19 "missing" are schema terms and symbols, not paths.
- I read every cited range against what its row says. Three point at the wrong lines (m1); the rest say what the row says.
- About 30 named functions and classes exist where the Note puts them. Spot counts hold: 13 review forms, 86 reviews, 56 production `stop_after` sites, the 722-line edge tool (159 + 464 + 16 + 83), `bundles.py` 133 lines, the hand-typed `3.2.7`.
- Both §8 defects confirmed. `ca/cli/raw_sync.py:469` calls `download_ranges(archive, urls, fetch=…)` against the signature `(client, url, path, *, size, last_modified, …)` at `streamed_recovery.py:31-40`, which raises `TypeError`. `records.py:483` strips only `HMKP`.

## Must-fix

**M1. §3.1 Fetcher (L51): "keep the per-hop scope check" keeps a check that fails A §7.1 and blocks B16.**
- **Evidence:** The kept check is `allowed_url` (`ca/parsers/archive_links.py:26-63`). It runs at `ca/transport/source_capture.py:44` and on every hop at `:127`.
- It is a hard-coded deny list, not the capture-scope registry A §7.1 requires ("MUST refuse … URLs outside the capture-scope registry").
- It refuses `api.congress.gov` and `api.govinfo.gov` (`archive_links.py:45-55`).
- The Note's next rows route the Congress.gov committee and meeting fetches through this fetcher (L55; A §8.5; P B16). As written, B16 fails at its first request, and D4–D5 wait on it.
- **Fix:** in the work cell, replace "keep the per-hop scope check" with "the per-hop scope check reads the capture-scope registry (today a hard-coded list that refuses `api.congress.gov` and `api.govinfo.gov`, `archive_links.py:45-55`)". Leave pacing, fallback and JSON link discovery as they are.

**M2. §3.1 Body store (L56): the interface drops the suffix, MD5 and size that locked receipts must record.**
- **Evidence:** The row specifies `put(key, file, media)` returning only `stored` or `unchanged`.
- A §7.1 records `unchanged` with suffix `.gz` after the older-copy HEAD, and with suffix `''` after a 412. DM §5.2 requires `stored_suffix` on every entry, and `stored_md5` and `stored_bytes` on the line that stored the body. Invariants 2, 3 and 10 read them, and DM §7.5 `suffix(body)` picks the physical key from them.
- The row's suite, the refusal matrix, tests only refusals, so nothing catches a receipt writer that guesses the suffix. Over half of attempts find an existing body, and every older body is `.gz`. A wrong suffix lands in receipts that lock after B0 and cannot be corrected.
- A §7.1 step 1 is also missing: upload nothing for a body already in the run's own set (today `body_info`, `raw_archive.py:376`).
- **Fix:** rewrite the clause as "`put(key, file, media)` returning outcome, suffix, MD5 and size: nothing for a body already in the run's set; `unchanged`/`.gz` after the older-copy HEAD; `stored`/`''` on a create-only PUT with `If-None-Match: *` and Content-MD5; a 412 is `unchanged`/`''` with no download". Change the suite to "The refusal matrix; the three write outcomes and their suffixes".

## Should-fix

**S1. §3.2 Parsers: JSON (L76) is "Build, nothing fits", but a generic JSON link reader exists, and the row omits links.**
- **Evidence:** A §8.3 reads JSON "with each page's links as written".
- `_json_links` (`archive_links.py:107-196`) reads native document slots and literal file URLs in any JSON. The Note keeps it in the fetcher (L51), so two JSON link readers would exist, which breaks binding rule 1.
- §4 homes K9's Congress.gov JSON discovery in "the fetcher" only. A document listed only in API JSON then reaches `url_state`'s queue (DM §7.7, which reads page links) only if that run reached it. The inventory's home for K9 is the JSON reading.
- **Fix:** row → "Build, seeded | `_json_links` (`archive_links.py:107-196`), shared with the fetcher; the Congress.gov models for the committee and meeting part | Facts, links as written and fingerprint for every JSON body". In §4 K9, change "(the fetcher)" to "(the JSON parser, shared with the fetcher)".

**S2. §3.2 Parsers: fingerprint (L77): `iter_zip_members` cannot fingerprint the archives that reach this parser.**
- **Evidence:** It takes the whole archive as `bytes` (`archive_members.py:166`).
- It raises `archive_size_limit` above the limit (`:182-183`), and it refuses a member over `max_member_bytes` without hashing it (`:200-205`).
- An archive goes unexpanded because a limit refused it, so this parser would give `error` for exactly the bodies DM §6.2 says to fingerprint "read from the archive" (up to 1,400 ZIPs).
- **Fix:** add to the work "for an unexpanded archive, a hash-only member walk over the file with `zipfile`, with no member limits and nothing held in memory".

**S3. §3.1 Archive expander (L60): ODF detection depends on the media type the target forbids.**
- **Evidence:** A §7.2 keeps Open XML and ODF whole. `is_office_zip` detects only `[Content_Types].xml` (`archive_members.py:148-163`).
- ODF is recognised only by URL suffix or server media type (`raw_archive.py:130-136`). The sniff row drops media-type fallbacks, and DM §5.2 forbids classifying by media type.
- Separately, `_ArchiveView` and `_directory_preflight` work on whole-archive bytes, so "from the spooled file" means reworking them, which the row does not say.
- **Fix:** add "Office packages detected by content only: `[Content_Types].xml`, or a `mimetype` member naming an OpenDocument type, not suffix or media type (`raw_archive.py:130-136`); the preflight and the zip view read the spooled file".

**S4. §3.2 Committee and meeting parsers (L80) cite the wrong House code.**
- **Evidence:** `house_evidence.py:50-116` and `house_documents.py:95-138` read document groups and witness documents. They feed `readings.links` and `group_path`.
- `meeting_records` needs title, date, type and committees. Those come from `HouseMeetingDetailsXML` (`ca/models/house.py:225-240`) and `parse_house_meeting` (`ca/parsers/house_xml.py`).
- **Fix:** replace the two citations with `ca/models/house.py` (`HouseMeetingDetailsXML`) and `ca/parsers/house_xml.py` (`parse_house_meeting`).

**S5. §3.1 Fetcher sources: meeting inventories (L54) leaves "(decide `house_sites.py` and `gpo.py`)" open.**
- **Evidence:** `gpo.py` fetches the GovInfo MODS records (`acquisition/gpo.py:13,165`). Their event IDs are `named_meetings` (DM §6.2, §7.5 `file_meetings`, the S2 MODS fixture).
- It also puts the API key in the query on every page (inventory K1, `gpo.py:302-304`). A §7.2 requires a header, or a key added at fetch time from configuration.
- **Fix:** decide it in the row before B16: "`gpo.py` moves, with its key in a header (its MODS records give `named_meetings`)". Then state whether `house_sites.py` moves, or stays with the explorer with its discovery rules seeding the capture-scope registry (K9, K10).

**S6. §3.1 Review recorder (L62): the named seed holds no verdicts.**
- **Evidence:** `document-review-identities.json` has 86 rows of `body_key`, `document_id`, `source_ids` and `index`, but no kinds.
- The kinds are in `reviews.json` inside the release asset `document-reviews.tar.gz` (release `document-reviews-fc5d361e-v1`). The pin is `apps/site/document-review-publication.json` (`sha256`, `review_sha256`), and the fetch is `apps/site/scripts/stage-document-reviews.py`. §6 deletes both.
- **Fix:** "the 86 published assistant reviews: kinds from `reviews.json` in the release asset `document-review-publication.json` pins; body keys from `document-review-identities.json`".

**S7. Coverage: release retention, the orphan report and the full re-hash have no row.**
- **Evidence:** A §10.3.7 and §12 (maintenance: raw check, then release retention, then orphan report), A §8.7 (orphans) and A §7.4 (full re-hash). P B9 and B10 put them with the raw verifier.
- No row binds them, and no release-retention code exists in `viewer_publication`.
- **Fix:** Raw verifier work (L64) → "The weekly LIST join and the 25-body sample; a re-hash of a body with no creating line; the orphan report; release retention from the pointer (A §10.3.7); the one-time full re-hash (B10)".

**S8. §3.1 Recovery importer (L61) and §6 miss the `accepted.json` reconciliation.**
- **Evidence:** P B7 starts by reconciling `accepted.json` into provenance `recoveries` records.
- Today `corpus_recovery/mappings.py` writes `viewer-publications/recoveries/accepted.json` with `If-Match` (`mappings.py:14,44-80`).
- Its `kind` is a file type (`viewer_publication/filename_recoveries.py:11`), not DM §5.3's display kind (inventory CM20).
- Neither the reconciliation nor `mappings.py` appears in B.
- **Fix:** add to the work "reconcile `accepted.json` into provenance `recoveries` once (its `kind` is a file type, `filename_recoveries.py:11`)". Add `mappings.py` to the row's not-bound list and to §6's corpus_recovery row.

**S9. §3.4 Reader (L103): the verdict overstates the fit, and the work list never names the contract's core.**
- **Evidence:** Today's reader decodes rows into objects with `parquetReadObjects` (`catalog-v6.ts:12,188`), and the row replaces that file.
- A §11.1 and §11.4 require: `list` decoded column by column into arrays and dictionary codes within a heap budget; `detail` read by offset index; `links` looked up by column index; shards; and both the current and previous `schema_version`. "New routes" names none of these.
- The kept files are about 450 lines of plumbing, while the 680-line reading core goes, so by the Note's own definitions the verdict is Build, seeded.
- **Fix:** verdict → "Build, seeded". Work → "`list` decoded column by column within the heap budget; `detail` by offset index, `links` by column index; shards; current and previous `schema_version`; release-ID identity; the 404 reload; a bytes variant of `withVerifiedJson`; replaces `catalog-v6.ts` and the v6 paths in `worker.ts`".

**S10. §3.3 C4 (L90): "Adapt" carries the lifecycle topology for 44 reusable lines.**
- **Evidence:** Everything except `DisjointSet` (`topology.rs:31-74`) changes: input, keys, ID computation, edge policy and the cap.
- **Fix:** "Build, seeded | `DisjointSet` (`topology.rs:31-74`) | dense `u32` IDs and the node-cap refusal over a plan's edges; no `document_id` or edge choice in the engine". `petgraph::unionfind::UnionFind<u32>` (petgraph 0.8.3 in the lockfile) is the maintained equivalent if it is made a direct dependency.

**S11. §3.4 Canary and contract test (L105) lacks the 404 check.**
- **Evidence:** A §15 item 6 requires both the canary and the contract test to check that a 404 makes the reader re-read the pointer. `verify-live-publication.mjs` has no 404 path.
- **Fix:** add "the 404-reload check (A §15, item 6)".

## Minor

- **m1. Three cited ranges point at the wrong lines.**
  - `capture_inspection.py:89-99` (L74 and L123) → `:95-99`; lines 89–94 are the image check.
  - `prepare_corpus_recovery_source_records.py:129,167` (L61) → `:129,168`; line 168 is `acquisition=row`.
  - `topology.rs:31-280` "45-line union-find" (L90) → `:31-74`.
- **m2. Engine paths lack `ds/`.** `engine.rs:84-85`, `test_hooks.rs`, `topology.rs`, `connected_components.rs`, `main.rs` and `error.rs` (L86, L90, L92) need the prefix. `main.rs` also names `packages/source-fetch/main.rs` in congressional-tech.
- **m3. Fetcher (L51) retry wording.** "retry on the six outcomes" literally includes `stored`. Change it to "record the six outcomes of DM §5.2; retry only `retry_later`, `size_limit` and `request_failed`".
- **m4. Fetcher (L51) keeps a resume journal.** It keeps `download_ranges` with its `.ranges.json` journal (`streamed_recovery.py:47-57,113-117`) and `If-Unmodified-Since` (`:83`). A §12 has no journals, and runners are ephemeral. Change it to "`download_ranges` without its journal".
- **m5. Fetcher redirect limit is off by one.** The loop is `range(6)` (`source_capture.py:126`), so it follows at most 5 redirects; A §7.1 says up to six. Add it to the work list.
- **m6. PDF copier (L65) binds a deleted method.** It binds `put_pdf_file`, which L56 deletes, and B13 runs after B3. Change it to "a create-only PUT through the body store".
- **m7. Canary (L105) cites a flag §6 deletes.** "`--verify-publication`'s Chromium checks" is a flag in `scripts/publication/pipeline_status.py:294`, which §6 deletes. The Chromium checks are `browserRuntimeProbe`, which the row already lists. Delete the phrase.
- **m8. §6 Raw index (L161) breaks a news_lake fallback.** It deletes the Python merge `specs.py:476-692`, which news_lake (kept, §7) reaches through `DocSpecClient.update_table`'s fallback (`docspec_client/client.py:735-745`). Name that fallback in the same cut.
- **m9. §5 (L151) misdescribes the facades.** They are not empty: they are the unused re-export packages `ca/retention/{catalog,raw,review}/__init__.py` (48, 34 and 30 lines). Name them that way.
- **m10. Two raw-writer gaps.**
  - The raw verifier's LIST-to-captures join (about 1M keys) is a data join, so by principle 5 it belongs in engine SQL; Python only lists.
  - The receipt writer names no source for `writer {job, commit, lockfile_digest}` (DM §5.2, invariant 3). Use the `release_identity.locked_runtime` helper that L61 already cites.

## Checked and sound

- **Coverage of A §6:** all 18 components have a row (HTML and XML share one).
- **Knowledge items:** K1–K34 all appear in §4. The rows the code supports most strongly are HTML and XML (Build, seeded, with the reason the explorer parsers stay), version digests (one helper), engine pin check (one pin file, PATH fallback at `binary.py:43`), C3, C8 and origin rules.
- **Over-engineering:** the Note already declines most inherited machinery (`bundles.separate`, `RecoveryGuard`, `checked_put`, the edge tool, the in-memory reservation). Beyond S10 and m4, nothing carried forward lacks a reason.
- **§6:** the delete list removes nothing a kept row needs, except the m8 fallback and the review files S6 points at. Those go only "after the 86 reviews carry over", and S6 fixes where their verdicts come from.
