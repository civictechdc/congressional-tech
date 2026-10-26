# CS 300 specification review: Congressional Document Archive (A, DM, P, B)

Reviewer: cold read of the 2026-10-24/25 snapshot. Numbers are tagged **[measured]** (re-derived from the 2026-10-19 snapshot with `spec6_*.py` in this folder), **[doc]** (taken from the documents) or **[est.]**.

## Verdict

**Not yet ready to build the lake and model from; the raw track can start once the plan's ordering gap is closed.** The architecture is coherent and the data model is unusually explicit, but three rules that identity, real-file status and raw permanence depend on cannot be computed as written. Each fix is a one-line rewrite of the rule it changes.

**Score: 74 / 100** — correctness and completeness 68; determinism and failure behavior 74; data model 76; specification craft 80; plan and bindings 78.

Counts: must-fix 3, should-fix 13, minor 14.

## Must-fix

**M1. DM §5.2 `complete` is undefined for a response with no declared length.** The rule says a fetch is complete when "the stored length equals the declared length (Content-Length, or the Content-Range total)". Chunked HTTP/1.1 and HTTP/2 responses, the norm for dynamic pages on congress.gov and docs.house.gov, declare no length, so `complete` is false (or undefined) for them. `good_fetch` (§7.3) requires `complete`, so those pages are never real files, never supply link context, never feed the queue, and their meeting pages give no `file_meetings`. The one definition of completeness is the gate for everything above raw. *Fix (rewrite the cell):* "True when the transport signalled the end of one entity without error: Content-Length matched, the final chunk was read, or the stream ended cleanly; for ranges, each requested with `If-Range` on the first response's strong ETag or Last-Modified and the total equal to the Content-Range total."

**M2. DM §7.4 never defines a capture row's "source URL", and the text implies three different answers.** It is the second input to `source_id` (identity), the PK of `filename_readings`, the base of `copy_urls`, `occurrences.url` and the directory in `same_rendition (b)`. §7.5's directory rule treats "the source URL" and "the container's URL" as different things; §6.3's "`''` for a source file without one (331,985 rows)" **[measured: 331,985, all archive members or bodiless]** implies members have none; §7.10's "`url` is the source URL … the latest attempt at that endpoint" implies it is `context_url`. With `copy_urls` as written, a member's set holds the container's requested URL, so a link to `hearing.zip` resolves to every member (`publisher_links`, recovery attachment) while `linked_from` (§7.10) does not — two semantics for one join. *Fix:* in §7.4 write "source URL := `url` (the final URL) for a top-level row; null for an archive member, whose container is `context_url`", and in §7.2 make `copy_urls` and every link join match on the endpoint `(url_key, member_path)`, null-safe, so a link to an archive matches the archive's own source file only.

**M3. P §4 / B0: `receipts/` is locked while two old writers still record what the cleanup removes.** The plan orders "the receipt part of B2" before B0 and the lock, but B2 is the *new* receipt writer, which is not bound until the switch; the old capture path "keeps writing raw data … and gets raw-safety fixes only" and today records every header, `Set-Cookie` included (B §3.1 Receipt writer row), and the live recovery importer writes local paths in `recovery_evidence.acquisition.body_path` (B §3.1 Recovery importer row; the memory notes say recovery jobs run from the primary checkout). Every such line written after the lock is public and permanent, defeating B0's "Done when: a re-scan finds no cookie … or local path". *Fix (rewrite step 1 of §4):* "patch the old receipt writer and the old importer to the §5.2 header allowlist, URL and path rules (raw-safety fix, B §3.1 rows); then B0; then the lock on `receipts/`; no recovery import runs between B0 and the lock."

## Should-fix

**S1. DM §7.3 record role has no grain.** A §3 calls it "a body's classification", but `'api'` and `'error_response'` read "the capture's URL", so one body fetched at a URL in the error-URL registry and at another gets two roles; `real_files` is per row, invariant 8 is per body. *Fix:* "record_role is evaluated per capture row; a body is a real body when any of its rows is a real file", and invariant 8 reads "a body none of whose rows has role `document`".

**S2. DM §7.4 step 1 and §7.8 Decision match an import row to its recovery decision by different rules** (exact `original_url` string, any decision, vs `url_key` + `body_sha256`, latest by `(decided_at, id)`). A row can get its filename from one decision and its kind from another, or a filename from none. *Fix:* step 1 reads "the `recovered_filename` of the row's recovery decision (§7.8)" and §7.8's match uses the exact `original_url`, so the filename producer (§6.3) still depends on no profile registry.

