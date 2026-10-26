# CS 300 review: Congressional Document Archive (engine-first design)

Reviewed cold on 2026-10-25: A (architecture), DM (data model), P (plan), B (bindings), plus the owner's decisions. Numbers are tagged **[measured]** (my DuckDB runs over the read-only 2026-10-19 snapshot; scripts `prof6_measure.py`, `prof6_measure2.py`, outputs `*.out` in this folder), **[doc]** (taken from the documents) or **[est.]** (mine).

## Verdict

**Not yet ready to build from; three small edits away.** The layering (append-only raw, derived lake, deterministic releases) is sound, the per-item cost accounting is unusually honest, and the plan puts the lock and the two decisive measurements first. What blocks a green light is (1) a self-contradiction in the one sanctioned rewrite of raw history that either leaks API keys into public files or makes the cleanup unverifiable, (2) a hole in that rewrite's safety net, and (3) a "one plan" rule whose cost the documents do not account for and whose decisive measurement (M2) would not catch. All three are rule rewrites of a sentence or two, not new sections.

**Score: 77 / 100.** Architecture correctness 78; efficiency 80; failure behavior and raw-data safety 71; plan 82.

## Spot-checks of the documents' numbers

Everything in A §5 and DM §6–7 that the snapshot can reproduce, reproduces exactly **[measured]**: 3,909,134 capture rows; 2,596,054 receipt lines; 1,041,863 bodiless lines; 1,036,256 bodies; 1,158,426 distinct context URLs; 2,289 receipt files; 22,354 bodies on one line; 696 GB stored (PDF 364.8 GB stored / 403.2 GB original over 261,039 bodies, ZIP 288 GB, untyped 36.9 GB, HTML 4.2 GB, XML 0.8 GB); largest body 1,187,816,490 B; none over 5 GB; 2026-10-16 = 3,553 rows / 2,946 lines; 2026-09-29 = 745,456 rows / 708,626 lines / 547,700 bodies; 21 families; placeholders 18 at k=100, 22 at 50, 12 at 200, top one a 57-byte VTT at 87,161 URLs; 2,717,129 rows without a time; 49 non-date receipt files with 2,197,261 rows; 287,765 server-labelled HTML/XML bodies; 214,040 good-fetched with 277,631 contexts (doc: 214,041 / 277,642); 141,762 body keys in several old documents; 1,392,681 filename pairs; 331,985 without a URL; 24,202 multi-kind; 491,710 readings; 64 cut-off URLs without a complete copy; 453,751 caption rows; 10,783 playlist rows; 460,271 saved-text rows; largest document 455 body keys.

Where I could not reproduce or found a different figure:

- Bodies over 100 MB: **588 [measured]** vs 579 [doc, A §11.5]. Immaterial.
- "98k metadata records" [doc, DM §7.5]: the old `record_role` gives 47,643 `source-record` rows **[measured]**; the 98k likely counts by XML root. Not reproducible from the snapshot; the listed-document estimate (0.5–0.7M) is unaffected in order of magnitude.
- Fingerprint candidates (my proxy: endpoints that served two or more distinct non-empty 2xx bodies, before role filtering): **5,056 endpoints, 9,523 bodies: 323 PDF (12.7 GB), 1,370 ZIP (76.6 GB), 6,805 HTML, 29 XML, 384 untyped [measured]**. The doc's "300 PDFs, up to 13 GB; up to 1,400 ZIPs" holds. Two things it does not say: the ZIPs are 76.6 GB if they must be read rather than taken from `captures.expansion`, and 384 untyped bodies need text extraction of an unknown format. No archive-member endpoint served two bodies today.
- Rendition groups (my proxy of DM §7.5 (b), broader extension list): **19,160 groups over 57,021 source files; 18,932 have one body per format, 213 would be refused for a repeated format [measured]** vs about 16,000 / 32,547 documents [doc]. Consistent.
- Timestamps: of the 2,717,129 rows without a time, **522,448 sit in date-shaped receipts (30% of 1,711,873 dated rows) [measured]**. DM §7.5 attributes the gap to "older lines" and P D1 checks only the undated receipts' JSON. See S4.
- "1,500 object operations a normal day" [doc, A §16.1]: a normal day's 258–1,595 new bodies each cost one HEAD and one PUT (A §7.1), plus one ranged sniff GET each, before lake reads, release upload and canary: **4,000–8,000 [est.]**. Still deep inside the free tier; the number is wrong, not the conclusion.
- "Over half of body-bearing attempts find an existing body" [doc]: not derivable from the snapshot's `resolution` column.
- Fidelity: exact-bytes 1,872,309; retained-file 534,689; saved-text 460,271 **[measured]**, matching P E4's 460k collapse.
- Link fan-in: the largest old document carries 33,479 link occurrences over 4 URLs and 2 bodies **[measured]**; distinct bodies per URL peak at 5 **[measured]**. So the link→source-file join (DM §7.2) cannot blow up: its output is bounded by 5 × links.

