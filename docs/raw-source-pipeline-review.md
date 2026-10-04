# Raw-source pipeline architecture review

Reviewed baseline: `483be4458f98e66ad4f62cd1587fd14c47c94dc9`, October 3, 2026.
Line references in baseline findings refer to that revision. This reviews the
complete raw-source route and its upstream and downstream boundaries, not the
unrelated document-catalog research currently being edited in this checkout.

**Verdict: RECONSIDER.** Keep immutable bodies, receipts, source-specific parsers,
house-naming and the two public document tables. Reshape stage lifetimes and
reuse of the existing inventory. More infrastructure or a larger worker does not address
the unnecessary work and memory overlap.

## Findings

1. **CONCERN — intent-vs-shape: acquisition owns publication.**
   `acquisition/raw_sync.py:134-137` invokes the catalog in `finally`, retaining
   the archive, download queue, seed context and futures throughout rebuilding.
   Even an acquisition error or stop request starts another expensive operation.
   This contradicts the separate collection/interpretation responsibilities in
   `packages/congress_api/README.md:97-123`. **RESHAPE:** acquisition saves its
   receipts/state and returns; the CLI releases it before calling the updater.
   Save the acquisition summary before the next operation can fail.

2. **CONCERN — commitment-violation: the first reusable source checkpoint comes
   after the failing join.** `retention/raw_catalog.py:201-222` expands context
   onto all rows and performs recovery before saving `sources.parquet`.
   Run [37155301094](https://github.com/civictechdc/congressional-tech/actions/runs/37155301094)
   stopped at 457,000 / 682,217 source rows. R2 had no source checkpoint afterward.
   The documented reuse promise cannot help that first run.
   **REVERSE:** remove the mixed checkpoint. The published filename inventory
   already retains source observations. Reuse it directly and rebuild missing
   source facts from receipts. Unpublished joins may rerun after failure.

3. **CONCERN — debt-accretion: compressed tables hide a large working set.**
   `raw_catalog.py:49-57` fully decodes the previous catalog;
   `document_index.py:643-654,985-991` recreates occurrence dictionaries during
   joins; acquisition state also remains live (finding 1). The read-only local
   replay exceeded 5 GiB at index loading alone. **RESHAPE:** stream prior-table
   columns, derive flat filters from the paired observations, share repeated
   immutable strings and occurrence values, and consume source rows while output
   rows are assembled. Release interpretation caches before document grouping.
   Preserve paired observations and every public field. The diagnostic resume
   reached 12,602 MiB during association and exceeded 14 GiB during assembly
   before this final lifetime correction; simply closing PDF buffers was not
   sufficient.

4. **CONCERN — intent-vs-shape: completed inspections survive exceptions but not
   hard termination.** `document_index.py:2033-2035,2070-2073` saves filename/body
   results only at stage exit. An hour of successful inspections can disappear
   when the worker dies. **RESHAPE:** retain only the optional body-result cache,
   saved periodically, including completed empty readings. Reuse filename fields
   from the published inventory; remove the duplicate filename-result table.

5. **CONCERN — ownership: the worker is its own only terminal-status reporter.**
   `cli/raw_progress.py:90-102` requires process cleanup to publish completion.
   The failed run left R2 reporting `running` with an old heartbeat.
   **RESHAPE:** finalize status in a separate, small workflow job, guarded by run
   identity and the object's current version; publish heartbeat expiry and memory
   usage so a lost finalizer is also distinguishable from live progress.

6. **CONCERN — user-value: known source kinds and size limits are applied too late
   to save I/O.** `document_index.py:2051-2099` inspects bodies before
   `prepare_document_indexes` applies publisher kinds. The cover reader's
   documented known-kind skip thus only sees filename classifications.
   `raw_catalog.py:118-124` downloads retained bodies before checking their
   original size, already available in the capture index. Unavailable bodies are
   also retried for each alias. **RESHAPE:** make document inspection opt-in.
   Apply the existing source fallback before optional PDF-cover inspection and
   recompute it when grouping aliases; reject known
   oversized reads before transfer and attempt unavailable bodies once per run.
   Native XML/format inspection must precede source-kind selection; only the
   PDF-cover fallback should be skipped. Keep `other` unclassified and retain the
   original source type and raw bytes.

7. **CONCERN — ownership: PDF readers do not release their buffers explicitly.**
   `parsers/document_cover.py:105-123` and `parsers/witness_pdf.py:51` create a
   `PdfReader` over an in-memory stream without closing either. PDF object cycles can retain the file and
   decoded pages until garbage collection. The full-corpus probe reached
   16,056 MiB during cover processing and stopped at its diagnostic limit.
   **RESHAPE:** give both resources a context manager; close them on success,
   abstention and exceptions. A real-PDF regression demonstrates the prior
   unclosed buffer; the sibling witness-reader check also preserves its raw digest
   and extracted observation. This is separate from the unknown hosted termination cause.
   Closing resources also does not turn the input-file size limit into a hard
   RAM limit: [pypdf documents the expansion during text extraction](https://pypdf.readthedocs.io/en/6.12.0/user/extract-text.html).

8. **OBSERVATION — named-seam: public table replacement is fail-closed, not atomic.**
   `raw_catalog.py:248-255` writes documents before filenames. The viewer rejects
   differing `catalog_id` values (`view_document_filenames.py:40-42`).
   **KEEP:** retain the previous pair and enforce matching IDs. A generation
   manifest would improve availability but adds consumer migration without
   addressing the current failure. Do not weaken the existing reader check.

## 1. Artifact summary

The operating design is `.github/workflows/raw-source-tables.md`, implemented by
`capture-raw-sources.yml`, `cli/raw_sync.py`, `acquisition/raw_sync.py`, and
`retention/{raw_archive,raw_catalog,document_index,catalog_cache,r2}.py`.
Paths without a repository prefix above are under
`packages/congress_api/src/congress_api/`.

Problem: retain all discovered government source bytes and metadata, then make
document names, kinds and provenance searchable without repeated downloads.
Beneficiaries: data maintainers and the document-catalog viewer's users.
Category: operations supporting a product surface. Source-preservation and
recovery tests are supporting verification, not additional product features.

## 2. Lineage and relationships

| Prior artifact | Relationship | Evidence |
| --- | --- | --- |
| `docs/congress-api-contracts.md`, opening and replay sections | Separates acquisition, byte interpretation, normalization and publication; preserves original evidence | Source fidelity and replay protection requirements |
| `docs/youtube-coverage/meeting-state.md`, state and acquisition sections | Weekly provider records live on pipeline-data and seed link discovery | Saved JSON/JSONL inputs in workflow |
| `packages/house-naming/README.md`, Choose an API | One offline filename rule owner; filename claims do not prove contents | `Engine.extract` boundary |
| `13cda76`, `be9bc83` | Earlier attempts reduced capture-row decoding and retention | Superseded only where this review finds remaining overlap |
| `29ced96` | Added heartbeat reporting | Retained, with independent failure finalization |
| `483be44` | Added incremental checkpoints and exact-revision validation reuse | Source/filename checkpoints removed; published inventory owns reuse |
| User instruction, October 3: basic inventory then optional metadata extraction | Explicit simplicity requirement | Governs this revision; supersedes the earlier checkpoint-placement proposal |
| `docs/adr/adapter-digest-versioning.md` | Protects Explorer domain identities | No adapter key or ID changes in this work |

| Component / seam | Responsibility | Input → output | Named? |
| --- | --- | --- | --- |
| Weekly collectors | `update-data.yml`, provider acquisition | Government APIs/pages → native JSON/JSONL, CSV summaries on pipeline-data | Yes: meeting-state and compatibility docs |
| Raw acquisition | `run_sync`, Rust transport, `Archive` | Seed URLs + retry state → bodies, receipts, capture index and retry state | Yes: raw-source-tables and Archive docstring |
| Raw storage | `R2Store` / `LocalStore` | Supplied key/bytes → checksum-checked objects or atomic local replacements | Yes: small injected read/put boundary |
| Source interpretation | Existing source parsers + `DocumentSources` | Receipts/XML/HTML → paired URL observations and scoped meeting context | Yes: DocumentSources docstring |
| Filename/body interpretation | house-naming + document evidence readers | Names or supplied bytes → flat observed metadata | Yes: separate reader fingerprints |
| Document grouping | `prepare_document_indexes` | Source rows → exact source table + grouped document table | Yes: catalog IDs and validation |
| Viewer | `view_document_filenames.py` | Verified pair → filterable lists and inline provenance | Yes: matched catalog ID required |
| Committee Explorer sibling | `publish-explorer.yml`, adapters, committee_meeting | Weekly records → normalized meeting Parquet and browser publication | Separate publication; does not currently consume this R2 document pair |

The two product catalogs serve different records and identity rules. Merging
them to remove a superficial duplication would change consumers; it is not a
fix for this incident. No active parent ADR requires a universal catalog or a
new data service. The operational document, package responsibilities and user
instructions supply the actual constraints.

## 3. Invariants and commitments

| Invariant | Source | Baseline status | Failure consequence |
| --- | --- | --- | --- |
| Raw body before immutable receipt; recover unindexed receipts | `raw_archive.py` docstring, record/flush/save | PRESERVED | Lost download evidence or repeated fetches |
| Acquisition and interpretation have separate lifetimes | README responsibility table; CLI composition | BROKEN: publication callback in finally | Acquisition failures trigger work; memory overlaps |
| Original source words, basis and parent/link pairing survive | DocumentSources docstring; compatibility source-context sections | PRESERVED; relied upon in refactor | Incorrect provenance or unsupported kinds |
| Completed expensive work can be reused | raw-source-tables, What an update reads | PARTIAL / BROKEN on hard interruption | Repeat historical I/O and parsing |
| Parsers accept supplied data and do not fetch | README import fences; pyproject policy | PRESERVED | Hidden refetches and untestable interpretation |
| Only validated matching catalog IDs may be served | document-index validation; viewer constructor | PRESERVED, with temporary unavailability on partial publication | Mixing unrelated source/document generations |
| Status distinguishes completion from incomplete work | `tests/test_raw_progress.py` purpose | BROKEN when worker cleanup cannot run | Dead work appears active |

No source-schema, public-column or domain-identity migration is needed. There is
no unlocated ratified specification being treated as authority.

## 4. User value

The outcome is a current, searchable document catalog without refetching already
retained sources or losing useful source context. The changes pay down an
unnecessary acquisition→publication callback and duplicated in-memory data.
They remove duplicate source/filename tables, make document-content reading explicit,
and retain periodic saves only for optional body inspection. A small independent
status finalizer fixes reporting after worker loss.

Rejected smaller-looking alternatives: raising the timeout repeats more work;
a bigger worker leaves recovery broken; removing provenance would lose user
value; adding a database/service introduces another durable owner without first
measuring whether the existing tables suffice.

Falsifier: repeated ordinary runs read historical raw bodies with unchanged
parsers, or ordinary metadata updates open the existing bulk documents. A small
fixture pass alone does not prove full-corpus capacity. Repeating unpublished
source joins is now an explicit tradeoff for removing duplicate persistent state.

## 5. Counterfactual checks

- Kill criterion: the revised first run still cannot complete on the supported
  worker with measured memory headroom, or resumed output differs from a fresh
  replay. In that case move bulk joins to a bounded disk-backed operation;
  do not hide the limit with retries.
- Opposite decision: replay everything every time discards useful published
  inventory facts. Direct reuse of that table removes the duplicate checkpoint
  without requiring every source body to be reread.
- Removal probe: remove raw capture and linked files disappear; remove the
  filename parser and useful name-derived columns disappear; remove expanded
  source context from checkpoints and nothing needs to disappear from outputs.
- Sibling subsumption: source parsers and house-naming already own extraction;
  reuse them. Explorer publication has distinct meeting/identity semantics.
- Six-month critic: growth in retained receipts must not cause unbounded copies
  of the same source occurrences or silently make failed runs look active.

## 6. Exploration record

H1: incremental checkpoints bound first-run recovery (high, workflow promise).
REFUTED by checkpoint placement and the failed run. H2: retained source context
requires duplicated persistent structures (low, current implementation). REFUTED:
the filename inventory already retains paired source facts. The earlier proposal
to move its mixed checkpoint before the join was rejected by the user's two-step
requirement; this revision removes that checkpoint instead. H3: the two catalogs are accidental
duplicates (low, similar Parquet terminology). REFUTED by their consumers and
identity policies. H4: normal exception handling covers worker loss (medium).
REFUTED by skipped cleanup and the stale status object.

Failure cause remains unproven: the hosted log reports cancellation, not an
out-of-memory exception. Local memory measurements test the design independently;
they must not be presented as a diagnosis of that host's termination.

GitHub documents a fresh worker for each job and supports `always()` on a job
with prerequisites. The separate finalizer therefore does not rely on the failed
worker's cleanup process. See [GitHub job dependencies](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-jobs)
and [hosted workers](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

## 7. Verification and resulting verdict

The revised code removes `source_checkpoint`/`restore_sources` and filename-result
cache writes. The existing filename table supplies source facts and filename
readings. Receipt replay supplies new facts; exact redirect/recovery observations
stay with the destination inventory row. Older scoped meeting receipts may be
read when newly received XML needs their context. No private meeting/URL graph
is serialized. Public schemas and document identity rules remain compatible.

Content inspection is disabled by default in both CLI entry points and GitHub
Actions. `--inspect-bodies` opts into retained content inspection. An ordinary
update preserves earlier content findings even when the content reader changed;
it does not silently relabel those findings as a new reading. The body-result
cache is the only retained interpretation cache. Source and filename caches from
older builds are ignored without deleting source evidence.

Acquisition ends before publication; PDF streams close explicitly; the separate
workflow finalizer reports worker failure. The existing matched-catalog-ID guard
and history remain. No database or service was added.

The removed 1,480,909-row checkpoint contained **831,540 file observations,
532,179 URL-context entries, 18,140 meeting entries and 99,050 URL-association
entries** in one 63-column table (123,839,853 bytes). That was an internal state
count, not a document count. Earlier checkpoint-equivalence measurements tested
an abandoned design and are not acceptance evidence for this revision.

Regression checks cover unchanged no-op runs, filename-only changes without raw
reads, opt-in body inspection, preserved earlier content facts, scoped meeting
joins, late redirect context, full versus incremental equivalence, publication
failure, viewer grouping, source preservation and workflow argument wiring.
The offline workflow and affected suites passed **4,929 tests in 69.73 seconds**,
including house-naming, source context, viewer, storage, import fences and workflow
checks. After the final preservation fix, **227 affected tests passed in 6.16
seconds**, including repair retaining content readings and preventing those
readings from leaking to changed bytes at the same filename. Actionlint and
Python error/undefined-name checks passed.

A local sample from actual receipts covers 30 receipt records from each of six
families: documents, House meeting XML, House witness XML, Congress.gov meetings,
Senate pages and GovInfo transcript HTML. Its 191 capture entries produced
**5,325 filename rows and 5,322 document groups in 4.43 seconds**, including the
unchanged follow-up. The initial pass read 16 receipt objects and 64 parent bodies;
the unchanged pass read three indexes and no receipts or bodies. The probe loaded
the full capture index to select its sample, so its roughly 3 GiB process peak is
not an isolated measurement of processing those 191 entries. Artifacts are in
`.cache/r2-admin/pipeline-review-20261003/simple-sample/`.

The earlier full-corpus run was stopped when the user requested this
simplification. A subsequent metadata-only rebuild of the complete locally
retained snapshot produced 671,035 filename rows and 553,914 document groups in
613.7 seconds, with a 10.96 GiB process peak. Both tables passed validation with
the same catalog ID. The integrated offline suite passed 6,465 tests, with five
optional native Rust checks skipped. Results are recorded in
`.cache/ci-fix-20261004/verification.json`.

This local snapshot includes missing bodies and does not establish full remote
coverage or hosted Linux capacity. No R2 publication or hosted rerun is claimed.

**Revised verdict: APPROVE the two-step shape; deployment capacity is unverified.**
Intent now matches the user instruction; the changes pay down duplicate state and
unnecessary document reading. Confidence is high in the tested preservation and
failure behavior, medium in operational performance pending a hosted run.
