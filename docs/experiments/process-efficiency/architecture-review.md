# Process efficiency architecture review — 18 October 2026

**Recommendation: keep the direction of A–F, retain the simpler one-pass source-context implementation after the direct integrated comparison, and judge the result across normal polls, changed builds and late retries.** Do not add the separate measured percentages. The remaining scale constraint is full-catalog traversal and nested-row materialization, which these changes only partly address. Linear work is necessary for some operations, including full reclassification; the avoidable costs are repeated traversals, copies and decoding, plus expanded nested records whose size is not bounded by a row-count batch.

This review applies the local semi-formal architecture-review skill. It traces the reviewed base `24137dd08241c34f1632afcd78a80a6138e5779d`, the audit and implementation proposal, A/B/D/status/E local commits through `5afecfc`, and C commit `801b808`, E refinement `f3ac7d4`, A qualification `ea32cad`, and F source arms pinned by `docs/experiments/process-efficiency-f/evidence/freeze.json`. The F, direct-cache and large-pair component receipts are complete. Combined final branch integration is a separate check. No hosted workflow or production publication was run for this review. A separate existing production monitor is outside its implementation and measurement scope.

## Findings and decisions

1. **KEEP — remove work that produces no new result.** B has the clearest recurring cost reduction: an exact unchanged recovery refresh avoids both large downloads and the mapping rebuild, while still checking selected status and mutable identities. This pays for itself structurally even without a production stopwatch result. Code and tests explicitly distinguish unchanged recovery inputs from a full remote data audit (`publish-viewer-r2.py:394-427`; `recovery-noop.md:1-23`).
2. **KEEP — simplify bounded work before adding persistent state.** D's one-pass aggregation removes a repeated decode and its exact predicate avoids constructing unused fields (`document_index.py:1062-1084,1234-1245`; `raw_catalog.py` association stage). A cache can be worthwhile even below an arbitrary threshold, but the two earlier experiments used separate contemporaneous baselines. Their 9.8% and 4.0% improvements cannot establish the cache's incremental contribution. The direct post-F cache comparison now shows a 3.27% median improvement, with paired improvements of 7.10%, 1.79% and 1.64%. It improved all three pairs; this is not a claim of zero benefit. Retain one-pass because the demonstrated gain is small relative to the added finalized/mutable state, eviction bookkeeping and unbounded temporary serialization: the rejected patch calls `pickle.dumps(result)` before checking its 1 MiB admission budget. That budget bounds retained entries, not temporary allocation for an oversized result (`process-efficiency-d/rejected-cache.patch:for_url`). Keep the measured candidate and its evidence for future evaluation; do not adopt the current cache solely because decode counts fell.
3. **KEEP, with an explicit scope limit — adopt compression level 9 as authorized.** The bounded research demonstrates a much cheaper codec setting with roughly 7–8% more compressed table bytes. It does not establish full publication speed or full-catalog browser latency. The complete Linux baseline failed at its capacity limit before internal stage evidence existed (`compression-plan.md:Recorded capacity result`; `output/process-efficiency/compression-linux-attempt2/trial-01-level-19/result.json`). Level 9 is a sensible risk/benefit choice; the user's explicit adoption decision supersedes the earlier hard gate. Preserve exact equality and diagnose the full-scale path separately.
4. **KEEP, measure success-path overhead — durable preparation exchanges routine I/O for cheaper recovery.** E avoids calling the builder after an accepted late failure and prevents uncertain writes being silently forgotten. Its artifact copy/restore and journal add requests, durable writes and hashes on successful builds. Journal safety is useful; repeated mutable selector polling for every immutable object was unnecessary and has been removed. Keep the initial and selection-time checks. The success and retry costs both appear in the evidence; local mocks cannot forecast remote latency (`viewer_publication_attempt.py:153-262`; `recovery_publication_continuation.py:143-213`).
5. **KEEP — file-backed catalog ownership, without claiming it fixes every memory peak.** F replaces compressed whole-file byte retention with bounded copies and explicit snapshot lifetime, preserving narrow derived-key writes and conditional selection. The complete frozen raw input pair is 1,083,172,105 compressed bytes. Its isolated read/validation comparison now demonstrates a 53.15% lower maximum sampled process-tree RSS, at a 72.69% higher median read time and about 1.083 GB of scratch. This is a worthwhile memory/temporary-storage exchange under the measured limit, not a general speedup. The audit's 15.85 GB parent peak involved nested source restoration. The viewer already opens local Parquet paths; F does not establish a fix for C's separate viewer OOM (`catalog_publication.py:27-161`; `raw_catalog.py:81-84,151-174`; `publish-filename-viewer.py:145-166`).
6. **KEEP — reproducible setup and honest qualification boundaries.** A removes duplicated package locks/setup, diagnoses prerequisites early, and assigns all fourteen historical test files to explicit regression treatment. The Python 3.12.13 pin is necessary because E binds exact runtime versions. Keep frozen research separate, and keep Linux/macOS/native/hosted results separately named (`.python-version`; `test-suites.toml:35-75`; `docs/development.md`).
7. **DEFER — the incremental index redesign.** A–F retain full restoration/export semantics. Full reclassification necessarily touches all records; routine small updates may still pay avoidable repeated whole-state work. A future affected-source planner should first prove its change closure against the existing complete result. Newly satisfied missing evidence, connected-component merges/splits, row positions, review bindings and fresh-host recovery are the hard correctness boundaries. The audit explicitly places this outside the current worktree (`IMPLEMENTATION.txt:WHAT BELONGS IN THE NEXT DESIGN`; `AUDIT.txt:THE HIGH-INVESTMENT OPTION`).

