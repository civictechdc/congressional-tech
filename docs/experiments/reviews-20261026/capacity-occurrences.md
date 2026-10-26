# Occurrence publication and bounded-resource review

## Findings first

**One confirmed resource defect in merged main; fixed locally.** At reviewed main
`ad222085f8dc4e4b7a34c0e7db9bf5a52bb66d4f`, the flat occurrence writer limited
pending observations to 16,384 rows but did not accept or enforce
`DecodedPolicy.writer_buffer_bytes`. Individual observation admission therefore
could not establish a bound on all retained writer rows. This predated the fused
publication path; fusion makes the writer overlap with browser generation.
Evidence: `packages/viewer_publication/src/viewer_publication/filename_exports.py:343`
and `:374` at the reviewed main SHA; the native caller at
`packages/viewer_publication/src/viewer_publication/filename_native.py:296` supplied
no policy to that writer.

Severity: **WARNING**, category: resource correctness. Four narrow reproductions
failed on that exact main: standalone and combined publication accepted eight
512-byte values in one group under a 4,096-byte writer budget, and accepted one
2,048-byte value under a 1,024-byte budget. These fixtures fit the existing
individual-observation admission limits, so those guards do not prevent the gap.

Fix commit: **`c178fd5dd024fa27d12565bfb875e4cd30a25593`**. Both caller paths now
supply the policy and metrics. The writer counts retained Python value trees and
reserved list space, flushes before the configured ceiling, and refuses a single
row that cannot fit. Shared values count repeatedly, conservatively; it does not
retain a second graph of visited objects. See the fix's
`filename_exports.py:346`, `:359`, `:390`, `:417`, `:448`, and
`filename_native.py:296`. The existing default is 64 MiB, with the 16,384-row ceiling
still enforced (`filename_budget.py:17`, `filename_exports.py:369`, `:409`).

No further actionable defect was confirmed in the inspected occurrence,
source-leaf, implementation-fingerprint, or component-index seams. This is a
bounded review, not a review of every merged data, deployment, or upload change.

## Scope and method

Reviewed main: `ad222085f8dc4e4b7a34c0e7db9bf5a52bb66d4f`.
Reviewed local correction: `c178fd5dd024fa27d12565bfb875e4cd30a25593`.
The worktree was rebased with an empty commit range onto exact main; prior patches
were already integrated. No old superseded patches were replayed. Backup ref
`codex/occurrence-passes-backup-20261026` preserves
`bc403130c507dfb869e4e4b39add397456420403`; review branch is
`codex/review-capacity-occurrences-20261026`.

Applied the semi-formal code-review skill. Static tracing covered the three
occurrence implementation files, changed occurrence/source tests, the component
lookup index and its test, source-count/detail admission, implementation
fingerprints, initial/upgrade resume bindings, renderer task commits, and the
workflow test-selection boundary. Only the concrete resource defect warranted
execution. The wider suites reported by the coordinating task were not rerun or
promoted into fresh evidence here.

Working hypotheses and outcomes:

- Three source traversals can become one without changing row semantics:
  **confirmed** by the shared writer and generation-time fingerprint.
- A row-count limit establishes a writer byte bound: **refuted**, reproduced and
  fixed as above.
- Fingerprinting may permit null/empty, order or value corruption: **refuted** for
  the traced framing and tested corruption cases; schema and row-count checks
  remain separate.
- Component indexing could alter membership or reuse eligibility: **refuted** by
  the indexed query shape, one-result guard, implementation fingerprint, and
  inspected seek-versus-scan/result-equivalence test.

Unless a main-SHA location is explicitly identified, line references below refer
to the local fix SHA. Paths named `filename_*.py` below live under
`packages/viewer_publication/src/viewer_publication/`.

## Function traces

