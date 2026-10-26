# Review verdict: revise before execution

The overall approach is sound: preserve raw data, reuse defensible per-item results, build beside the old pipeline, and switch only after an engine-built release passes the reader’s checks. The main problems are incomplete phase boundaries, missing preservation and verification steps, and several rules that cannot produce the promised behavior.

I would retain the owner’s settled decisions, including the full F0 fixture, M2, borrowed PDF checks, the listing baseline, and deferred PDF copies.

References: **P** = implementation plan; **B** = bindings; **A** = architecture; **DM** = data model. Quantities below are marked **M** — measured in this review; **S** — taken from the submission; **E** — estimated. Step numbers, source locations, versions and commit hashes are identifiers.

## Must revise

### R1. Phase one is not a closed dependency graph

**Location:** P §4 dependency table; §6.3 completion; §6.4 completion; F4; DM §7.5, §7.7 and §8.1.

The phase description excludes B13, but the dependency table requires B13 for both D2 and F. Receipt-key lists are assigned to phase two in F4 even though phase-one releases need them for reconstruction after snapshot expiry.

The optional entity-file rule only solves the reader’s file presence problem. The model still derives:

- `meeting_refs` partly through transcripts;
- `chambers` through committees and meetings;
- `witness_keys` through appearance records;
- age-banded capture intervals through meeting dates.

Those inputs arrive later. An engineer must invent the phase-one substitutions.

There is also an acceptance cycle: C must finish the full export before D and E, although D supplies its tables and E supplies its model. The phase-one enumeration omits B11’s ratchet.

**Accepted replacement for P §4 and the affected completion sentences:**

> Phase one pins only `captures`, document `readings`, `filename_readings`, provenance and document registries. It derives hearing keys from document evidence and publishes key-only meetings. Meeting-derived dates are null; transcript and witness relationships are empty. Chambers come from the committee-code registry’s mapped chamber; unknown mappings remain empty and are reported. Undated meetings use the family’s unbanded recheck interval.
>
> Phase one includes B11, release input records, receipt-key lists and baseline-based maintenance. D2 and F do not depend on B13. C completes its capability contract jobs before D; the full export and rebuild-equivalence checks close at E/F. D’s completion applies only to phase-one tables. Entity fixtures, reference pins and committee-explorer migration close in phase two.
>
> Phase two adds producers and evidence. Its new evidence may change document membership, dates, saved copies and IDs; “additive” does not promise unchanged document results.

This preserves the split while making it executable.

### R2. Deferring the re-hash also disables the check that makes the listing baseline useful

**Location:** P B9–B10; A §7.4 and §8.2.

B9 first runs after B10, which is deferred. Consequently, phase one has a baseline but no scheduled comparison against it. The same deferred maintenance path is supposed to catch receipts that arrive behind ingestion’s date boundary.

A §7.4 also says the full re-hash skips keys having a verification record. After the listing baseline, that includes unverified bodies. Implementing that sentence literally can make the later re-hash skip its entire intended population.

**Accepted replacement for B9–B10:**

> After the raw locks, record the listing baseline and start weekly verification in phase one, using the old capture index until D1 replaces it. Compare recorded body keys, sizes and ETags; reconcile the complete receipt listing for late arrivals; report missing, changed and unreferenced objects; run the existing random sample.
>
> B10 remains in phase two, after B13. It skips only physical keys whose verification record has `sha256_verified = true` and matches the current size and ETag. Listing-only records never satisfy that predicate.

The baseline is a reasonable deferral. It detects changes **after** the baseline; it does not establish that pre-existing bytes match their SHA-256 names.

### R3. Borrowed PDF evidence needs an explicit importer, a valid selection rule and stable version semantics

**Location:** P §2, D2, S2’s raw-only check and §8 PDF sample; B §3.2 “Parsers: sniff”; DM §5.3 and §6.2.

`legacy_pdf_checks` is required by the model but has no scheduled producer in P or binding in B. Deleting the old readings before that import would remove evidence on which phase-one classification depends.

