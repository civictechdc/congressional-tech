# Independent review: archive definition authority

VERDICT: REQUEST CHANGES

The default publication metadata path cannot compile the supplied declarations under the pinned DDK release. Two separate declaration mismatches block catalog assembly. The baseline expectations and copied SQL are independently grounded in the incumbent Git revision, but they do not establish that this implementation can produce the required consumer bytes.

## Ranked findings

### 1. BLOCKER / correctness — the first relationship rejects the detail row-position identity

Location: `model/ddk/project.ddk.json:822-849`; supporting declarations at `:365-398`.

`document_detail` is one-to-one from `list.list_row` to `detail.list_row`. The same project declares `detail`'s `link_key` as a `kind: key` identity and `list_row` as a separate `kind: row_position` identity. In the actual released `ddk/catalog.py:269-276`, a unique relationship endpoint must equal a complete declared `kind: key` whenever that dataset has any such key. The row-position declaration is excluded from that comparison, so the target fails with `CATALOG-KEY-INCOMPLETE`.

The full trace is `archive_schema.build_schema` (`archive_schema.py:159-162`) → `checked_archive_schema` (`archive_definitions.py:206-208`) → `compile_archive_definitions` (`:123-129`) → DDK `build_catalog` → `Assembly.declarations` → `Assembly.relationship`. DDK catches the error and returns a failed report without `metadata.catalog` (`ddk/catalog.py:618-624`); the compiler then raises instead of generating metadata. This blocks ordinary `build_schema()` calls, the explicit generator/check command, and the real archive publication path (`archive_format.py:248`). It also blocks release comparisons that unconditionally request the current definitions (`release_comparison.py:169-171`).

Preserve both the primary public link key and the release-local physical row identity. Use a representation supported by the released DDK, or qualify the necessary DDK identity support and pin that successor. Do not weaken the relationship to many-to-many or remove the real primary key merely to satisfy assembly. The incumbent validator explicitly admits virtual unique columns in addition to the primary key (`archive_schema.py:120-123`), so its prior behavior is different from this DDK release.

Confidence: high. This is a static execution trace, not a reported test run.

### 2. BLOCKER / correctness — five recipes use informational relationships that DDK treats as required input bindings

Location: `model/ddk/project.ddk.json:3039-3046`, with the affected declarations also at `:3068-3076`, `:3372-3377`, `:3427-3432`, and `:3482-3486`.

The incumbent metadata lists useful semantic relationships alongside each recipe. DDK's `relationships` field has a stronger meaning: every local endpoint of every listed relationship must occur among the recipe's bound input datasets (`ddk/catalog.py:199-206`). For example, `bill_documents` binds only `list` and `detail`, but lists `document_bills`, whose target is `bills` (`project.ddk.json:1086-1094`). After finding 1 is repaired, this independently raises `CATALOG-RECIPE-RELATIONSHIP` before a catalog can be returned.

The complete mismatch set from the supplied declarations is:

| Recipe | Missing endpoint required by its declared DDK relationship |
| --- | --- |
| `bill_documents` | `bills` |
| `bill_hearing_transcripts` | `bills` |
| `recording_tracks` | `meetings` |
| `meeting_recordings` | `meetings` |
| `coverage_counts` | `meetings` |

Adding those datasets to `inputs` would change the consumer's requirements because the adapter emits `requires=list(item['inputs'])` (`archive_definitions.py:193-195`). This is a behavioral regression, especially for the two bill recipes that intentionally work without a populated local bills table (`test_archive_schema.py:68-73`, independently consistent with the incumbent SQL). DDK's checked access API also binds every recipe input and enforces same-release relationship scope (`ddk/catalog_access.py:168-182`), so the stronger meaning is operational, not just a validation quirk.

Represent informational references separately from the relationships that the recipe actually binds, while preserving the exact incumbent `requires`, relationship annotations, SQL and result grain. If the current release cannot express that distinction, fix and qualify the maintained DDK representation before adopting it here. Keep the recipe scope requirements visible; do not silently discard them.

Confidence: high. Finding 1 currently masks this second failure.

### 3. WARNING / correctness — the adapter can return a report for different definition bytes