## Decision frame and lineage

The beneficiary is the developer/operator responsible for timely, verifiable civic-document publication, and ultimately the user waiting for current source context and recovery links. A and status are operational support; B/C/D/F improve compute and storage behavior; E is recovery infrastructure. None introduces a new public data model or new source acquisition.

| Prior artifact | Relation | Evidence |
| --- | --- | --- |
| Reviewed base `24137dd` | Existing semantics and benchmark reference | `output/process-audit-20261018/IMPLEMENTATION.txt`, opening and delivery rules |
| Completed run audit | Establishes large restore/preparation costs and unchanged-poll waste | `output/process-audit-20261018/AUDIT.txt:WHAT THE COMPLETED RUNS ESTABLISH` |
| Existing guarded publication and continuation | Reused primitives, not new gains | `scripts/guarded_recovery_publication_client.py`; preexisting `Continuation` |
| Existing retained receipts, catalog selector and history | Source authority and safe generation selection | `retention/catalog_publication.py:1-5,132-161`; `raw_catalog.py:349-365` |
| Content experiment freeze | Must remain distinct from current regression/runtime | `docs/experiments/filename-patterns-20261015/content_rule_freeze.json`; `test-suites.toml:69-75` |
| User steering after C OOM | Chooses level 9 on existing research, removes rigid optimization gate interpretation | `docs/experiments/process-efficiency/compression-plan.md:Recorded capacity result and user decision`; current session instructions |

All audit/proposal paths above are relative to the primary checkout `/Users/mikewolfd/Work/congressional-tech`. Code and implementation evidence are in the isolated worktree.

## Relationships and ownership

| Component / seam | Owner and inputs | Consumer / result | Defined boundary |
| --- | --- | --- | --- |
| Workspace setup | Root lock, six Python members, exact runtime and native tools | Local/CI test commands | `.python-version`, root `pyproject.toml`, `test-suites.toml`, shared setup action |
| Catalog snapshot | LocalStore/R2Store, selected manifest and exact table hashes | Rebuild, source restore, previous-history archive | `CatalogSnapshot` plus derived-file methods; F changes all maintained readers together |
| Source context | Retained paired occurrences, extra legacy filters | Source association and document classification | `DocumentSources` preserves original pairing; flat filters never establish provenance |
| Viewer preparation | Selected raw pair, review identities, compression policy | Complete local publication plus accepted inventory | `publish-filename-viewer.publish`; `viewer_publication_attempt.prepare` |
| Artifact custody | GitHub immutable artifact ID/run/digest/name | Explicit restart | `verify_github_artifact`, complete local inventory validation |
| Publication attempt | Original release, input versions, journal and accepted bytes | Immutable objects then selected viewer pointer | `DurableJournal`, `GuardedPublicationClient`, conditional pointer write |
| Status inspection | GitHub state, heartbeat, bound local receipts | Operator view with pending verification | `pipeline_status.py:113-197`; reads only, no second state store |

The design continues to reuse existing components. F introduces a distinct derived-file capability rather than broadening the source-body API. E extends the existing continuation and guarded writer rather than creating a scheduler or general workflow engine. These are appropriate boundaries; avoid adding another authority for accepted/selected state.

## Invariants and commitments

