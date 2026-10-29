# Bounded component proof-page prefetch

Base: `26e4105f1308f74930d9e6227137848345142492`. Registration now groups its existing `ORDER BY page,id` cursor into at most six proof pages, each admitting at most the maintained 64-member limit. Independent maintained readers fetch and validate those pages concurrently. The caller checks each component's staged page binding and still calls `CatalogComponentReader.read` for every component before performing the unchanged SQLite writes in their original order.

`CatalogComponentReader.page(..., remember=False)` retains all identity and page validation while avoiding new insertions into the global parsed-page cache. Its default remains unchanged. Registration passes each validated page directly to component reads, so cold successful traversal fetches each distinct proof page once. Existing schema/chunk/store caches remain in effect. At most six prefetched pages and 384 staged member references are retained per batch; consumed pages/groups are cleared. This is not a whole-process RSS or transport-buffer guarantee.

Read failures cancel pending futures; the sole executor joins on all exits, including per-component validation errors. No worker touches SQLite. No live container, frozen source, corpus acquisition, remote write, push or deployment was used.

## Evidence

**87 passed, two qualified-native-CLI skips, in 17.29 seconds.** Independent review approved the code and tests. The 450-component synthetic fixture spans more than six proof pages, allowing refill behavior to be checked. It proves exact serial-versus-parallel SQL writes/results and GET-count parity, one GET per proof page, peak read concurrency greater than one and at most six, and no new global parsed-page retention.

The tests explicitly remove `PYTEST_CURRENT_TEST` and cover both issuer-verified and unissued production branches. The unissued branch executes all 450 full component validations. Fixture-mode tests reject digest damage, fetch errors, staged-page mismatch, a 65-member group and invalid per-component validation counts, preserving accepted SQLite contents and leaving no active workers. A separate check preserves the page reader's default cache behavior.

The first fixture attempted one 450-row physical chunk and correctly hit the existing 256-row budget. It was corrected to supply bounded chunks without changing that budget; the failed log remains alongside the successful log under `output/component-proof-prefetch-20261027/` in the owned worktree.

Focused command, using checkout-local package and test roots in `PYTHONPATH`:

```sh
PYTHONDONTWRITEBYTECODE=1 /Users/mikewolfd/Work/congressional-tech/.venv/bin/python -B -m pytest -p no:cacheprovider -q packages/viewer_publication/tests/test_component_proof_prefetch.py packages/viewer_publication/tests/test_component_scope_prefetch.py packages/viewer_publication/tests/test_viewer_publication_attempt.py packages/congress_api/tests/test_native_catalog_selection.py packages/congress_api/tests/test_catalog_coalesced_batches.py
```

No live proof-page timing or full-release speedup is claimed. This implements bounded overlap for the identified cold serial page reads; physical chunk reads, component validation and SQL work remain unchanged. Integrate with the pending custody repair before creating the next fresh preparation identity.