| Function | Location | Inputs | Output and verified behavior |
| --- | --- | --- | --- |
| `publish_selected` | `filename_native.py:876` | Selected catalog, previous publication, policy, optional preparation binding | Rejects incompatible reuse before rendering; binds source, rules and review inputs for resumable work. |
| `NativeSourceAssets.render` / `_render` | `filename_native.py:334`, `:340` | Native source route and previous route | Reuses unchanged subtrees; changed leaves run as owned renderer tasks. |
| `NativeSourceAssets.render_source` | `filename_native.py:370` | Selected native source leaf | Checks retained leaf rows/bytes and source IDs, writes core Parquet, publishes occurrences/details, computes admitted facets, checks footer count. |
| `typed_observations` | `filename_native.py:278` | Schema, ordered owner IDs, occurrence reader | Produces null or typed part sequences without joining the whole observation list. |
| `publish_occurrence_assets` | `filename_native.py:293` | Typed source, policy, output directory, optional counts | Shares observations with the flat writer; publishes immutable assets only after generation and writer closure succeed. |
| `publish_observations` / `_publish_observations` | `filename_observations.py:165`, `:176` | Typed source, counts, optional flat writer | Admits each observation once, builds deduplicated browser blocks and row references, fingerprints source values, verifies generated local blocks, then writes the index. |
| `observation_rows` / `observation_values` / `observation_value` | `filename_observations.py:38`, `:57`, `:79` | Native typed parts | Enforces reference-list estimate, schema, part bytes, sequence length and per-observation Python admission. |
| `_fingerprint_row` / `_fingerprint_value` | `filename_observations.py:222`, `:226` | Row lengths and canonical JSON bytes | Frames null rows with -1, empty rows with 0, and each value with its byte length. Order and boundaries participate in the digest. |
| `verify_observations` | `filename_observations.py:231` | Generated files/index and expected digest, or explicit source | Reconstructs canonical dictionary values in SQLite, validates blocks/references/counts, and compares the framed digest. Normal generation supplies its digest and avoids reopening native occurrences. |
| `publish_occurrence_parquet` / `_publish_occurrence_parquet` | `filename_exports.py:299`, `:448` | Standalone source, owners, row/byte policy | Adapts an Arrow table when needed and feeds the same writer; budget refusals produce the maintained failure receipt. |
| `OccurrenceParquetWriter.start_row` / `append` / `finish_row` | `filename_exports.py:382`, `:390`, `:412` | Declared row length, then decoded observations | Preserves owner/order and null markers; enforces row completion and corrected pending-byte admission. |
| `OccurrenceParquetWriter._flush` / `__exit__` / `result` | `filename_exports.py:417`, `:429`, `:442` | Pending admitted rows | Writes rows and matching browse ranges, clears byte accounting, closes on success/error, checks footer count, and returns slices/schema/ranges. |
| `publish_details` path | `filename_details.py:76`, `:88`, `:114` | Physical core source and owned observation counts | Reads/admit every source row, verifies output schema/count/digest; the removed additional source scan adds no independent count fact. |
| `NativeComponents.__init__` / `_prepare_entries` | `filename_native.py:444`, `:625` | Staging SQLite database | Adds `views_by_component(component,name)` idempotently; per-component lookup still requires exactly one document asset. |
| `native_requirements` | `filename_native.py:750` | Implementations, policy, compression, Arrow version | Hashes normalized AST of occurrence files and native owner code; actual writer/index code changes affect reuse eligibility. |
| `RendererState.run` | `filename_renderer_state.py:172` | Task and action | Saves task result and commits before completion notification; completed work can be reused after interruption. |

Native source-occurrence callees were also read:
`packages/congress_api/src/congress_api/retention/catalog_dependency_storage.py:319`
resolves the selected release and delegates to `catalog_rows.py:620`, which resolves
the owner, preserves null versus count, and returns typed occurrence parts.

## Data flow and invariants

1. **Source custody.** Selected source rows enter through the dependency reader.
   `render_source` checks native leaf size, row count and unique ordered IDs before
   converting serving output (`filename_native.py:378`). Source observations and
   document observations enter the same shared publisher (`:398`, `:620`).
2. **One decoded observation.** `observation_value` admits a typed scalar before
   `as_py`; the resulting Python value feeds compact browser encoding and the flat
   writer (`filename_observations.py:79`, `:193`). The writer retains only its
   bounded pending rows; it never retains native part sequences.
3. **Exact browser comparison.** The expected digest is created once, updated with
   row framing and encoded values, then consumed by the verifier. It remains
   process-local and is not accepted from a remote receipt. The actual digest is
   rebuilt from generated references and canonical dictionary values. Schema,
   reference types, missing dictionary IDs, block continuity and row counts are
   independently checked (`filename_observations.py:187`, `:217`, `:238`, `:272`,
   `:281`, `:289`).
