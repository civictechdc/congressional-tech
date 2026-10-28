# Bounded component-scope metadata prefetch

Base: `2ccb994329a5aec5a08d00456755547378e57033`. Candidate `filename_native.py` SHA-256: `c2911097094893195680ceea810b5db21285df2298bf9347a6db188153765363`. Independent review approved the change. The existing live container and its frozen source were untouched.

Fresh component planning now uses one six-worker pool for verified routing metadata. Each worker owns an existing `RoutingPages` reader; `MetadataObjects` still checks exact key, size and digest, and routing checks still validate version/prefix/basis. At most six direct children are submitted together. Their validated pages pass directly into recursive planning, so successful traversal still reads each node once. All leaf-membership checks, deterministic sorted traversal and SQLite mutations stay on the caller thread. Incremental planning chooses the original serial path once at public entry, including newly added descendants.

The batch completes before recursive staging, pending work is cancelled on failure, and the sole executor joins before failure escapes. Consumed pages are cleared. Six workers does not mean only six retained pages: ancestor sibling batches remain across at most 64 hash-prefix levels (at most six results per level). Existing JSON expansion, transport buffering and store-cache limits remain; this is not a hard six-MiB process-memory claim or a new corpus cache.

## Bounded real metadata comparison

Used the source selection already recorded in the retained local release check: selection SHA-256 `97e2ff1b675d11ba2dc6f4c9a9e25182474fa47060bc48b7913b358ffde841b8`. The selected catalog counts are 1,241,157 document rows and 1,683,430 source rows. Its component leaves allow at most 64 members, giving a minimum 19,394 component leaves; the actual total routing-node count was not enumerated.

The sample is the same 16 direct routing children under prefix `00`, totaling 59,294 encoded bytes. These are small branch metadata pages, not a representative full payload/leaf distribution. Baseline calls the maintained serial `RoutingPages._read`; candidate calls its actual `_scope_batch`, which delegates to the same maintained verified reader in independent worker instances. Reader caches are fresh per arm; client, references and credentials are held constant. Retries were disabled. No remote write API was invoked.

| Comparison | Serial seconds | Parallel seconds | GETs per arm |
| --- | ---: | ---: | ---: |
| Initial AB pair |1.5065|0.4189|16|
| Reversed BA pair |1.6144|0.4098|16|
| Final tested source pair |2.2118|0.5842|16|

Each arm returned the identical ordered result digest `e3d41dc0742ad55f97aced578c5a270bc7dc0860d1f78217e2b24221267729ba`. The final pair reduced this sample's wall time about 74% (3.79×), with unchanged request count. Total collection was exactly 100 GETs: four discovery requests plus six 16-node arms, touching 20 unique already-selected objects. Existing private credentials were read in-process and never printed or retained in results.

The first ABBA comparison measured the candidate prefetch helper before a caller-handoff edit was corrected. The initial regression caught duplicate caller reads and retained its failed log. The helper was unchanged; the final 32-GET pair pins the corrected, tested full source hash above. No failed result was relabeled as passing.

## Verification and reproduction

Focused run: **79 passed, two skipped, in 15.96 seconds**. The skips require the qualified native CLI on this host; they were not weakened. New cases cover exact SQL/output/order and request-count equivalence, peak concurrency≤6, serial changed/unchanged incremental scope, digest/fetch refusal with rollback and joined workers, and empty child routes. Maintained publication-attempt tests exercise real preparation callers.

```sh
export PYTHONPATH="$PWD/packages/house-naming/src:$PWD/packages/committee_meeting/src:$PWD/packages/congress_shared/src:$PWD/packages/docspec_client/src:$PWD/packages/youtube_api/src:$PWD/packages/congress_api/src:$PWD/packages/viewer_publication/src:$PWD/packages/corpus_recovery/src:$PWD/packages/news_lake/src:$PWD/apps/committee_youtube/src:$PWD/packages/congress_api/tests:$PWD/packages/viewer_publication/tests"
PYTHONDONTWRITEBYTECODE=1 /Users/mikewolfd/Work/congressional-tech/.venv/bin/python -B -m pytest -p no:cacheprovider -q packages/viewer_publication/tests/test_component_scope_prefetch.py packages/viewer_publication/tests/test_viewer_publication_attempt.py packages/congress_api/tests/test_native_catalog_selection.py packages/congress_api/tests/test_catalog_coalesced_batches.py
```

Raw decisions, scripts, selected immutable objects, measurements, final-pair receipt and failed/successful logs remain in this owned worktree's `output/component-scope-prefetch-20261027/`. `measure.py` ran the initial ABBA comparison; `measure-final.py` used only the remaining 32 GETs and the already retained references. No further R2 acquisition is needed to inspect the evidence.

## Operational decision

The measured gain justifies this narrow code change for the next freshly qualified preparation. It does not establish a whole-release speedup or a remaining-time estimate: the live stage exposes no safe committed node numerator, and this sample covers only small branch reads. Without another reason to restart, the evidence alone cannot prove restarting beats finishing existing work. The integration coordinator separately reported a required file-proof guard repair and fresh execution identity; combine the two fixes before that mandatory fresh attempt. Do not hot-patch or restart the existing container based on this note. This branch performs no merge, push, release or deployment.