**S3. The `document_id` formula is not today's, though the decisions say it is kept.** On 3,000 sampled catalog documents **[measured]**: `["bodies", sorted keys]` reproduces 33%, `["sources", sorted member source_ids]` 45%, `["sources", [one source_id]]` 13%, none 8% (mostly two-body documents). `source_id` reproduces 100%. Invariant 9's golden vectors from today's code (P E3) will fail. *Fix:* either state the selector today's code uses (sources unless the body is a verified saved capture, from the sample) or drop "kept" and generate the vectors from the specified formula; say which in DM §7.5.

**S4. List and fold element order is not fixed, so byte-identical export is not enforced by anything named.** §7.5 fixes `meeting_refs`, `meeting_keys`, `measure_keys`, `bioguide_ids`, `alternates`; `document_kind`, `document_family`, `committee_name` (joined, so SQL gives no order), both `fields` folds and `f.*`'s lists are unordered. A §10.2's mechanisms (unique sort keys, batching) cannot order list elements. *Fix:* rewrite the sentence as "every list and fold column is written in a fixed order: structs by their fields, strings bytewise, folds by `(field, value)`, `alternates` in format-preference order."

**S5. Web-page editions multiply documents.** A real HTML page refetched with different visible text at one endpoint is edition-ambiguous: each version is a separate listed document and none takes rendition edges. Today 3,700 HTML URLs hold 2–3 distinct 2xx bodies (3,715 extra) **[measured; old path rarely re-fetched]**; the recheck schedule makes every changing hearing page a growing stack of near-duplicate "documents". The decision "one distinct content" was made for files, not pages. *Fix:* in §7.5, one rule for `format = 'html'` real files at one endpoint (one document per endpoint, newest body saved, older bodies as occurrences), or say explicitly that page versions are listed separately.

**S6. `same_rendition (b)` "otherwise" is ambiguous** (only files in no publisher group, or all files?), the stem comparison's case rule is unstated, and the saved-file order gives no position to formats absent from the format-preference registry (`docx`, `doc`, `text`, `image`, `other`). *Fix:* "(b) for every real source file, also: …", "stems compared bytewise", "unlisted formats after listed, by name".

**S7. Invariant 13 contradicts §7.8 twice.** "Resolves to a listed document or is reported as orphaned" — §7.8 gives every unattached recovery its own document, so none is orphaned. "No recovery body is a link key" — a recovered copy whose bytes were later fetched normally is a real body and a key. *Fix:* "resolves to a listed document; a body that is only a recovery body is not a key."

**S8. Three derivations are missing.** `saved_media_type` (§7.5 columns, read by §11.5) has none; `complete` for older lines is "derived" with no rule beyond the 64 MiB case (62 URLs **[measured]**: 207 URLs hold a 64 MiB body, 62 have nothing larger, matching B14); B13's candidate rule ("every older gzip PDF") names no signal, and older rows carry no sniff — the copier reads every candidate's bytes anyway and can record the sniff. *Fix:* "saved_media_type := a fixed map from the saved file's format, else its capture's `media_type`"; "older lines: complete := not (bytes = 67,108,864 or outcome in (size_limit, request_failed))"; B13 candidates "older bodies whose decompressed first bytes are `%PDF`".

**S9. DM §8.1 "`meeting_keys` … at most 9" is false today**: the maximum distinct meeting keys per catalog document is 270, with 7,675 documents above one **[measured]**; the examples are Senate hub pages linked from dozens of hearing pages. The target's `file_meetings` narrows this to "a publisher_links page that is a meeting page", but "meeting page" is undefined. *Fix:* define it (a page whose address matches the two meeting URL patterns, or a House meeting XML record) and drop the "at most 9".

**S10. `url_state.next_attempt_at` is undefined when `last_attempt` is null**, and 2,717,129 of 3,909,134 capture rows carry no time **[measured]**, so most older URLs are "due now" on the first run after the switch. *Fix:* "a null `last_attempt` gives `next_attempt_at` = the import run's date plus the interval, else null".

