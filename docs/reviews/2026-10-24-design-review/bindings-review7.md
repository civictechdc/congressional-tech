# Bindings Note, review 7

- **Documents:** commit `40ee51b2` (the snapshot matches it byte for byte).
- **Code:** read only through `git show d9730967:` (congress-tech) and `git show d9c6719:` (docspec-rs). `git diff d9730967 40ee51b2` outside `docs/` is empty.
- **Independent grade:** `bindings-review7-own.md`, written before I opened the lead's opinion or the reconciliation file. This file keeps its findings and adds the status of the review-6 findings and the verdicts on the lead's claims.

## Score: 88/100

| | Review 6 | Review 7 |
|---|---|---|
| References | 93 | 95 |
| Verdicts | 80 | 88 |
| Coverage | 86 | 87 |
| Fitness | 83 | 88 |
| **Overall** | **85** | **88** |

**References.** `bind7_refs.py` resolves every span in the Note against the pinned commits. Of 332 spans:
- 204 line ranges fall inside their files, and 110 file references exist.
- The 14 "missing" spans are non-paths, or review documents that exist at `40ee51b2`.
- The 44 references added this round each say what their row says. Spot-checked in the upstream crates:
  - iceberg 0.10.1 `Transaction::do_commit` reloads the table and re-applies the actions on a stale base (`transaction/mod.rs:218-246`).
  - docspec's `GuardedCatalog::load_table` refuses that (`ds/catalog.rs:1334-1345`).
  - The table reader plans with no filter (`ds/storage/schema.rs:101`, `ds/query.rs:413-420`).
  - opendal 0.57's `checksum_algorithm = "md5"` sends `content-md5` and refuses multipart (`opendal-service-s3 core.rs:869-872,1493-1496`).
- Defects: one short-form reference resolves to the wrong file, two ranges are a line off, and two seed citations point at output files (m1–m3).

**Verdicts.**
- Five rows moved to Build, seeded, all correctly: Fetcher, Archive expander, C1/C6, C4 and Reader.
- JSON parser now lifts `_json_links`.
- C2's guard mechanism is right.
- One row still binds a broken pattern (M1).

**Coverage.** Every A §6 component has a row, and K1–K34 all have homes. The gaps are new requirements from this round (drop with purge, table drops) and two plan steps with no binding.

Counts: 1 must-fix, 3 should-fix, 8 minor.

## Must-fix

**M1. Receipt writer (L59) and Recovery importer (L61): writer identity is bound to a helper that is not a code identity.**
- **What `locked_runtime` actually is** (d9730967 `packages/viewer_publication/src/viewer_publication/release_identity.py:92-107`):
  - It reads `uv.lock` only for seven hard-coded publication packages (`:22`). It hashes their versions together with the Python version, `platform.system()` and `platform.machine()` (`:76-79`), and it raises when the running Python differs from `.python-version`.
  - So it is not DM §5.2's `writer.lockfile_digest` (the SHA-256 of `uv.lock`), and two runner operating systems give two values for one lockfile.
- **What `source_files` actually is** (`:28-73`): a hash over a hand-listed set of paths that contains no `corpus_recovery` code. It cannot refuse uncommitted importer code (plan B6), and it gives no git commit, which DM §5.2 needs as `writer.commit`.
- **Why it matters:** this is inventory lesson 14 (hand-listed fingerprints go stale) bound into the one field written into locked, permanent receipts.
- **My error:** my review-6 note m10 suggested `locked_runtime`. Checking the code this round shows that suggestion was wrong.
- **Fix, L59:** replace "with writer identity from `locked_runtime` (`packages/viewer_publication/src/viewer_publication/release_identity.py`)" with "with writer identity from git `HEAD` (refusing a dirty tree) and the SHA-256 of `uv.lock`".
- **Fix, L61:** replace "code identity from B6 (`packages/viewer_publication/src/viewer_publication/release_identity.py`: `locked_runtime`, `source_files`)" with "code identity as the receipt writer's".

## Should-fix

**S1. Drop with purge, and the maintenance job's table drops, have no binding.**
- **The requirement:** A §8.6, §12 ("table drops") and §13.2 ("drop with purge"), and plan C2 ("M1's commit and drop tests").
- **The code fact:** iceberg-catalog-rest 0.10.1 has `purge_table`, which sends `purgeRequested=true` (`catalog.rs:381-389,879-881`). In docspec-rs it only appears in pass-through wrappers (`ds/catalog.rs:1404-1405`); no job operation calls it.
- **Fix, L88 work:** replace "long-lived table creation with the data model's properties and row-group sizes" with "create with the data model's properties and row-group sizes, and drop through iceberg-rust's `purge_table` (no engine path calls it today)".
- **Fix, L64 work:** add "table drops" after "release retention from the pointer".

