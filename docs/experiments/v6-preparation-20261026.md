# V6 preparation lookup diagnostic

Historical diagnostic recorded before the repairs were implemented. Its runtime
and workflow limitations describe that initial snapshot. See
[the integrated repair report](current-explorer-repairs-20261026.md) for the
subsequent implementation and verification.


Decision: Determine whether one SQLite index is a justified, narrow candidate for speeding up current filename viewer preparation.

Hypothesis: The per-document lookup in `NativeComponents._prepare_entries` scans the `views` table because its primary key starts with `name`. An index starting with `component` should replace that scan with a keyed lookup. A plan without a scan or no repeatable timing improvement weakens the hypothesis.

Arms: Current source schema and exact lookup versus the same schema and lookup with `CREATE INDEX views_by_component ON views(component, name)`.

Cases: Constructed 50,000-document membership fixture with one document chunk and one filename chunk per document, coalesced into groups of 512. Compare all returned values for 1,000 deterministic document lookups and a missing document. This fixture tests lookup mechanics, not production data or total preparation time.

Held constant: Same Python/SQLite runtime, data, query, cache budget, and lookup order; three alternating repeats, one warm-up per arm. Stop within 60 seconds or 100 MiB of owned evidence. Extract schema and query directly from the maintained source; no remote reads or writes.

Decision rule: Recommend the index as a candidate only if query plans show indexed access, all results match, and every indexed repeat is faster than every baseline repeat. Otherwise report the uncertainty. Never extrapolate the measured lookup speedup to the full release.

Evidence: `output/playwright/deployed-explorer-20261026/v6-lookup-diagnostic.json`.

Harness correction: The first run exposed stale cached `EXPLAIN QUERY PLAN` text after dropping the experimental index. Preserve that run as `v6-lookup-diagnostic-initial.json`; repeat with Python's SQLite statement cache disabled in both arms. The data, query, criteria, and repeat counts stay unchanged.

## Result

The corrected comparison met the decision rule. The current query scans the `views` primary-key index; the candidate searches `views_by_component` by component. Every returned value matched, including the missing-document case.

Across three measured repeats, the median for 1,001 lookups was 2.2413 seconds with the current schema and 0.00324 seconds with the extra index. Baseline range: 2.2247–2.3090 seconds. Indexed range: 0.00323–0.00328 seconds. Creating the index cost 0.0264–0.0280 seconds. The fixture has 50,000 documents and 100,000 membership rows. This confirms an avoidable repeated scan; it does not identify the stage reached by the timed-out production job or predict complete-release duration.

The maintained `test_filename_native_upgrade.py` resume/corruption subset also passed: 5 passed, 9 deselected. Those tests cover the existing renderer-upgrade path. Initial v5-to-v6 preparation still cannot use that path, and the workflow only retains complete accepted preparation assets. Neither runtime code nor workflow configuration changed in this investigation.

## Follow-up: other indexes

Decision: Decide whether `member_ids(id,source_id)` deserves inclusion alongside the missing component lookup index.

Hypothesis: The existing `(id,source_order)` primary key bounds each membership lookup but needs a separate sort for `ORDER BY source_id`. A covering `(id,source_id)` index should remove that sort; maintaining it may cost more than it saves for mostly singleton groups.

Arms: Existing schema versus one additional index created before loading membership rows, matching a simple constructor change.

Cases: Constructed small-group fixture with 25,000 groups and 34,000 total members; separate 500-group fixture with 200 members per group. Read every group in both orders used by the renderer and compare result digests. Extract both queries from current source. These cases describe shapes, not observed production frequency.

Held constant: Same schema, data, insertion order, Python/SQLite runtime, and cache size; three alternating repeats per case. Measure load and read costs separately and together. Stop within 60 seconds. No network or publication writes.

Decision rule: Recommend unconditional inclusion only if the total load-plus-read time improves in every pair for both shapes and results match. Otherwise classify it as conditional or unnecessary. Inspect query plans for the other repeated lookups; do not recommend indexes solely to remove one-time full-output sorts.

### Follow-up result

Do not add the membership index for this release on the current evidence. It removed the per-group source-ID sort and preserved all values, but loading and reading the table together took longer in every paired repeat. Median totals were 0.13659 → 0.13972 seconds for small groups and 0.14598 → 0.17657 seconds for large groups. These in-memory fixture results include maintaining the additional index during insertion; they do not establish production timing or rule out a later measured benefit from building an index after loading.

The query-plan audit covered all 18 SQL read/update statements in `NativeComponents`. Its other point lookups use existing keys. The remaining unindexed sorts (`components` by page/id, `chunks` by label/name, and final browse rows by filename/id) traverse whole output sets once. Adding indexes for those is not justified by this diagnostic. Observation deduplication, observation ID reads, recovery spill ordering, and renderer progress/asset lookups already use primary keys. Native recovery URL membership uses the existing hash routing rather than a missing SQLite URL index.

Follow-up evidence: `output/playwright/deployed-explorer-20261026/v6-other-indexes.json` and `v6-sql-query-plans.json`. Runtime and workflow changes remain unimplemented.