| Commitment | Status and evidence | Failure if broken |
| --- | --- | --- |
| Retained source evidence remains authoritative | Preserved; catalog metadata still derived, old selected bytes archived (`catalog_publication.py:1-5`; `raw_catalog.py:353-364`) | A repair could irreversibly erase context that cannot be reconstructed. |
| Exact values, pairing, order and required metadata survive optimization | Preserved in D's supplemental comparison of 24 tables and C's equality path (`process-efficiency-d/report.md`; `repack_and_verify`) | Faster output could silently change interpretation or browser identity. |
| Candidate, accepted and selected states differ | Preserved; artifact prerequisite, durable journal and conditional public pointer (`viewer_publication_attempt.py:153-199`; uploader selection) | Existence or exit status could be mistaken for public acceptance. |
| Mutable selection uses the original version | Preserved; explicit conditions and read-only reconciliation (`GuardedPublicationClient.put_object`; `Continuation.reconcile`) | Concurrent attempts could overwrite a newer catalog or mapping. |
| Restart can reconstruct the accepted runtime | Preserved by the exact Python 3.12.13 pin in commit `ea32cad` | Safe refusal would prevent the promised routine manual restart. |
| Native/frozen/fixture success are separate claims | Preserved in lane declarations and validation receipts | Skips or current fixtures could be mislabeled as native or research qualification. |
| Source body keys remain narrow | Preserved by separate exact catalog key allowlist (`derived_files.py:9-13`) | Optimization could accidentally grant generic object writes. |

## Aggregate runtime, memory and complexity

A useful accounting model is: recurring unchanged polls × no-op cost, plus changed catalogs × (raw rebuild + viewer preparation + artifact custody + transfer/journal/proof), plus explicit retries × (artifact restore + reconciliation + remaining work). This is an accounting framework, not a timing forecast. The workloads and baselines differ, so percentage improvements cannot be summed.

- **Normal polls:** B replaces data-sized repeated work with identity/status reads. The audit measured a prior 366 MB download per unchanged poll. Its 17.57 GB/day figure assumes every scheduled poll and is not observed daily traffic. New production traffic has not been measured.
- **Changed catalog computation:** D reduces finite redundant occurrence work; F removes complete compressed byte ownership from Python. Both retain full restoration/export semantics. `raw_catalog.py:151-174` still loops over all previous source rows in 4,096-row batches, including nested conversion. Necessary linear work is not itself a defect; repeated scans/materialization and redecoding unchanged values are the targets. Logical row size can dominate a batch-count bound. The next profile needs each stage's rows, occurrence count, decoded bytes, scratch bytes, and process-tree RSS, not just a total percentage.
- **Viewer preparation:** C lowers one costly codec setting while leaving verification, navigation, detail construction, review binding and ID generation intact. Complete preparation does more than compression. The new stage events improve the next diagnosis but cannot reconstruct the killed run.
- **Successful publication:** E adds an accepted artifact and an append-only journal. The current fixture records 273 public PUTs, 548 journal PUTs and full readbacks, 269 version HEADs, and four GETs for each of three mutable identities, plus 236,828 journal bytes. Counts exclude GitHub custody and public probes (`output/process-efficiency/success-request-counts-final.json`). Journal appends serialize, so even small records can add remote round-trip latency to the successful path. Hashing and full readback establish recoverability; remote costs remain unmeasured.
- **Late retry:** The local E fixture reuses preparation with zero builder calls and zero repeated release-payload writes. A process-local proof binds the exact client, bucket/key, hash, length and version established by full reconciliation; replay performs a fresh version/length HEAD. Serialized receipts or a different client cannot issue that proof and still require the full read. Copy/restore plus journal work measured 1.172 seconds locally versus a 0.226-second fixture build, illustrating why a tiny fixture is not a retry speedup claim (`output/process-efficiency/retry-fixture-proof.json`). The real beneficiary is the expensive preparation path; representative remote benefit remains unqualified.
- **Maintenance:** A pays down duplicated environment configuration. D without a cache avoids invalidation/finalization state. B's conservative full-revision fingerprint makes extra misses on unrelated changes but avoids a fragile hand-maintained dependency graph. E/F add state/lifetime complexity that is justified only because accepted results and bounded file ownership solve concrete failure modes.

## Direct F and cache evidence

All rows below use the same pinned Linux Python 3.12.13 image, two CPUs, a 2 GiB worker limit, network disabled, warm uncontrolled filesystem cache and a 250 ms process-tree/scratch sampler. Peaks can miss shorter events. The full-fixture comparisons use three alternating pairs each; the large selected-pair component uses two alternating pairs. Exact ordered rows, required metadata, implementation fingerprints and previous-history digests matched across all 24 fixture output tables. The component inputs remained unchanged. Sources: [summary](../process-efficiency-f/evidence/summary.json), [ordered/metadata/history checks](../process-efficiency-f/evidence/ordered-metadata-history.json), [plan and scope](../process-efficiency-f/plan.md).