More importantly, `status = completed` does not necessarily prove a successful PDF open. The inspected path can recognize a PDF with a binary preamble or UTF-8 BOM, then return from `document_cover` before invoking a PDF reader. Its caller still records completed format evidence. I reproduced those source-function paths with synthetic malformed inputs. This establishes a selection hazard, not its incidence in the corpus. See [capture_metadata.py](/Users/mikewolfd/Work/wt/ct-ticket-audit/packages/congress_api/src/congress_api/retention/capture_metadata.py:34), [document_cover.py](/Users/mikewolfd/Work/wt/ct-ticket-audit/packages/congress_api/src/congress_api/parsers/document_cover.py:220) and [document_links.py](/Users/mikewolfd/Work/wt/ct-ticket-audit/packages/congress_api/src/congress_api/parsers/document_links.py:164).

There is also a rebuild problem. Existing sniff rows retain a borrowed verdict, while a clean rebuild can consult newly added copy verification and produce a different verdict under the same parser version.

Finally, “no PDF is read whole in phase one” contradicts the planned whole-read sample of **1,000 PDFs [S]**.

**Accepted replacement for D2’s PDF preparation and sniff step:**

> Before sniff backfill, import eligible legacy PDF-open evidence into immutable `legacy_pdf_checks`, retaining the source-part digest and recorded parser fingerprint. Do not infer `opened` from `completed` alone; prove the selector against the reader paths, including preamble and BOM cases. Preserve unknown original check times as unknown. Retain the owner-accepted receipt-based checks.
>
> Each sniff version pins the borrowed and copy-verification evidence it may consult. New verification affects a new version, whose maintained and clean-rebuild outputs must agree before promotion.
>
> Run the already planned PDF sample before adopting the borrowed results, stratified by supported capture checks, unattributed receipt checks, legacy-only evidence and unchecked bodies. Examine the known disagreements and report unchecked and conflicting results separately. Phase one performs these sampled reads, not a corpus-wide PDF read.
>
> The raw-only check runs after this provenance import and requires no old derived file at runtime.

The accepted receipt-only population of **15,475 PDFs [S]** and unchecked population of **3,104 PDFs [S]** remain explicit uncertainties; neither justifies an unsolicited full re-hash.

### R4. The reader lacks the size needed to open older gzip files safely

**Location:** P A5 and F0; A §11.5; DM §8.1 `detail` and `recoveries`.

A requires compressed downloads when the original exceeds **100 MB [S]**. `detail` contains no saved-file size, and recovery rows contain no size. An older gzip object’s HTTP length gives compressed size, not original size.

The reader therefore cannot decide whether to inflate a saved file without first downloading or expanding it. The pinned capture data records bodies as large as **1,187,816,490 bytes [M]**.

**Accepted replacement for A5, with the corresponding release-schema edit:**

> Publish original byte size for saved files and recovery files; alternates already carry it. Before fetching an older gzip copy, offer a compressed download when its original size exceeds the specified threshold or is unknown. Otherwise unpack and open it. Exercise both branches in the fixture and reader contract test. Size need not be displayed.

This is operational data the reader needs, not a reversal of the decision to omit a size display.

### R5. Dead-link lookup loses requested addresses that redirected successfully

**Location:** P phase-one outcome and S2 dead-link fixture; DM §3 “source URL”, §7.2 `copy_urls`, §8.2 lookup keys.

A top-level source URL is the final URL. `urls.parquet` indexes that URL and recovery originals, but not the requested URL of a successful redirected fetch.

**Counterexample:** a published `/download?id=report` redirects to `/files/report.pdf`. The archive saves the PDF. Later the download endpoint dies. Pasting the published address finds nothing, although the receipt records it and `copy_urls` already represents it.

**Accepted replacement for DM §8.2’s lookup-key rule and the corresponding S2 fixture:**

> Build lookup rows from every good fetch’s requested and final addresses for listed real files, plus recovery original links. Reuse the address relation behind `copy_urls`, apply the fixed `lookup_url` normalization, and deduplicate `(lookup_key, list_row)`. The fixture includes a requested address that redirects successfully and later disappears.

This needs another metadata join, not another body read.

### R6. A successful API page is not a completed relist

**Location:** P B15; B §3.1 Congress.gov APIs and removal of source state files.

B15 advances the relist window from the API list URL’s `last_good_at`. That records a successful page fetch, not successful traversal of the whole list.

**Failing sequence:** the first page succeeds; a later page fails; the next run starts its time window after the first page’s success. Older updates on the unread pages can fall outside that window. Treating query-specific page URLs as the checkpoint also leaves the stable checkpoint identity unspecified.

