---
id: ct-csjp
status: closed
deps: [ct-vt7i]
links: [ct-mi03, ct-a1aa, ct-gf8i, ct-vt7i, ct-gziq, ct-n6lj, ct-jo8n]
created: 2026-10-20T20:37:00Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, news-lake, refresh, aggregation, join]
---
# Support CollectSet aggregates and nested Struct/List<Struct> JoinField projections

Two native relational gaps in `docspec-rs` force Python-side workarounds in `packages/news_lake/src/news_lake/storage/docspec_backend.py:25-32`:

1. **`CollectSet` aggregate absent**: `AggregateFunction` (`docspec-rs/src/model.rs:321-331`, `src/engine/aggregation.rs:36-45,112-160`) supports only `CountRows`, `Count`, `CountDistinct`, `Sum`, `Min`, and `Max`. Because there is no set-collection aggregate (`ARRAY_AGG(DISTINCT field ORDER BY field)`), `DocSpecNewsViews._assemble_coverage_daily` (`docspec_backend.py:831-866`) must re-read `survivor_items` into Python to compute `identical_text_group_ids`.
2. **Nested `Struct`/`List<Struct>` `JoinField` projection gap**: `DocSpecNewsViews.SELECTED_MENTIONS_SCHEMA` (`docspec_backend.py:628-636,663-667,774`) serializes `occurrences` (`list<struct<field, start, end>>`) to a JSON `pa.string()` column before the native `politician_articles` join and parses it back with `json.loads` because `Selection::new` (`src/storage/selection.rs:80-85`) and `plan_files` (`src/storage/schema.rs:81-92`) only push top-level `field.id`s into `task.project_field_ids` (whereas `iceberg-rs` `ArrowReader` requires descendant leaf field IDs when projecting nested columns) and multiset verification (`src/engine/refresh.rs:1002`, `src/engine/changes.rs:280`) must support nested projected columns.

## Design

1. Add `AggregateFunction::CollectSet { field: String }` to `src/model.rs` and `src/engine/aggregation.rs`, compiling to deterministic non-null `ARRAY_AGG(DISTINCT <field> ORDER BY <field>)` over qualified scalar fields (`Utf8`, `Int32`, `Int64`, `Date32`) and preserving incremental affected-key recomputation and contributor evidence.
2. In `src/storage/selection.rs:80-85` and `src/storage/schema.rs:81-92`, recursively collect all descendant field IDs for selected `Struct`/`List` root fields into `task.project_field_ids`, and ensure `join_queries`, `verify_related_with_inputs` (`src/engine/refresh.rs`), and `verify_native_changes` (`src/engine/changes.rs`) preserve and verify nested `Struct` / `List<Struct>` `JoinField` projections in full and incremental `Refresh`.
3. Update `DocSpecNewsViews` in `packages/news_lake/src/news_lake/storage/docspec_backend.py` to keep `selected_mentions.occurrences` as a native `list<struct>` column and compute `identical_text_group_ids` natively in `coverage_daily`.

## Acceptance Criteria

- Full and incremental `Refresh` in `docspec-rs` pass with `AggregateFunction::CollectSet` (covering nulls, duplicates, empty groups, and deterministic element ordering) and with `Struct` / `List<Struct>` columns in `JoinField`.
- `DocSpecNewsViews.politician_articles` and `DocSpecNewsViews.coverage_daily` in `packages/news_lake/tests/test_docspec_backend.py` pass without JSON string serialization of `occurrences` or a secondary Python scan for `identical_text_group_ids`.

## Notes

**2026-10-20T22:19:32Z**

Fresh source review at engine9661026: CollectSet is still absent. Application adoption is ct-gf8i. Root nested JoinField payload copying already exists; qualify reader/refresh field-ID behavior before assuming a blanket projection gap. Preserve global distinct-item repetition across dates when listing coverage text groups; per-day CollectSet alone changes meaning.

**2026-10-20T22:24:50Z**

Final static review through native 22a804e: CollectSet is implemented for local Refresh with sorted unique non-null values and empty-list output. New tests were inspected, not run in this review. App ct-gf8i still needs intended-backend qualification and corpus-wide repeated-group parity; implementation presence is not adoption.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch mi03a).
- Grades: proposal 88 → 88, work 84 → 84.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
