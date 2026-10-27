# V6 component lookup repair

Decision: Add only `views(component,name)` to the current renderer staging schema.

Hypothesis: The existing name-first primary key cannot seek by component in the per-document asset lookup. A component-first index should preserve entries and replace the repeated scan with a seek.

Arms: Maintained schema without the index versus the constructor-created index, on the same populated database. Run the actual `_prepare_entries` method in both arms.

Cases: Existing two-document native catalog fixture, 4,096 unrelated membership rows, missing component, and duplicate document assets. Compare query results and complete serialized component entries. Reopen the populated database twice to check idempotent index creation.

Held constant: Database, inputs, assets, SQLite runtime, and query text; disable SQLite statement caching to avoid stale query-plan text. No remote reads or writes.

Decision rule: Adopt if all results match and every component lookup searches the new index without scanning `views`. Use query plans, never a wall-clock assertion in the regression test.

Additional diagnosis: Profile only `publish_selected` while running the maintained `native_viewer_fixture.py`, using its ordinary and giant-document shapes. Record cumulative Python call costs and renderer task durations; profile at most one run per shape and stop within 60 seconds per run. This is an observational check for remaining expensive paths, not an intervention comparison or a production timing estimate. Native calls use the fixture's in-memory test double; import, fixture creation, and native preparation stay outside the profile. Make no further runtime change without separate narrow evidence.

Timing reproduction, declared before running: Reuse the parent's read-only `output/playwright/deployed-explorer-20261026/v6-lookup-diagnostic.py` unchanged against this worktree's source. It extracts the schema and lookup from maintained source, compares 50,000 constructed documents / 100,000 memberships / 1,001 lookups, uses a warm-up and three alternating repeats, and stops within 55 seconds. Require identical results, indexed plans, and every indexed repeat faster than every baseline repeat. Measure index build cost separately; this isolates lookup cost and does not measure constructor-time insertion overhead or total preparation.

## Verified local result

Adopt the one index. The regression test passed with identical serialized entries and query results. Each baseline query scans `views`; each indexed query reports `SEARCH views USING COVERING INDEX views_by_component (component=?)`. Reopening populated staging databases creates the index safely. Other query text and publication logic remain unchanged.

The fresh timing reproduction used Python 3.12.13 and SQLite 3.50.4. Baseline lookup range: 2.2643–2.3044 seconds; median 2.3033. Indexed range: 0.00334–0.00352 seconds; median 0.00342. Index build range: 0.02756–0.02785 seconds. All 1,001 result sets matched. The source SHA-256 was `ef64e9b4c53c47b5df5eb86d605aa75f160b2f5f4c471ec030a68a3d7b4499f0`.

Focused validation: `test_filename_native_indexes.py`, `test_filename_native_sources.py`, and `test_filename_native_upgrade.py`, with `-k 'not actual_native'`: **22 passed, 3 deselected** in 11.94 seconds. The run used this worktree's source directories first in `PYTHONPATH`, the existing Python/Arrow runtime, and a private pytest install under `/tmp/ct-v6-index-test-deps`. The skipped selection comprises the real native-runtime tests; these results establish local fixture behavior, not native or production qualification.

## Remaining preparation cost

The profiles used the maintained fixture with seven source rows and six components. Its giant-document case has 18,000 occurrences in document `A`, occupying 27,167,699 logical Arrow bytes. Each shape ran once with Python profiling enabled; timings include profiling overhead.

| Profiled measure | Ordinary fixture | Giant document |
| --- | ---: | ---: |
| Complete renderer | 0.2384 s | 2.6049 s |
| Component registration | 0.00072 s | 0.00081 s |
| Component entries | 0.00052 s | 0.00051 s |
| All document chunks | 0.01890 s | 2.38582 s |
| `publish_occurrence_assets`, cumulative | 0.031 s | 2.394 s |
| In-memory native read calls | 6 | 62 |

The giant case spends 1.797 seconds in `publish_observations` (including 0.863 seconds in full readback verification) and 0.581 seconds in `publish_occurrence_parquet`. `observation_value` runs 54,018 times; the maintained publisher, verifier, and export each traverse occurrences. Python value-size estimation accounts for 1.098 cumulative seconds. These overlapping cumulative times must not be added together. The ordinary fixture instead spends 0.183 seconds on the one-time renderer requirements hash.