**S2. The plan and the Note disagree on two steps.**
- **The patch to today's writers.** Plan §4 track B ("the old writers patched, then B0") and B0's first bullet require patching today's writers first. The Note lists the leaking code (`ca/transport/http.py:92-122`, `source_capture.py:68-70,104-111`, `packages/source-fetch/main.rs:163-176`, `prepare_corpus_recovery_source_records.py:168`) only as facts that break the new receipt writer, so nobody is told to patch them in place.
  - **Fix, L59:** change "Today's code that breaks it:" to "Today's code that breaks it, patched in place before B0:".
- **B17.** Plan B17 fetches about 8,800 wrapped files "ahead of the model's queue", after B2 but before any `html` reading exists. No row says where its URL list comes from.
  - **Fix (prefer deleting work):** in plan B17, change "(after B2)" to "(after D2, from the wrapper pages' `html` readings)". The Note then needs nothing new.

**S3. §4 K1 (L115) seeds the credential registry with a parameter the data model forbids.**
- **The code fact:** the seed is `ca/parsers/archive_links.py:19`, `SECRET_KEYS = {"api_key","apikey","key","token","access_token","authorization"}`.
- **The conflict:** DM §7.1 says "never a bare `key`". Every one of the 3,944,944 credential-like parameters in the receipts is `key` on `www.youtube.com` caption URLs (`measurements/receipt-scan-20261025/val_receipts.json`). B0, run on this seed, would rewrite all of them.
- **Fix:** "K1: `ca/parsers/archive_links.py:19,56-57` without `key` (3,944,944 YouTube caption constants, `val_receipts.json`); `ca/acquisition/committees.py:23-29`".

## Minor

- **m0. L54 does not say what leaving `house_sites.py` out costs.**
  - Its POST calendar discovery cannot become a `url_state` row: energycommerce.house.gov `/api/events` (`ca/parsers/committee_discovery.py:236-237`), read by `calendar_links` (`ca/parsers/committee_pages.py:20-29`).
  - Its docstring says its pages feed "the raw mirror" (`ca/acquisition/house_sites.py:1-7`).
  - **Fix:** append "; event pages only its POST calendar API finds (`ca/parsers/committee_discovery.py:236-237`) are no longer captured".
- **m1. L51's short reference `:126` points at the wrong file.** By the Note's own short-form rule it resolves to `ca/transport/congress.py`, which has 9 lines. **Fix:** write `ca/transport/source_capture.py:126`.
- **m2. Two ranges are a line off.**
  - L60 `ca/retention/raw_storage.py:333` is a bare `try:`. **Fix:** `:332-334` (the `is_office_zip`-only test and the expansion).
  - L56 `ca/retention/raw_archive.py:377-378` misses the re-download. **Fix:** `:377-381` (the re-download is at `:380-381`).
- **m3. L124 and L127 cite measurement outputs, not the seed.**
  - The words, error URLs, challenge markers and wrapper marker are in `measurements/short-pages-20261025/sp_rules.py:7-9,22`. `rules.json` holds rule tallies and `labels_rule.json` holds per-body labels.
  - The quoted "please wait, your file download will begin shortly" appears in no committed file. The rule matches "download will begin shortly" or a "Download File" heading.
  - **Fix:** cite `sp_rules.py:7-9,22` in both rows.
- **m4. L66's count has no committed evidence.** "(85 path and 15 cookie locations in the last two weeks alone)" cannot be reproduced: `val_receipts.json` keeps only the top 15 path fields (`val_receipts.py:71-73`). **Fix:** delete the parenthetical.
- **m5. L51 and §8 (L192) still say to fix the old `streamed-recovery` call.** That call lives in the old CLI, which is not bound, and plan B14 now runs "through the spooled fetcher". **Fix:** delete "fix the `streamed-recovery` call (§8)" and the first row of §8.
- **m6. C1/C6 (L87) does not bind named-step materialization.** A §13.1 and plan M2 rely on it. **Fix:** add "a named step materialized with DataFusion's `DataFrame::cache()`, whose memory M2 measures".
- **m7. L78 (version digests) does not say which files the helper hashes.** Today one helper hand-lists them (`ca/retention/document_evidence.py:47`). **Fix:** add "over the version's package directory and vocabularies, never a hand-listed set".

## Review-6 status