Location: `packages/viewer_publication/src/viewer_publication/archive_definitions.py:124-133`.

`build_catalog()` admits and checks its own immutable documents. The adapter then reopens the project and ODCS source and uses these new values to construct the consumer schema without comparing their digests with the catalog's admitted `sourceInventory`. A concurrent edit or replacement between those reads can therefore produce a schema from one definition version and a DDK report from another. `read_json()` establishes valid bounded JSON, not semantic admission into the already-built catalog (`ddk/documents.py:194-203`). The recipe code correctly performs the missing association check for SQL (`archive_definitions.py:183-189`), which makes the inconsistency especially clear.

Consume DDK's admitted effective dataset definitions where available (`ddk/catalog.py:329-354`), and bind any unavoidable project/source reread to the admitted digest before using it. A narrow metadata-only comparison is sufficient; this needs no corpus reread. Add a deterministic test that changes the project or ODCS bytes after catalog admission and verifies refusal or use of the original admitted snapshot.

The SQL reread at `archive_definitions.py:187` also uses unbounded `read_bytes()` after DDK's bounded first read (`ddk/catalog.py:295-300`). Reuse the admitted bytes or retain the same byte limit on the reread. The current fixed SQL files are small; the issue is the gap between the two reads, not evidence of excessive resource use today.

Confidence: high about the missing association; occurrence requires an intervening mutation. This warning is separate from the two deterministic blockers.

## Review boundary and method

Reviewed the unstaged/untracked implementation against `a06eb64bf3caa4a44e12a89bdd08939323de3092`: `model/ddk/**`, `archive_definitions.py`, the changes to `archive_schema.py` and `archive_model_profile.py`, `test_ddk_definitions.py`, both affected `pyproject.toml` files, `uv.lock`, and the frozen DDK wheel and provenance. Read the repository instructions, the semi-formal code review skill, the ETL workflow skill, and its execution and lifecycle/reuse guidance.

The review was blind to the author's conclusions and the other reviewers' reports. No suites, compiler, native engine, network access, dependency installation, Git mutation, or source mutation ran. Read-only source inspection, archive inspection, and small standard-library comparisons of source bytes supplied the evidence. Only this report was written.

The installed `.venv/lib/python3.12/site-packages/ddk/` implementation was inspected directly. All Python files in the wheel and installed DDK match Git source `8e9a53e81ec6258f2068557ff5e4788c80c32995`. The external source checkout has since advanced, so the findings above cite the frozen wheel/installed release, not an assumption about that checkout's current branch.

### Exploration record

| Hypothesis before inspection | Evidence inspected | Result |
| --- | --- | --- |
| H1: The adapter genuinely gates the publication path. | `archive_format.py:203-205,248`, `archive_model.py:1344-1348`, `archive_schema.py:159-162` | Confirmed. It is not an unused generator. |
| H2: The released catalog API admits the new identity and recipe declarations. | Installed `ddk/catalog.py:175-206,239-286`; all project identity/relationship/recipe declarations | Refuted by findings 1 and 2. |
| H3: Frozen expectations describe the old revision independently of the compiler. | Git objects for the old registry/reference, inert test constants, all 16 SQL files | Confirmed for the facts listed below. Compilation parity remains unproved. |
| H4: Representation conversion is based on the same admitted input bytes as the report. | Compiler reads, DDK inventory/document immutability, SQL digest comparison | Refuted for project/ODCS rereads; finding 3. |
| H5: The definition migration introduces bulk data scans or native execution. | Catalog defaults, inventory limits, compiler operations, publication caller | Refuted. Reads are metadata only; no native invocation occurs in this adapter. |

## Patch summary and function trace

The patch authors 23 public table descriptions, 70 relationships, one product and 16 SQL recipes in ODCS/ODPS/DDK declarations. A local adapter converts them to the existing archive consumer JSON representation. `build_schema()` now requires that conversion and byte equality with the checked-in registry. The command can emit the full DDK report, and new source definitions enter the model's definition hashes. Physical lake schema authority remains in the existing model files (`archive_model_profile.py:88-92`); this patch does not implement native DDK execution or full replacement selection.