4. **Flat output.** `row_slices` records the logical occurrence offset and length;
   null rows use -1 and empty rows 0. Byte-triggered flushing changes physical
   groups, not the running logical row count or occurrence order. Browse ranges
   are computed for the actual flushed group (`filename_exports.py:382`, `:417`).
5. **Resource scope.** The new metric bounds conservatively accounted retained
   Python rows/list space. It is not total process memory: a current admitted input
   observation, native decoder buffers, browser blocks, SQLite caches, conversion
   tables and Parquet codec allocations have separate lifetimes/bounds. No process
   memory benchmark or production-sized claim is made. Source core leaves retain
   their existing native bounds; details/facets retain physical-reader admission
   (`filename_budget.py:17`, `:65`; `filename_native.py:379`, `:396`, `:412`).
6. **Failure and recovery.** An oversized writer row raises the maintained budget
   exception before it enters the pending list; the publisher writes its failure
   receipt. `publish_occurrence_assets` reaches immutable asset installation only
   after both publishers complete (`filename_native.py:296`). Renderer tasks
   rollback failures and commit results before completion callbacks
   (`filename_renderer_state.py:172`). Restored assets are rechecked locally by
   identity (`:139`). These are local preparation checks, not object-upload
   readbacks.
7. **Implementation binding and workflow selection.** Native rules include the
   changed implementation AST; existing v6 reuse requires equality or an explicit
   upgrade, while retained preparation binds the same requirements
   (`filename_native.py:750`, `:891`, `:937`). The workflow checks out the original
   resume revision before tests. Its historical path fallback omits only listed
   supervisor tests for accepted historical resumes; preparation resumes still
   require their tests (`.github/workflows/publish-filename-viewer.yml:93`, `:116`,
   `:136`). No workflow mutation is part of this fix.

## Edge cases and test evidence

| Scenario | Evidence read | Result and risk assessment |
| --- | --- | --- |
| Null row, empty row, null observation, Unicode, duplicate/order preservation | `test_filename_native_sources.py:228` | One source call per owner; browser and Parquet bytes match separate publishers for the representative fixture. Included in the fresh focused run. |
| Value/reference corruption without reopening source | `test_filename_observations.py:281` | Changed values, reference order, null/empty shape and trailing rows are rejected. Included in the fresh focused run. |
| Huge logical list split across native parts | `test_filename_observations.py:224`, `:258` | Parts are read once for generation; missing, extra, wrong-schema and oversized parts refuse. Included in the fresh focused run. |
| Group boundaries inside one owner row | `test_filename_observations.py:310` | Ten source parts produce groups 7/7/7/7/2 while row slice remains [0,30]. Included in the fresh focused run. |
| Aggregate byte budget reached before row limit | `test_filename_observations.py:343` | Four red/green reproductions cover standalone and combined paths; 4,096-byte policy creates multiple groups while all eight rows/order/slices remain. |
| Single row exceeds writer byte budget | `test_filename_observations.py:368` | Standalone/combined refuse, retain a failure receipt, and install no immutable occurrence assets. |
| Mid-generation open/serialization/compression/write/verification failures | `test_filename_observations.py:83` | Owned browser writers close and incomplete logical blocks do not flush; primary cleanup errors retain their context. Included in the fresh focused run. |
| Unchanged source subtree or mapping-only rebuild | `test_filename_native_sources.py:20`, `:95` | Maintained tests assert no old native payload reopening and unchanged roots/zero new payload bytes. Included in the fresh focused run. |
| Component query seek with no/multiple matches | `test_filename_native_indexes.py:17` | Inspected assertions prove same entries and query results, idempotent index creation, indexed SEARCH rather than SCAN. Static evidence here; not rerun. |
| Resume before/after task completion, changed inputs, corrupt completed asset | `test_filename_initial_resume.py:19`, `:46`; `test_filename_native_upgrade.py:30`, `:56` | Inspected guards and tests cover task reuse, binding mismatch refusal and local corruption refusal. Static evidence here; not rerun. |
| Real native process exit | `test_filename_native_upgrade.py:95` | Inspected initial/upgrade and start/completion parameterization; no native-binary or subprocess qualification was executed in this review. |