The existing code explicitly preserves unfinished work so advancing update times cannot skip it. That behavior needs a replacement before its state files disappear: [meetings.py](/Users/mikewolfd/Work/wt/ct-ticket-audit/packages/congress_api/src/congress_api/acquisition/meetings.py:99).

**Accepted replacement for B15:**

> Key each relist by its stable API endpoint and requested time window. Advance its completed-through watermark only after every page in that window has been stored and the terminal page observed. Record that completion in raw provenance and expose the watermark to capture. A partial run repeats the last incomplete window; already stored bodies remain reusable. Remove the old pending-state path only after a later-page-failure fixture proves no records are skipped.

This is a phase-two execution blocker; it does not require bringing meeting enrichment into phase one.

## Should revise

### S1. Make B0’s final handoff finite and verifiable

**Location:** P B0–B1; B receipt-rewriter contract suite.

The backup, conditional overwrite, exact-change comparison and crash recovery are good. The remaining ambiguity is operational: patching scheduled writers does not establish that an already running old revision has stopped emitting dirty receipts. Meanwhile, “every receipt has a verification record” is a moving target while capture continues.

The mirror check found **6,966 absolute-looking key names [M]**, with **zero basename collisions [M]** and **zero matching absolute pointer segments [M]** in that examined set. Those checks do not establish the owner-approved field list or cover future receipts.

**Accepted replacement for B0’s closure:**

> Patch and drain obsolete writer revisions before cleanup. Validate each transformed receipt before its conditional replacement, retaining the existing read-back comparison. When the owner is ready to lock receipts, briefly pause receipt writers, back up and clean the final delta, verify the exact receipt-key set, apply and read back the lock, then resume patched writers. Conflicts or unresolved protected fields block this handoff. Delete the rewriter only after these records are complete.

### S2. Make the measurements produce decisions, and move extractor selection earlier

**Location:** P M1, M2, S1, D2 and A11.

M1 has a useful decision threshold. M2 names measurements but leaves the actual resource ceilings and failure response implicit. S1 tests fingerprint behavior before D2 selects the extractor that produces those fingerprints.

The receipt input is **1.083 GB compressed [M]**, but **13.784 GB uncompressed [M]**. Its largest line is **187,661,340 bytes [M]** and references **196 captures [M]**. Carrying a copied raw string through that expansion would create about **36.8 GB [E]** of intermediate string data from that line alone.

**Accepted replacement for the relevant measurement instructions:**

> Before M2 runs, commit the runner’s pool, process-memory and scratch ceilings and its decision rule. Extract fallback fields once per receipt line before expanding capture entries; measure the largest line’s decoded allocations and preserve skew in the link/context workload. A variant qualifies only within those ceilings.
>
> Move the already planned main-content extractor comparison from D2 into S1 and use its real fingerprints in M2. D2 retains the full-data repeat. M1’s scan projection includes the existing table baseline, not just newly appended small batches. A11 records the devices, workloads and accepted thresholds before tuning.

Keep the full M2 input. No additional broad corpus scan is needed for these changes.

### S3. C5’s named helper is buffered, not a streaming file uploader

**Location:** B §3.3 C5; P C5 acceptance.

The OpenDAL MD5 configuration is supported by the installed dependency. That reuse choice is sound. However, [`create_bytes_by_key`](/Users/mikewolfd/Work/spicy-stack/docspec-rs/src/storage/remote/objects.rs:534) accepts a complete `Vec<u8>`. Configuring its checksum does not make it stream a file.

**Accepted replacement for B C5:**

> Reuse the create-only PUT semantics and OpenDAL MD5 support. Charge the complete upload buffer to the shared pool and measure the largest release file. Use this path only while it fits that reservation; otherwise supply a bounded file-backed single-PUT implementation. The contract checks peak memory, request counts, conditional conflicts and absence of multipart upload or read-back.

This avoids building a more elaborate uploader before its necessity is established.

### S4. Merge the exceptional fetch jobs into the scheduler, and defer unused sharding

**Location:** P B14, B16, F2; B reader/export sharding items.

Phase one’s queue already discovers wrapper targets, and its scheduler already retries cut-off attempts through the uncapped fetcher. Those populations are not isolated until phase two merely because separate jobs are listed there.