Paths in this table are relative to `packages/viewer_publication/src/viewer_publication/` unless prefixed with `ddk/`.

| Function | File:line | Input | Output and verified behavior |
| --- | --- | --- | --- |
| `ArchiveDefinitions.registry_bytes` | `archive_definitions.py:25` | Adapted schema | Indented ASCII-escaped UTF-8 JSON, with a trailing newline. No native effects. |
| `_archive_metadata` | `archive_definitions.py:30` | One ODCS object/property | Requires exactly one Congressional Tech `archive` custom-property dictionary. |
| `_path` | `archive_definitions.py:38` | DDK field/list path segments | Existing dotted/`[]` path; refuses unrepresentable literal dot/list syntax and empty paths. |
| `_logical_type` | `archive_definitions.py:55` | Exact incumbent physical type text | Limited logical type mapping; unknown types raise instead of being coerced. |
| `_check_property` | `archive_definitions.py:73` | ODCS property and nested children | Checks logical/physical agreement, binary interpretation, list items, struct order/types and scalar shape. Uses incumbent `_parts`. |
| `_column` | `archive_definitions.py:98` | Checked ODCS property | Legacy column fields/order. Requires explicit top-level boolean nullability for physical columns. |
| `compile_archive_definitions` | `archive_definitions.py:113` | Repository root | Calls maintained DDK catalog assembly, adapts definitions, checks SQL digests, returns mutable schema plus untouched complete report; deterministic blockers prevent this on the supplied definitions. |
| Nested `endpoint` | `archive_definitions.py:162` | Local/external relationship endpoint | Local dataset's object name and adapted paths, or retained external label. |
| `checked_archive_schema` | `archive_definitions.py:206` | Root plus generated registry bytes | Refuses generated drift, returns authored metadata. Does not return qualification evidence. |
| `build_schema` | `archive_schema.py:159` | Optional availability, explicit test registry, upstream digests | Default uses the new compiler; explicit registry path is deep-copied. Existing validation and availability stamping remain. |
| `main` | `archive_schema.py:343` | `--check`, optional report path | Compiles once, writes/checks registry and reference, then returns exit 2 for an incomplete report; invalid catalog raises first. |
| `_definition_hashes` | `archive_model_profile.py:85` | Root and current small definition files | Includes all DDK JSON/SQL, adapter source and existing lockfile alongside incumbent inputs. |
| `Assembly.relationship` | `ddk/catalog.py:239` | Declared identities, endpoint fields and relationship | Resolves paths/types and enforces complete key identities; produces explicit unknown for unsupported shared matching; rejects the first relationship here. |
| `Assembly.declarations` | `ddk/catalog.py:175` | Catalog declarations | Registers identities/relationships/recipes, then requires all recipe relationship endpoints among its inputs. |
| `Assembly.recipe` | `ddk/catalog.py:288` | Recipe, local SQL path | Resolves inputs; reads SQL under byte limit; records exact SQL digest. Does not execute the SQL. |
| `build_catalog` | `ddk/catalog.py:513` | Project path; default definition-only settings | Returns report and inspectable catalog for successfully assembled passed/incomplete metadata; catches declaration failures and returns a failed report. No output directory is requested by this patch. |
| `_release_schema` / `_execute` | `archive_format.py:203,237` | Actual release outputs and upstream generations | Calls changed `build_schema`; metadata enters native invariant generation and later `schema.json`. Manifest is written only after existing checks/footers and content files. |
| `_require_model_definition` | `archive_controller.py:113` | Retained model intent and engine | Compares saved file hashes with the changed definition set, refusing stale retained model definitions. |

## Data flow, invariants and lifecycle