## Must-fix

**M1. The receipt cleanup contradicts itself, and the contradiction either leaks credentials or makes B0 unverifiable.** DM §5.2 "The one-time cleanup" and P §6.2 B0. The rule removes "the credential parameters in recorded URLs" and in the next sentence promises "every URL … stayed byte-identical"; B0's run check asserts "no URL … value changed". One of these is false. If the URL check wins, Congress.gov `api_key=` values stay in public receipts and flow unchanged into public release files: `url_state.requested_url` (DM §7.7 strips credentials from queue rows only; invariant 12 tests only queue rows) and `occurrences.url` (§7.10). If the removal wins, B0's done condition can never pass. Fix, folding into the rules: DM §5.2 → "Every other value stayed byte-identical; a recorded URL changed only by losing its credential parameters." B0 → the same clause in the re-read check. DM invariant 12 → "no row of `url_state` and no occurrence URL carries a credential parameter" (the model strips them where it already strips them for queue rows). B0 "done when" → add "and the keys that appeared in receipts are rotated" (they have been public on `r2.dev`, decisions §Raw).

**M2. The one rewrite of raw history has no safety net for receipts written after 2026-10-24.** P §6.2 B0 names the input as "the receipt keys in the 2026-10-24 backup plus any written since", rewrites in place with `If-Match`, and after a crash "verifies against the backup's original". A receipt written since has no original anywhere once its PUT lands; a crash between that PUT and the re-read, or a bug in the rewriter, loses the only copy of its attempt records. Fix (one sentence in B0's run): "A receipt not in the backup is copied there, create-only, before it is rewritten." The verification record already carries the backup object compared.

**M3. "One plan with no intermediate tables" is unpriced, and M2 as written will not price it.** A §9.1, §13.1, §16.1; P §5.2. DataFusion inlines a CTE at every reference; it does not materialize shared subplans. The model's most expensive relation, resolved link targets (5.5M rows [doc], each through two RFC 3986 UDFs and `url_key`), is consumed by `publisher_links`, the `url_state` queue, `linked_from`, `file_meetings`, `same_rendition` (a), `removed_on` and `document_kind`; `real_files` by placeholders, edges, the fingerprint work list, occurrences and `url_state`. In one plan each is evaluated once per consumer: O(k·N) with k ≈ 6–8 on the widest relation, and k duplicate hash-join builds inside the memory pool at once. §16.1 lists every other repeated cost and omits this one. M2 is a "throwaway harness" that naturally runs steps one at a time, so it would pass while C7's single job spec fails or spills. Fix: A §9.1 "evaluates one plan with no intermediate tables" → "evaluates one job: named steps whose results stay in memory or scratch and never in the lake"; §13.7's job spec lists the steps; M2 adds one line, "report how many times the link-resolution and real-file subplans appear in `EXPLAIN` of the single-plan form, and time and peak memory for the single-plan and stepped forms". Deleting "no intermediate tables" shrinks the section.

## Should-fix

**S1. A 412 on a receipt or provenance write must be an error, not "unchanged".** A §7.2 says a run writes numbered files create-only; it does not say a run ID is never reused. A resumed run that reuses `<run>-<seq>` gets 412 from `If-None-Match: *` and, if it follows the body store's convention, treats it as already written: up to 22,354 bodies [measured] lose their attribution silently. Rewrite A §7.2: "a run ID is never reused, and a 412 on a receipt or provenance write fails the run".

**S2. An errored sniff yields a real file.** DM §7.3: `format` is null when the pinned `sniff` reading has `status = error` (unreadable object, undecompressable gzip); `record_role` has no null-format arm and falls to `'document'`; invariant 8's "failed reading" covers only HTML/XML/JSON. Rewrite the `record_role` list's first line: "null when format is null or the sniff reading is not completed" and report them with the other role-less bodies.

**S3. The first weekly check would re-hash 0.7 TB.** A §7.4 "a body with no creating line is re-hashed once": every one of the 1.04M older bodies has no line with `stored_md5` and no verification record until B10 runs, so B9's verifier does B10's job on its first run, inside the publish concurrency group. Rewrite: "a body with neither a creating line nor a verification record is reported; only keys newer than the last re-hash job are re-hashed".

**S4. D1's timestamp check must cover dated receipts.** 522,448 timeless rows sit in date-shaped receipts [measured]; P D1 checks only `undated/`. Change "checks whether the undated receipts' JSON carries times" to "checks every receipt shape for times the old index dropped". This decides a label on ~30% of documents.

**S5. The 404 reload can loop.** A §11.3, invariant 21: a pointer naming a release whose files are gone (a maintenance crash mid-delete) makes the reader re-read the pointer and reload forever. Rewrite: "re-read the pointer once; if it names the same release, show the not-found notice".

**S6. The fingerprint step is unbounded inside the daily publish.** DM §6.2, A §12: a registry change (file shapes, listing thresholds, k) can enlarge the candidate pool to its ceiling, 9,523 bodies today, 89 GB if ZIPs are read [measured], and the lake step runs it synchronously before the pin. Add to A §12 "Order": "a lake step whose work list exceeds its per-run budget runs as a backfill and publish refuses early", and delete DM §6.2's "makes publish refuse until they are fingerprinted" (the gate already says it).

**S7. Backfills race the publish lake steps.** A §8.1, §12: a background parser backfill commits to `readings` outside the CI concurrency group; the publish producer gets three retries against both Basin compaction and the backfill's batch commits, then fails the day's publish. Put "backfill" in the concurrency group's list in §10.3.7, or have it stop while publish runs.

**S8. B14 depends on B2's spool.** P §4 step 1 and §6.2 B14 run the cut-off re-fetch "first, through today's capture path", whose fetcher holds three bodies in memory and is capped at 64 MiB (B §3.1). The 64 URLs [measured] need bodies above 64 MiB, the exact thing that path cannot do. Say B14 runs after B2's spooled fetch, or that it uses `download_ranges` only and name its limit.

**S9. A gzip PDF with no `.pdf` copy has no rule.** DM §6.2 reads a PDF's tail from its `.pdf` copy; B13 can fail to decompress a damaged `.gz`. Add to the `sniff` bullet: "a gzip PDF with no copy is `intact = false`", so the work list empties and the body is reported as damaged.

**S10. Invariant 2's multipart clause is false for older bodies.** B §3.3 C5 says today's engine upload used 8 MiB multipart; such ETags contain `-`. Scope the clause: "no body with a creating line has an ETag containing `-`".

## Minor

- A §16.1 "1,500 object operations": correct to the HEAD + PUT + sniff-GET count per new body (4–8k [est.]) or delete the number.
- A §11.5 "579 over 100 MB": 588 [measured].
- DM §7.4: the bodiless row for a recovery that needs its own document has no stated effective filename; say "its decision's `recovered_filename`, else the original link's last segment".
- DM §6.2 `fingerprint` for ZIPs: say the members come from `captures` when `expansion = 'expanded'` "and otherwise the archive is read (76.6 GB today if none were)" so the budget in S6 is visible.
- P §6.5 E4 expected changes: add "source IDs of API-fetched files change where their URLs lost credential parameters" (follows M1).
- A §12 "Capture reads the public release": say that a failed publish streak leaves capture on a stale schedule, which re-fetches the due set and stalls HTML link discovery; bounded, accepted.
- DM §7.5 "98k metadata records": mark as *est.* or name the predicate; the old role column gives 47.6k [measured].

## Correctness as a system

Capture, publish and maintenance are well separated: bodies before receipts, receipts create-only, publish and maintenance in one concurrency group, the pointer flipped under `If-Match`, two releases retained, nothing deleted by publish. Crash cases I traced resolve correctly: a crash after upload and before the flip re-emerges byte-identical and gets 412s checked by one HEAD; a maintenance crash mid-delete of a release that later re-emerges re-creates only the missing files; a lost Iceberg race recomputes its work list against the new snapshot, so two ingests of the same receipts cannot duplicate rows; a canary failure leaves the previous release live and capture on a slightly older `url_state`, safe because body writes are create-only. The accepted loss (body without receipt) is bounded and named. The gaps are the ones above: receipt-key reuse (S1), the reload loop (S5), backfills outside the concurrency group (S7), and an error path that promotes an unreadable body to a document (S2).

## Efficiency (Big O by path)

| Path | Order | Accounted for? |
|---|---|---|
| Capture | O(new attempts); 1 HEAD + ≤1 PUT per new body | Yes; the op count is understated (minor) |
| Captures ingest | O(new receipts) read; O(history) anti-join on 2,289 keys | Yes (§16.1) |
| Readings work lists | O(history) distinct-body scan per parser per run | Yes |
| Filename work list | effective-filename SQL over all 3.9M rows per run | Yes ("scan the keys") though it is string work, not a key scan; seconds |
| Sniff backfill on a version change | 1.04M ranged GETs + 261k tail reads | Yes |
| Link resolution | O(links × contexts) = 5.5M; per (page body, context) | Yes; multiplied by consumers in one plan (M3) |
| Link → source-file join | ≤ 5 × links [measured max bodies per URL] | Yes |
| `linked_from` | links × contexts after reducing fetches | Yes, explicitly |
| Grouping | O(n) nodes, O(edges·α) union-find, 32 MB at 4M | Yes |
| Sorts/export | O(N log N) with unique keys; fold attached after the sort | Yes (§13.6) |
| Weekly check | O(history) metadata, 1,300 LISTs | Yes; first-run re-hash not (S3) |
| Fingerprint on a registry change | up to 9,523 bodies / 89 GB | No (S6) |
| Site | `list` whole, O(rows) heap in a worker; detail one page per leaf | Yes, with the 10× sharding plan |

The documents are better than most at naming repeated per-run work (§16.1). The one structural omission is CTE re-evaluation (M3).

## I/O and memory bounds

Object requests, bytes read and written are bounded by new items except for the weekly LIST and the two one-time jobs (B13: 403 GB written; B10: about 335 GB read after B13). Hash-join build sides are addressed by rule (§13.6) and by M2's reporting; the `readings.links` column (4.2M structs) and the `detail` fold are the two wide columns the SQL author must keep on the probe side, and M2 names both. The memory pool is set per runner class and must not exceed the machine. The reader's heap budget is enforced on the canary in Node and on real phones only after measurement; the contract test in a headless browser is the nearest proxy, acknowledged.

## Raw-data safety

Bodies: content-addressed, create-only, locked; the one hazard is a writer with a wrong hash whose key then shields later correct bodies behind a 412; B10's full re-hash catches the past and the 25-body weekly sample is the only ongoing check. Acceptable for greenfield, but say in A §7.4 that the sample checks SHA-256 against the key, not only MD5. Receipts: create-only, but reuse of a run key can silently drop a file (S1). Provenance: create-only, superseded by ID; fine. The receipt cleanup is the only rewrite and it is where the two must-fixes live (M1, M2). The lock is first in the plan and the maintenance credential is the only one that deletes; raw prefixes are locked before it exists in its new form. The lake and releases are rebuildable and treated as such.

## The plan

Order is right: lock, then the receipt rules, then the cleanup, then the lock on receipts, with B14 beside them; then M1, M2 and S1; then F0, C0, A and B; then C, D, E, F. The two risky measurements come before any lake or model code, and each step names a contract test or a committed measurement. B13, the largest write, waits for the lock and the refusal matrix. Weak points: M2 does not measure the shape the architecture mandates (M3); B14's dependency on B2 is inverted (S8); D1's timestamp check is too narrow (S4). Every step is executable and verifiable as written except B0 (M1 makes its done check unsatisfiable).

## Counts

Must-fix 3; should-fix 10; minor 7.