**S11. Numbers that do not reproduce** — re-measure or label as *est.*: §7.10 "1,695,040 occurrences; largest document 455" (catalog `source_occurrences` sum 4,727,694, max 33,479; distinct `(body, url, path)` 1,691,547 **[measured]**); P §7 "36,137" (36,854 by last status, 43,767 by any **[measured]**); §7.3 "about 34,000 HTML members" (45,724 bodies, 58,283 rows by member extension **[measured]**); P "3,042 over 50 MB" / §11.5 "579 over 100 MB" (2,467 / 642 decimal, 2,268 / 588 binary, by distinct body **[measured]**); A §16.1 "about 1,500 object operations" a day omits the per-body HEAD of §7.1 step 2 (about 4,500 with 3,553 rows and up to 1,595 PUTs **[est. from doc]**). Everything else checked matches exactly: 3,909,134 rows; 2,289 files; 2,596,054 lines; 1,036,256 bodies; 0.70 TB; 1,158,426 URLs; 1,041,863 bodiless lines; 1.19 GB; 22,354; 3,553/2,946; 708,626/745,456; 49 files / 2.2M rows; placeholders 18/22/12; the 57-byte body at 87,161 URLs; 287,765; 5,587; 1,683,430; 331,985; 24,202; 1,392,681; 95,664 header names; 460,256 download-state-only rows; 141,762; fingerprint candidates about 300 PDFs and up to 1,400 ZIPs (147 PDF endpoints / 294 bodies; 685 / 1,370 ZIP) **[all measured]**.

**S12. `linked_from` (§7.10) and `publisher_links` (§7.5) disagree on archive members** (see M2): the page that linked the archive gives the member its meeting and kind but not its "where seen" context. One sentence after M2's fix removes the difference.

**S13. B14 depends on the 64 MiB cap being gone in the old path**, which B §3.1 schedules under B2. Either the cut-off re-fetch uses the ranged path only (say so) or the cap removal in `rust_fetch.py:134` and the workflow is the raw-safety fix named before B14.

## Minor

1. `error_signs` hard-codes 2,048 bytes while listing thresholds live in a registry; move it there.
2. `committee_key` is singular, `committee_code` and `list.committee_name` are lists; write "for each code".
3. The effective filename has no fallback when every step is empty (`https://host/`); say `''`.
4. `captures` nullability: `fidelity`, `context_url`, `writer_job`, `writer_commit`, `bytes` on bodiless or older rows are marked non-null.
5. §10.3.3's release-ID field list `(name, SHA-256, size, rows)` and the manifest's `files[]` differ; define the ID over the manifest's `files[]` and `schema_version`.
6. `locator` is defined in A §3 and again in DM §7.3.
7. S1 fixture 2's input omits the shared endpoint that makes "no document holds both editions" true; fixture 3 shows what happens without it.
8. §7.7 "a recovery import … never hides a URL that was never fetched" and S2's "the URL enters the queue" hold only if a page links it.
9. A JSON body at a non-API URL is a `document`; say whether that is intended.
10. Two scanned-image PDFs at one endpoint both lack fingerprints, so a repacked scan is always a new document; note it with the known limit.
11. §7.1 step 2: a failed HEAD should count as absent (a duplicate `<sha>` beside `<sha>.gz` is harmless).
12. §8.2 ingest "from the newest date already ingested" — say inclusive.
13. §6.2 "makes publish refuse until they are fingerprinted" — publish's own lake step fingerprints them; the refusal is the gate for a failed step.
14. Bindings lack rows for the committee explorer's lake switch (F3) and the weekly orphan report over the catalog; A §16.1's "O(new pairs)" for filename readings scans every capture row's pair (acknowledged in principle 4).

## Scores explained

- **Correctness and completeness (68):** three rules cannot be computed as written (M1, M2, S8), two pairs of rules contradict (S2, S7), one identity formula is not what the decision says it is (S3). The model is otherwise closed under its inputs and the edition protection holds (I could not build a counterexample to invariant 14 without a review edge).
- **Determinism and failure behavior (74):** every total order needed is stated except list-element order (S4); crash, retry and race paths are handled; the first-run flood (S10) and the page-version growth (S5) are unaddressed.
- **Data model (76):** keys, grain and joins are explicit and PKs are testable; the source-URL gap (M2), the role grain (S1) and the nullability drift (minor 4) are the costs.
- **Specification craft (80):** one home per rule mostly holds; cross-references resolve; fixtures with expected outcomes are the right acceptance sheet; several numbers are stale or unlabeled (S11).
- **Plan and bindings (78):** dependency order is sound and the bindings are precise to the line; the lock-before-writers gap (M3) and B14's cap dependency (S13) are ordering defects.