1. Project, ODCS, ODPS and SQL files enter `build_catalog()` without a metadata adapter, exports or output destination (`archive_definitions.py:124`). DDK's definition-only mapping limit explicitly says availability, qualification and observed lineage are unresolved (`ddk/catalog.py:566-567`).
2. Catalog assembly validates the declarations. Unsupported shared relationship matching becomes `unknown` (`ddk/catalog.py:279-285`). Because the project requires `catalog.relationships` (`project.ddk.json:173-180`), these unknowns should reduce the report decision to `incomplete` (`ddk/results.py:36-47`). The supplied patch fails earlier; the intended incomplete result is not yet reachable.
3. The adapter constructs local dictionaries and lists and deep-copies the completed schema (`archive_definitions.py:198-203`). DDK's frozen dictionary/list classes implement deep copies as ordinary mutable dictionaries/lists (`ddk/documents.py:86-107`), so availability stamping is compatible with immutability rather than an attempted mutation of admitted documents.
4. The default publication call compares exact serialized registry bytes before returning a schema. There is no other default authored release-schema read in this path (`archive_definitions.py:206-213`). The optional `registry=` input remains for explicit callers/tests; the production `_release_schema` caller does not supply it (`archive_format.py:203-205`).
5. `build_schema()` distinguishes unavailable tables from published empty tables through presence names; it retains definitions and adds missing-table lists without inferring source completeness (`archive_schema.py:165-177`). External upstream paths are created only from supplied generation digests (`:149-156`).
6. In the actual producer, the schema generates maintained native null/key/reference checks, then the existing native job runs, footers are checked, and `schema.json` and the final manifest use the established atomic content writer (`archive_format.py:248-254,323-369`; `_content` at `:191-194`). The adapter creates no second selection pointer or success state. With the deterministic definition failure, an output directory has been created at `:238`, but the native job has not run and no manifest is created. A retry must use the existing attempt lifecycle; direct reuse of that directory is not automatically resumable because `mkdir(exist_ok=False)` remains.
7. Generator updates use two ordinary file writes (`archive_schema.py:365-366`), so interruption can leave the registry and reference from different generations. Rerunning/checking restores the pair; this is a generated-source-file operation, not an atomic live release selection. Publication checks only the registry's agreement with definitions. No atomic pair guarantee should be claimed.
8. New authored definition and recipe bytes participate in retained model identity (`archive_model_profile.py:91-96`; `archive_controller.py:117-118`). This prevents silently reusing a model under changed definitions. It does not implement metadata-only reuse: a note or recipe edit changes that broad identity too. The existing optional `relationship_metadata_update` record preserves the original model pins when deliberately supplied (`archive_model_profile.py:132-141`), but this patch adds no caller that selects such a reuse route. No full model rebuild or performance improvement is established by this review.

The current three source JSON files total roughly 382 KiB; all 16 recipe SQL files are small. DDK enforces an 8 MiB per-document limit, a 64 MiB project limit and nesting/graph limits (`ddk/documents.py:33-41`, `ddk/inventory.py:121-136`). The adapter performs extra metadata reads but opens no Parquet payload or raw body. Finding 3 qualifies the bound on the second SQL read. There is no measured speed or memory claim here.

## Independent baseline facts and packaging

These comparisons used Git's old file contents directly, not the new compiler or a generated candidate schema:

| Fact | Result |
| --- | --- |
| Old registry bytes | 134,651 bytes, SHA-256 `4afb316675b38fc163e34a43d2ebb3c85ea22bdd933ec94318d1c08ea7db1ba2`; matches the inert test expectation at `test_ddk_definitions.py:22-23`. |
| Old reference bytes | 85,261 bytes, SHA-256 `0c30daff52744691af3d47a478c651ecba509e9923ba092cf788669c08bea9a5`; matches `test_ddk_definitions.py:24`. |
| Old sorted semantic JSON | SHA-256 `e20aaae7ce7efdf856b3d349079680a0c9884781f68165d7a30fb9d845676a36`; matches `test_ddk_definitions.py:25`. |
| Recipe source files | All 16 SQL byte strings exactly equal their corresponding old registry SQL strings, including the lack of added trailing newlines. |
| ODCS data transcription | Across all 23 objects, direct comparison found no changes in old physical column order, physical type spelling, meaning, top-level nullability, table purpose/row meaning, gaps, nullability basis or retained domain notes. This is a source transcription comparison, not successful compilation or native schema qualification. |
| Frozen dependency | Wheel is 279,678 bytes, SHA-256 `b705e81c15636522c4e0e41f202ee3717d264800cdf0984c91f76ab925b4cd0e`; matches `vendor/ddk/README.md:8-10` and the lock entry. |