The correction preserves semantic rows, schemas, null markers, order and row
slices. **It can change Parquet row groups, browse ranges, bytes and asset digests
when the byte ceiling causes an earlier flush**, including at the default ceiling
for sufficiently large observations. The representative byte-equivalence test is
not proof of byte identity for all production input sizes. The implementation
fingerprint changes with the correction, so prior preparation/reuse cannot silently
claim the corrected implementation's requirements.

Executed red/green reproduction: four failures on exact reviewed main, then four
passes after the correction. Executed focused regression on the correction:
**50 passed, one real-native qualification deselected, 12.23 seconds**.

```sh
PYTHONPATH=packages/viewer_publication/src:packages/congress_api/src:packages/congress_shared/src /Users/mikewolfd/Work/congressional-tech/.venv/bin/python -m pytest -p no:cacheprovider packages/viewer_publication/tests/test_filename_observations.py packages/viewer_publication/tests/test_filename_exports.py packages/viewer_publication/tests/test_filename_native_sources.py -k 'not actual_native' -q
```

`git diff ad222085..HEAD --check` passed before this report. No full catalog build,
production memory measurement, remote operation, deployment, push or merge ran.

## Verdict

**REQUEST CHANGES on reviewed merged main** for the confirmed writer-byte gap.
**APPROVE the inspected occurrence/source/index seams with local fix
`c178fd5dd024fa27d12565bfb875e4cd30a25593` applied.**

The combined path achieves one native occurrence traversal while retaining exact
browser corruption checks. The correction makes the existing writer byte policy
effective without changing source semantics. Coverage of the changed writer path
is **ADEQUATE** for this bounded correction; confidence is **HIGH** in the local
behavior and **MEDIUM** in production resource improvement because no complete
production build or process-memory qualification was performed. Integration of
the local correction remains the coordinating task's responsibility.

## Final integrated source review

Final source reviewed: **`6183938fcb2b0842d5e1f59072383aa7dd251d32`**.
The coordinating task integrated the writer correction under that exact source
commit. Its occurrence implementation and observation tests are byte-identical to
the locally reviewed/tested correction `c178fd5dd024fa27d12565bfb875e4cd30a25593`:
`git diff c178fd5d 6183938f --` the three affected files produced no differences.
The earlier integration-pending verdict therefore no longer applies to this final
source SHA.

The incremental review covered only `ad222085..6183938f` as relevant to this scope.
The three occurrence files carry the same reviewed correction. Adjacent release
identity changes expand the fingerprint's source set to include `docspec_client`,
publication builders and constants (`release_identity.py:28`, `:38`), strengthening
binding of this caller chain. The supervisor now recomputes remaining wait time
from the original absolute deadline, including after process launch
(`scripts/publication/prepare_workflow_resume.py:95`, `:108`); it does not change
observation emission or task-completion ordering. Other raw-data changes in this
range are outside this occurrence review and were not audited here.

No tests were repeated for this final rebase because the occurrence correction is
identical. The coordinating task supplied final-source evidence of **126 renderer
and native checks passing**; I read `/tmp/ct-post-review-occurrence-20261026.log`,
which records 126 passed in 46.78 seconds. That is owner-supplied execution evidence,
separate from the four red/green reproductions and 50-test run executed in this
worktree above. No production memory or full catalog qualification is inferred.

**Final verdict: APPROVE the inspected occurrence, source-leaf, component-index and
fingerprint seams at `6183938fcb2b0842d5e1f59072383aa7dd251d32`.** The confirmed
writer-byte defect is fixed in that source. No unresolved actionable finding
remains within this scope; earlier-flush physical output differences and the
resource-evidence limits remain as stated above.

Before the final rebase, backup ref
`codex/occurrence-review-backup-20261026` preserved report tip
`6af164866e962c43ff124497b28a38bd38811c76`. The owned review branch was then rebased
onto exact final source while dropping its duplicate local source correction and
retaining this report. This review performed no remote writes.

### Final closure source

Final closure source SHA: **`0cde0d348dce0c5eae714a7199b54839dab8bc23`**.
The coordinating task's additional bounded smoke-read correction is outside this
occurrence review scope. The scoped **APPROVE** verdict above is unchanged.
No audit or test expansion was performed for this report-only rebase from
`6183938f` onto `0cde0d34`. Backup ref
`codex/occurrence-report-final-backup-20261026` preserves the preceding report tip
`b2b1b6c0fda59d0f1bbbe5c059d7b41bea844373`.