| Scope | Reference → candidate | Interpretation |
| --- | --- | --- |
| Small complete rebuild, bytes → files | Median 14.3705 → 14.1334 s; maximum sampled RSS 370,356,224 → 384,327,680 bytes; maximum scratch 64,522,079 → 65,028,211 bytes | Timing ranges overlap. This fixture establishes equivalence and bounded resource behavior, not a full-rebuild speedup or memory reduction. |
| Direct file-backed rebuild, one-pass → cached | Median 14.1284 → 13.6663 s; maximum sampled RSS 381,349,888 → 382,304,256 bytes | 3.27% median benefit; pair gains vary from 1.64% to 7.10%. Keep one-pass given the cache lifecycle and temporary serialization cost. |
| Large selected pair read/validation only, bytes → files | Median 2.65244 → 4.58054 s; maximum sampled RSS 1,875,550,208 → 878,702,592 bytes; scratch 0 → 1,083,172,637 bytes | Measured 53.15% lower RSS, 72.69% slower reading and additional disk use. This directly demonstrates the compressed-file memory benefit; it does not include rebuilding nested rows or preparing the viewer. |

The initial component invocation used the offline wrapper's unsupported script form and refused before any timed read; the corrected invocation and original refusal are retained. No capacity limit was raised to obtain these results. The older failed C viewer trial remains separate.

## Counterfactuals and kill criteria

- Remove A: existing setup omissions, wrong-checkout imports and unassigned experiment tests become easier to reintroduce. The user loses early diagnosis, not a speedup in the data algorithm.
- Remove B: unchanged polls again download and rebuild large unchanged inputs. This is the earliest obvious recurring user-cost regression.
- Remove C: keep level 19's smaller bytes but pay the bounded experiment's much higher encode CPU. Reverse only if representative complete delivery/browser evidence shows the byte cost outweighs the CPU benefit.
- Remove D: repeat occurrence scans. The direct comparison shows a modest benefit but does not justify this cache's added lifecycle and temporary allocation shape; no arbitrary local percentage is universal.
- Remove E: successful runs are cheaper, but a late failure loses accepted preparation on runner loss. The design fails its purpose if artifact/journal restore regularly costs as much as rebuilding, or original runtimes cannot be restored. The exact patch pin addresses the latter; measure the former on representative failures.
- Remove F: simpler byte-only API, but memory grows with complete compressed input/output files. Reverse only if actual scratch/streaming overhead outweighs the resource benefit and a simpler bounded-file route exists; do not reintroduce parallel production APIs for old tests.
- Six-month critic: the likely question is why small updates still traverse so much unchanged nested state, not why a codec is level 9. The next material architectural step is proven change closure and storage layout, after measuring the remaining stages.

## Graded rationale

These are engineering judgments using separate dimensions, not measured scores or points awarded for test count.

| Dimension | Original | Current local result | Rationale |
| --- | --- | --- | --- |
| Correctness and recoverability | B+ | A- | The original already preserved provenance and conditional publication. Complete accepted inventories, fenced durable intents and conservative version proof close concrete restart gaps. Hosted integration remains unqualified. |
| Algorithms and data movement | C+ | B- | No-op work disappears; compression and repeated decoding become cheaper; compressed catalog files gain bounded ownership. Necessary linear processing remains, as do avoidable whole-state repetitions and expanded nested-record pressure. |
| Experimental evidence | B- | B | Exact comparisons, runtime identities and failed bounds are retained. Small complete fixtures establish mechanisms; representative end-to-end operation is still unqualified. |
| Developer reproducibility | C | A- | One lock, exact Python patch, own-checkout imports, native prerequisites and explicit test lanes remove known setup failure modes. Hosted CI and the complete Linux Rust lane are still separate gates. |
| Maintainability | B | B | A and one-pass D simplify. The justified E/F journal and file-lifetime state add complexity, so the net result is not automatically simpler in every subsystem. |

**Overall: B- originally, B currently.** Component F proof can strengthen its specific claim but does not, by itself, qualify representative operation or raise the overall runtime claim. A future B+ requires demonstrated net user benefit across the actual changed-build/retry mix without avoidable maintenance cost. The completed F component proof strengthens the bounded file-I/O claim, not representative end-to-end qualification.

This is a useful scoped engineering improvement, not yet an A-level scale redesign. It removes established waste and reuses maintained primitives. Full reclassification legitimately performs linear work; the unresolved engineering problem is avoiding unnecessary repeated whole-state traversal and materialization during ordinary updates, and bounding expanded nested records. The full viewer run did not fit the available bounded worker, and its failing stage remains unknown.

## Verdict

**APPROVE the local architectural changes and keep the one-pass implementation.** Intent and implementation match the small measured improvements requested. User value is supported for avoiding unchanged work and preserving preparation; broad latency/memory percentages remain unproven. Existing commitments are honored. Net conceptual debt is reduced in A/B/D and deliberately added at the E/F recovery and ownership boundaries. Confidence is high in the design direction and local invariants, medium in net runtime benefit across production workloads.