The root relative wheel source (`pyproject.toml:45`) and exact dependency (`packages/viewer_publication/pyproject.toml:10`) avoid a second checkout's editable package. The wheel includes `_build.json` naming the exact source revision, package resources, schema provenance, Apache license and NOTICE files, and upstream schema licenses. Inspection found every wheel/installed DDK Python source file equal to the named release source. Dependencies are locked to `jsonschema==4.26.0` and `referencing==0.37.0`; the optional catalog export extra is not requested. This verifies the inspected package identity and included notices, not external legal conclusions or a fresh installation/deployment.

## Test behavior and concrete edge cases

No tests were executed. Predictions below follow the inspected call graph.

| Test / scenario | Static behavior and limit |
| --- | --- |
| `test_ddk_definition_reproduces_frozen_metadata_and_recipe_literals` (`test_ddk_definitions.py:367`) | Fails at compilation before reaching the meaningful independent byte/semantic assertions. Its expected facts are independently correct. |
| `test_legacy_publication_reads_authored_metadata_and_refuses_generated_drift` (`:381`) | Fails on the initial valid-definition `build_schema` call; the generated-drift mutation is not reached. This exercises the real schema wrapper, not a complete publication job. |
| `test_changed_authored_meaning_cannot_reuse_stale_generated_schema` (`:391`) | Fails before obtaining the changed schema. It cannot yet show the intended admission/drift boundary. |
| Missing SQL / wrong field tests (`:402-411`) | Generic failed-catalog assertions can pass for unrelated earlier declaration failure. The missing-SQL case does not establish that SQL absence was detected. Assert the intended diagnostic after establishing that the unmodified copied definitions compile to the intended incomplete state. |
| Unsupported physical type (`:414`) | The unrelated first relationship fails before `_logical_type` can raise the asserted physical-type error. |
| Explicit incomplete report and exit 2 (`:422`) | Fails at its initial compiler call. Once assembly works, the reducer and CLI branches preserve required unknowns and exit 2 instead of a pass. |
| Definition identity (`:438`) | The added glob/source paths supply the tested hashes. This checks inclusion, not successful compilation, metadata-only reuse or changed-data correctness. |
| Existing schema tests (`test_archive_schema.py:12,32,44,59,88`) | Default `build_schema()` now reaches the blocker even for metadata-only callers. The tests independently state virtual-row, primary-key and availability semantics worth retaining. |
| Required unknowns under publication | Intended metadata use accepts an inspectable incomplete report and keeps native publication checks separate; the CLI returns the report explicitly. Ordinary `build_schema` returns metadata only. Neither is evidence that a DDK-required unknown passed. |
| Definition mutation after catalog admission | Not covered by new tests; can detach the consumer metadata from its returned report, as finding 3 explains. |
| Interrupted generator / failed actual publication | No new test covers partial registry/reference writes or retry after the newly introduced DDK refusal. Existing output/manifest ordering prevents a selected manifest from this pre-native failure. |

## Conclusion

VERDICT: REQUEST CHANGES

The patch moves the actual default metadata entry point to the new definitions and preserves independently verified baseline source facts. It does not yet achieve its stated first increment because the pinned maintained DDK rejects the supplied identity and recipe declarations. Resolve both representation mismatches while retaining incumbent keys and access scope, bind the adapter's report to the same definition bytes, then run the already-authored positive parity and incomplete-report checks through this checkout's required test entry point.

Coverage of changed paths: INSUFFICIENT as acceptance evidence today. Relevant tests exist, but static tracing predicts failures before their key assertions, and the read/admission race is uncovered.

Confidence: HIGH for the deterministic blockers and baseline/package facts; no runtime, full-suite, native-execution, publication or deployment qualification is claimed.

## Repair re-review — 2026-11-06

Disposition: all three original mechanisms are addressed in the application source. End-to-end acceptance remains blocked by the released DDK loader; VERDICT remains REQUEST CHANGES. The original findings above describe the original patch and are preserved as review history. Line references below describe the repaired source.