| Review 6 | Status | Where |
|---|---|---|
| M1 scope check | RESOLVED | L51: the registry as an allowlist on every hop of every transport, with the API-host, provider-path and API-client facts |
| M2 store interface | RESOLVED | L56: outcome, suffix, MD5 and size; the run's set; no download on a 412 |
| S1 JSON parser | RESOLVED | L76 (Build, seeded from `_json_links`); L116 (K9 in the JSON parser) |
| S2 fingerprint of unexpanded ZIPs | RESOLVED | L77 |
| S3 ODF detection | RESOLVED | L60 |
| S4 House meeting parsers | RESOLVED | L80 (`HouseMeetingDetailsXML`, `parse_house_meeting`) |
| S5 open decision | RESOLVED | L54 (`gpo.py` moves with its key in a header; `house_sites.py` stays); see m0 |
| S6 review verdicts | RESOLVED | L62 |
| S7 maintenance coverage | RESOLVED | L64; this round's new table-drop requirement is S1 |
| S8 `accepted.json`, `mappings.py` | RESOLVED | L61, L171 |
| S9 Reader | RESOLVED | L103 |
| S10 C4 | RESOLVED | L90 |
| S11 canary 404 check | RESOLVED | L105 |
| m1 ranges | RESOLVED | L74, L123 `:95-99`; L61 `:129,168`; L90 `:31-74` |
| m2 `ds/` prefixes | RESOLVED | L86, L90, L92 |
| m3 retry wording | RESOLVED | L51 |
| m4 range journal | RESOLVED | L51 |
| m5 six redirects | RESOLVED | L51, though the new short reference is wrong (m1) |
| m6 PDF copier through the store | RESOLVED | L65 |
| m7 `--verify-publication` | RESOLVED | L105 |
| m8 news_lake fallback | RESOLVED | L162 |
| m9 facades | RESOLVED | L152 |
| m10 LIST join and writer identity | PARTLY | The engine-SQL join is RESOLVED (L64). The writer identity adopted my `locked_runtime` suggestion, which was wrong (M1) |

## The lead editor's claims

| Claim | Verdict | Evidence |
|---|---|---|
| Grade about 87 | PARTLY | Close to my 88 for the Note, but the score misses M1 and S1–S3, which the lead does not see |
| Raw-data safety 9.5 | PARTLY | The specs earn it (A §7.1 write steps, B0 backup-first, the re-hash before the first check). The Note carries three raw-log risks: M1's permanent identity field, S3's B0 rewrite of 3.9M URLs, and the unbound old-writer patch (S2) |
| Grounded in data 9.5 | PARTLY | Most rules cite numbers. But L124 and L127 cite outputs, the quoted wrapper wording is in no committed file, and plan B0's "more than 40 fields" and L66's "85 path and 15 cookie locations" are not in `val_receipts.json` (top 15 only), which plan §3's committed-evidence rule requires |
| Internal consistency 9; "193 references, 0 problems" | DISAGREE | Contradictions: Note K1 against DM §7.1 (S3); Note L88 and L64 against A §8.6, §12, §13.2 (S1); Note L51 and §8 against plan B14 (m5); plan §4 and B0 against the Note (S2). My check also finds one broken short reference and two off-by-one ranges |
| Executable plan 8.5; M1 and M2 open | AGREE | The order and gates are clear. Add the two plan steps with no binding (S2) and the unbound drop that M1 tests (S1) |
| Simplicity 7 | PARTLY | Over P §3 the 7 is the lead's call. In the Note, simplicity rose: five rows build smaller, and platform primitives replace code (`os.link`, opendal `md5`, `purge_table`, the extraction library). From my lens, 8 |
| Readability and concision 7 | AGREE | Counted: DM 9,929 words; all four documents 27,835. Note cells L51, L56 and L61 run 232, 191 and 183 words |
| Holds back 1: grouping meets real data only at D2 and E4 | AGREE | Plan §5.3 runs S1 as an executable model on fixtures, and M2 groups only sampled links |
| Holds back 2: ceremony in P §3 | PARTLY | Agreed that the W3C framing stays. But the ticket and closure rules answer the owner's own lessons ("closed tickets are not evidence" from the October audit; tickets marked in progress), and `wc -l` per deletion is how "smaller" is shown. Only wording that repeats them is boilerplate |
| Holds back 3: density | AGREE | Same counts as above |
| Nit: A §6 diagram omits bodiless rows | AGREE | A L183, against A §8.2 and DM §6.1 |
| Nit: plan §1 `stored_sha256` | AGREE | True of the old path (plan L29); "the old capture schema" would make it plain |
| Raise 1: run S1 as an executable model and on real data | AGREE | Plan §5.3 already requires the executable model; the real-data slice is the gain |
| Raise 2: cut boilerplate and process rules; one concision pass on DM §7 | PARTLY | Agree on concision. Keep the process rules that carry owner lessons (see Holds back 2) |
| Raise 3: run M1 and M2, then re-grade | AGREE | M1's drop test needs S1's binding first |
| Already checked: no body ETag contains `-` | AGREE | Every body writer at d9730967 makes one `put_object` (`ca/retention/r2.py:434`), and the publication client replaces managed multipart with one PUT (`viewer_publication/client.py:228-241`). No commit ever added `upload_file` to the body-writer files. Twenty-four bodies is a sample, but the first raw check's LIST sees every ETag |

**What the lead missed:**
- **M1:** the receipt writer's identity is bound to `release_identity`, a platform-dependent fingerprint over hand-listed files.
- **S1:** drop with purge and table drops have no binding, although M1 tests drop.
- **S2:** the old-writer patch and B17 have no binding.
- **S3:** the K1 seed would let B0 rewrite every YouTube caption URL.
- **m0–m7:** reference and seed-citation defects, the stale `streamed-recovery` fix, and the unspoken cost of leaving `house_sites.py` out.

All of these sit at the binding layer, which a read of the specifications alone does not show.