Interpretation: occurrence-heavy rendering is a plausible remaining cost worth measuring after production stage timing is available. These fixture results do not justify another index, removing verification, changing the memory budget, or altering occurrence output. The retained production artifact contains no accepted preparation or stage progress, so it cannot identify the stage that hit the three-hour limit. Native I/O and real catalog shapes are absent from this profile.

The prior read-only SQL audit covers all 18 `NativeComponents` read/update queries. Other point lookups already use keys; remaining full-output sorts run once. The earlier `member_ids(id,source_id)` experiment made load-plus-read slower for both tested shapes. Keep that index out.

## Evidence and integration

Preserved local raw evidence: `/tmp/ct-v6-index-lookup.py`, `/tmp/ct-v6-index-lookup.json`, `/tmp/ct-v6-index-profile.py`, and `profile.json` under `/tmp/ct-v6-index-profile-ordinary/` and `/tmp/ct-v6-index-profile-giant/`. The profile wrapper measures only `builder.publish_selected`, times `NativeComponents._task`, records native-read deltas, and then invokes the maintained fixture through `runpy`; its JSON records imported module paths and the top 45 cumulative calls. Run it once per shape with `FILENAME_FIXTURE_GIANT_DOCUMENT=1` for the giant case. Retained parent evidence remains in the primary checkout's `output/playwright/deployed-explorer-20261026/`.

Only the schema line, focused regression test, and this note changed. `publish_selected`, CLI/workflow behavior, and remote state remain outside this repair. Because renderer requirements hash the implementation, this index changes that hash: an existing v6 publication still needs the maintained explicit renderer upgrade. The public v5-to-v6 preparation, durable checkpoints, stage timing, and the first production publication require integration with the other repairs and new production evidence.

## Follow-up: continuation capacity blocks a full release at this size

Verified mechanism: v6 inventory pages hold at most 64 references, but `publish_viewer_r2.prepared_files` expands every reference into a file dictionary. `attempt.prepare` then gives all issued file proofs to `Continuation.phase`. That method expands them into `hashes` and rejects a total over `MAX_PHASE_FILES=32768`; paging the public inventory does not reduce this count (`filename_native.py:832`, `publish_viewer_r2.py:194`, `attempt.py:108`, `continuation.py:197–215`).

The retained deployed v5 manifest reports **1,241,157 entries**. A full initial v6 build at that count requires at least **19,394 browse leaves plus 19,394 component leaves = 38,788 distinct files**, before branches, source assets, occurrence assets, inventory pages, and controls. Browse leaves hold at most 64 rows; native component leaves hold at most 64 identities, and the renderer emits one component leaf per selected native leaf (`BrowsePages.__init__`, `BrowsePages._groups`, `CatalogComponents._members`, `NativeComponents.plan`, `NativeComponents.finish`). The two leaf kinds contain different JSON and distinct document membership. More generally, any full build above 1,048,576 documents exceeds the phase cap through these two leaf sets alone. Exact selected native counts should still be checked at integration; the retained v5 count is not a newly fetched native selection.

Independent upload blocker: every immutable asset uses `GuardedPublicationClient.put_object`, which records an intent and successful verification through `DurableJournal`. Verified writes remain in `Continuation.value['writes']`. `apply_event` refuses a new key after **8,192** retained writes. The separate **16,384-event** durable-journal cap also remains active; batching some verification facts does not remove the write cap (`client.py:176–218,224–240`, `continuation.py:105,457–474`). A single fresh full-release attempt cannot upload even the minimum browse leaves under these budgets.

Bounded local reproduction used the real functions and unchanged limits: `write_inventory` / `iterator_inventory` successfully represented **32,769 dummy asset references in 513 pages**, enumerating **33,282 total references**. `validate_state` refused 32,769 phase files with `Publication continuation exceeds phase file limit`; `apply_event` accepted and verified 8,192 unique writes, then refused the next intent with `Publication continuation exceeds write limit`. Dummy references exercise metadata paging only, never file-proof validation. No payloads or remote objects were generated. Raw harness and results: `/tmp/ct-v6-scale-budget.py` and `/tmp/ct-v6-scale-budget.json`.

Finding: **a definite capacity mismatch for a full release at the retained catalog size**, separate from the observed preparation timeout. No limit changed. Continuation/journal repair is outside the assigned schema/query scope and requires parent coordination with the checkpoint task. Before another full preparation, size the accepted-file and write evidence against the actual selected counts and all byte/event budgets, preserve resumable exact-byte verification, and add bounded boundary checks. Raising only `MAX_PHASE_FILES` leaves the upload blocker intact; raising only `MAX_WRITES` leaves phase and journal limits intact.