This pass again used static inspection and small read-only comparisons of authored JSON against Git `a06eb64bf3caa4a44e12a89bdd08939323de3092`. It did not run the compiler, tests, native commands, package installation or Git changes, and it did not edit shared DDK source. The parent reported that a real focused run now passes `doctor` and fails at the DDK external-target loader; that execution result is reported evidence from the parent, not this reviewer's execution.

### Original finding dispositions

| Original finding | Disposition | Current evidence |
| --- | --- | --- |
| 1. Unique endpoint cannot resolve to detail's row-position identity | Addressed in source; acceptance pending | `project.ddk.json:819-835` adds a distinct `kind: key`, `scope: release`, virtual `detail.list_row` identity. It explicitly describes declared uniqueness, not an observed result. The original `detail.link_key` key and row-position declaration remain at `:365-398`. The adapter still selects the original first identity at `archive_definitions.py:186-189`, so the consumer identity stays `link_key`. The new key satisfies the released DDK complete-key comparison at `ddk/catalog.py:269-276`; cardinality and `same_release` are retained at `project.ddk.json:860-865`. A static comparison of every unique local relationship endpoint against the declared keys found no remaining mismatch. |
| 2. Informational relationships force extra recipe inputs | Addressed in source; acceptance pending | The five references now live in `recipeContextRelationships` (`project.ddk.json:3777-3807`). The active DDK relationships have no remaining local endpoint outside their recipe's inputs. `_recipe_relationships` (`archive_definitions.py:130-149`) restores each contextual reference at its explicit position; rejects invalid positions, duplicate positions/IDs and unknown IDs; and rejects moving a relationship whose endpoints are already bound into context. `requires` still comes only from the original input names (`:243`). A direct static reconstruction of all 16 recipes found exact equality with the old ordered `requires` and relationship arrays. |
| 3. Returned report and schema can describe different bytes; SQL reread unbounded | Addressed in source; acceptance pending | `_schema_from_catalog` reads the project with DDK's document byte limit, requires exactly one admitted project source digest matching its bytes (`archive_definitions.py:163-167`), and obtains ODCS objects from DDK's admitted effective `datasetDefinitions` (`:170-183`). It therefore does not reopen mutable ODCS source to construct the schema. SQL rereads use `limit + 1`, refuse oversized data, and compare the digest to the admitted source inventory (`:224,231-238`). Successful output remains a deep copy of the admitted metadata (`:248-253`). |

The release-scoped key is valid declared metadata. It does not establish that a native consumer can supply or verify the virtual column, or that any actual released table has passed a new DDK uniqueness check. The added test explicitly requires empty observed `versions` and `runs` (`test_ddk_definitions.py:629-630`), which helps preserve this distinction.

The contextual mapping preserves the incumbent consumer annotations while keeping them outside DDK's executed input-binding list. This does not make DDK checked access support every recipe: external and other unsupported relationship scopes retain the existing limitations of `resolve_query` (`ddk/catalog_access.py:175-181`). The change remains a metadata-authority adapter.

### Test repair assessment

The previous false-positive concern is addressed by the repaired negative tests. `test_ddk_refuses_missing_recipe_or_wrong_relationship_path` first requires the unchanged copied definitions to compile to the intended `incomplete` state (`test_ddk_definitions.py:576-578`). Only then does it mutate the SQL path or field path and require the corresponding `CATALOG-IO` or `CATALOG-KEY-PATH` diagnostic, collected from both check diagnostics and operational errors (`:571-585`). An unrelated broken baseline can no longer satisfy these tests merely by returning any failed catalog. The asserted codes match the actual missing-file and missing-field branches in `ddk/catalog.py:295-300,618-623` and `:252-260`. These positive preconditions are appropriate; they currently stop at the independent dependency fault instead of falsely passing.

The added `BASELINE_RECIPE_ACCESS` constant (`test_ddk_definitions.py:353-515`) independently matches all 16 recipe access descriptions in the old Git registry. It is asserted alongside SQL, registry, semantic and reference-byte expectations at `:534-547`, and again by the virtual-key/access test at `:622-633`. This verifies the right intended property once the compiler reaches the assertions; this review did not execute them.

The new mutation cases target the repaired boundaries:

| Test | Static trace assessment |
| --- | --- |
| Virtual key and original public identity (`test_ddk_definitions.py:622`) | Asserts the old `link_key`, new release-scoped virtual key, retained 70 relationship declarations, all original recipe access arrays and absence of observed native versions/runs. The supplied identity ordering and declarations support these assertions. |
| Context indices (`:636`) | `-1`, `999` and `True` reach the explicit index refusal; `type(position) is int` excludes booleans (`archive_definitions.py:139`). |
| No demotion of an executed binding (`:647`) | Removes `document_detail` from active relationships and inserts it as contextual; both endpoints remain among the input values, so `archive_definitions.py:143-145` refuses it. The DDK recipe schema allows an empty active relationship list (`ddk/resources/schemas/0.1/catalog.schema.json:568-574`), so that earlier schema rule does not invalidate the intended test setup. |
| Project changed after admission (`:661`) | Reuses the prior report and mutates only project bytes; the digest mismatch must fail before use of the new mapping. |
| ODCS changed after admission (`:670`) | Reuses effective objects from the original report and asserts the original baseline registry hash and filename meaning. This demonstrates the intended snapshot use rather than a second ODCS read. |
| SQL changed/oversized after admission (`:680`) | Changed bytes fail the admitted digest comparison; oversized bytes fail the bounded reread before hash comparison. Both paths are explicit `ValueError` branches. |

`compile_archive_definitions` now attaches the complete DDK report to adapter `ValueError`s as well (`archive_definitions.py:123-127`), correcting the earlier loss of that report on representation errors. As with the original tests, none of the new tests establishes native model execution, selected-publication validity or deployment.

### Remaining dependency blocker and original trace limitation

The original review identified two real declaration incompatibilities but did not identify an earlier loader fault. The first observable failure in the currently pinned release occurs before catalog assembly: `_catalog_dependencies` unconditionally reads both relationship endpoints' `dataset` keys (`ddk/core.py:36-54`), while the authored external target legitimately contains only `external` (`project.ddk.json:1800-1808`). `load_project` calls that helper and catches `ResourceLimit` and `RegistryError`, not `KeyError` (`ddk/core.py:82-101`). This corroborates the parent's reported `KeyError('dataset')` and explains why neither the repaired application branches nor their assertions have yet run successfully.

The three application repairs do not work around that defect, remove external targets or manufacture a report. Repairing and qualifying a maintained DDK successor remains with the parent release/runtime owner. The source dispositions above are conditional on that owner restoring the real supported catalog path; they are not a full implementation approval.

### Additional small actionable issue

WARNING / error reporting — validate the contextual extension's shape before indexing it. At `archive_definitions.py:132-140`, the new extension values and entries are assumed to be collections and objects with both `position` and `relationship`. DDK intentionally permits arbitrary namespaced extension values (`ddk/resources/schemas/0.1/common.schema.json:37-43`). For example, a contextual entry `{"position": 0}` passes that extension-level schema but raises `KeyError('relationship')`; `recipeContextRelationships: null` raises `TypeError` while the adapter iterates its keys at `archive_definitions.py:227`. Neither becomes the adapter's explicit diagnostic or receives the DDK report because `compile_archive_definitions` only catches `ValueError` (`:125-127`) and the CLI only catches that type (`archive_schema.py:352-355`).

This fails closed and does not publish bad metadata; its impact is a traceback and missing requested error report for a malformed authored mapping. Add narrow object/list/required-member/type validation and raise a clear `ValueError`, with one malformed-record test and one malformed-container test. This is lower priority than the unresolved dependency failure and does not negate the repaired behavior for the supplied valid mappings.

### Re-review verdict

VERDICT: REQUEST CHANGES for integration acceptance; the three original application findings are addressed in source, pending execution through a corrected, qualified DDK release. The new source tests are well targeted and their independent baseline access facts are verified. No new blocking application defect was found in the three repair mechanisms. One smaller extension-shape error-reporting issue remains above.

Confidence: HIGH for the static repair dispositions and baseline-array comparisons. Runtime compiler parity, explicit incomplete-report behavior, native acceptance and publication remain unverified here and cannot be inferred from these source changes.