Sharding is also implementation work now for a growth condition described as roughly **ten times current rows [S]**, despite DM making it optional.

**Accepted replacements:**

> B14 and B16 are priority selections for the existing capture scheduler, using current receipt evidence to exclude completed work. F2 sets the per-run request, byte and spool budgets, including the first run’s historical backlog. These selections introduce no additional writer or retry path.
>
> Emit unsharded release files initially. Implement sharding only if F0 or the first engine release exceeds the specified metadata or reader limits.

### S5. The deferred ZIP fingerprint walk is still unbounded work

**Location:** B §3.2 “Parsers: fingerprint”.

“No member limits” avoids silently omitting members from a hash, but streaming alone bounds neither decompression work nor runtime.

**Accepted replacement:**

> Walk members without buffering whole members. Bound total expanded bytes and elapsed time using the parser version’s declared limits; record a deterministic refusal when either limit is exceeded. A candidate without a fingerprint remains a separate edition.

No new measurement is needed until such a candidate actually appears.

## Minor revisions

### N1. Remove duplicated instructions and stale navigation

**Location:** P S/E1; P §2/D2/§8; B §3.4 Model and §6.

The PDF work is specified repeatedly and now contradicts itself. S writes the rules, while E1 partly restates that work. B §6 points to F4 for deletion, although deletion is F5.

**Accepted replacements:**

> **E1:** Use the SQL, registries and fixtures completed in S; E adds integration, invariant checks and parity.
>
> **B Model:** Build the model from S’s SQL; E supplies its acceptance evidence.
>
> Keep the PDF execution rule in D2 and its measurement decision in §8; shorten the strategy paragraph to reference them. Correct B’s deletion reference to F5.

## Evidence checked and its limits

| Check | Result | What it could not see |
|---|---|---|
| Frozen submission | Read P, B, A, DM and the settled decisions. No earlier reviews were read. | Future implementation or operational readiness. |
| Code bindings | The inspected congressional-tech code matches B’s pinned code despite the checkout’s later HEAD. The engine matches `d9c6719`. PDF checks, body-store PUT, conditional pointer flip, filename parser, export settings and union-find exist. | Exhaustive qualification of every binding or every surviving consumer. |
| Capture and catalog snapshot | Capture digest matches `db033173…`; **3,909,134 capture rows [M]**, **1,036,256 distinct bodies [M]**. Catalog footers report **1,241,157 documents [M]** and **1,683,430 filenames [M]**. | Semantic parity, body integrity or live bucket contents. |
| Receipt mirror | Read **2,289 files [M]**, **2,596,054 lines [M]**; measured compressed/uncompressed sizes and the largest line. | Backup correctness, writer races, lock enforcement or receipts outside the mirror. |
| Legacy PDF readings | **226,842 distinct PDF bodies [M]** have completed readings. Stored identity fields include `parser_fingerprint`; no explicit successful-open flag or original check timestamp exists. Synthetic source execution demonstrates the selection hazard. | How many actual PDFs take that path, or fresh PDF integrity. |
| OpenDAL upload support | Local dependency code supports MD5 for single PUT and rejects it for multipart initialization. | Real R2 request behavior and target-runner memory. |

Reproducible local checks and outputs are in [review_checks.py](/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/review-9/codex/review_checks.py), [receipt-pointer-check.json](/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/review-9/codex/receipt-pointer-check.json) and [legacy-pdf-counterexample.json](/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/review-9/codex/legacy-pdf-counterexample.json).

No network requests, bucket mutations or raw-body reads were performed. These checks do not substitute for M1, M2, real-device testing or the owner’s lock actions.

## Cost assessment

Let **R** be receipt bytes, **B** body count, **N** relational rows, **T** resolved link targets, and **Fᵤ** the source-file multiplicity at address *u*. Complexity below is **estimated from the specified algorithms**. Runtime on the **4-vCPU, 16-GB runner [S]** remains unmeasured unless the submission supplies a figure.

| Work | Reads, writes and complexity | Runtime or cost concern |
|---|---|---|
| B0 cleanup | Linear in uncompressed R; read originals, write cleaned receipts, read them back, and back up missing originals. | Compressed size understates parsing work. Bound concurrent large-line decoding. |
| Locks and writer changes | Constant-size configuration work; contract fixtures plus a representative capture. | No justification for a historical body scan here. |
| M1 | Scratch writes, catalog operations and full scans of the tested table layout. | Maintenance waiting and metadata growth, not body bytes, dominate uncertainty. |
| M2/S/F0 | Full receipt decoding, catalog scans, sampled page reads and fixture exports. Sorting is `O(N log N)`. | Raw-line duplication, wide allocations and skew must be measured. |
| D1 ingest | `O(R)` decoding plus the processed-key anti-join; append derived capture rows. | The submission’s approximately minute-long ingest **[S]** is not established by this review. |
| D2 sniff | About **1.04M ranged GETs [S]**; bytes scale with the chosen range length. | Request latency can dominate. At **100 GETs/s [E assumption]**, this is about **2.9 hours [E]**, before page parsing. |
| D2 page parsing | **289,179 bodies and about 5 GB [S]**, plus reading-table writes. Linear in decoded input and emitted links. | Measure extraction time, decompressed bounds and link-output size. |
| D3 filenames | Work-list scan plus **1,392,681 pairs [S]** for the initial version. | **7–18 minutes [S]**; reuse unchanged pairs thereafter. |
| E/model/parity | Scans and sorts; link matches cost `O(Σ TᵤFᵤ)`. Union-find is near-linear in nodes and edges. | Group-node construction avoids pairwise quadratic edges. Link and parity joins can still multiply rows. |
| F publish/reader | Full changed release upload; browser startup proportional to `list`, later reads by indexed ranges. | Approximately **95 MB per changed release [S]**, not a daily byte delta. Buffer reservations and phone decoding remain gates. |
| Weekly verification | `O(B)` metadata listing and joins, plus the existing **25-body sample [S]**. | Useful in phase one without a corpus re-hash. |
| B13 copies | About **365 GB read and 403 GB written [S]**, plus verification records. | Storage grows permanently under the lock. Stream, bound spool use and resume from verified outcomes. |
| B10 re-hash | Linear in remaining unverified stored bytes. | Must exclude actual whole-read verification, not listing baselines. |
| D4/entity work | About **60k bodies, 9 GB and 199,156 inline records [S]**, plus reference-generation reads. | Read inline records by receipt batches, not by reopening a gzip receipt per record. |
| B14/B16 | Linear in selected fetch bytes through the existing scheduler. | Separate implementations would duplicate scheduling and retry work. |
| Deferred ZIP fingerprinting | Linear in expanded bytes, which can greatly exceed stored bytes. | Currently unbounded until S5 is adopted. |

The cost structure is mostly appropriate. The weak spots are request-heavy sniffing, intermediate expansion and missing resource admission rules—not the near-linear grouping algorithm.

## Grades

All grades are **estimated review judgments**, out of 100.

| Category | Grade | Reason |
|---|---:|---|
| Ordering and dependencies | **62** | Cross-phase edges and an integration-acceptance cycle remain. |
| Phase split | **58** | Optional files are defined; optional model inputs and operational duties are not fully separated. |
| Risk front-loading | **74** | The right major probes exist; extractor timing and decision ceilings need correction. |
| Reuse decisions | **77** | Strong direction, with incomplete legacy-evidence selection and preservation. |
| Executability and acceptance | **63** | Several steps still require hidden choices or an undefined completion boundary. |
| Cost | **65** | Sensible asymptotic design; request cost and peak intermediate memory remain under-specified. |
| Raw-data safety | **75** | Locks, backup and conditional writes are strong; monitoring and cleanup handoff need tightening. |
| Bindings | **84** | Most inspected references are accurate and the build/adapt choices fit; a few adaptations are understated. |
| Simplicity | **73** | Good consolidation, with removable duplication and prematurely specified work. |
| **Overall** | **70** | A credible plan that needs targeted rewrites before commitment. |

## Final verdict

**Not ready to execute as written.**

Resolve R1–R6: close the phase-one dependency graph, activate baseline verification, preserve and correctly select PDF evidence, supply saved-file sizes, index redirected requested addresses, and define completed relist checkpoints.

Then execute the existing gated measurements and owner actions. The evidence does **not** call for restarting the architecture, moving the full re-hash into phase one, replacing Iceberg before M1, shrinking F0, or trimming M2.