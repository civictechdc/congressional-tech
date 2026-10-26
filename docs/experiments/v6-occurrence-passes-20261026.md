# One occurrence traversal for browser and Parquet assets

The native viewer previously traversed selected occurrences three times: browser
asset generation, its source comparison, and flat Parquet export. Browser and
Parquet generation now share each decoded observation. Browser verification
compares the generated local files with a framed SHA-256 fingerprint computed
during generation, so it does not reopen native occurrences. The explicit verifier
still accepts an existing source and independently checks its generated assets.

The flat exporter and the combined native path use the same occurrence writer.
Null rows, empty rows, null observations, owner IDs, occurrence order, duplicates,
Unicode, row slices, browse ranges, schemas, compression and output bytes remain
unchanged in characterization tests. Streaming typed parts are never collected
into a whole native occurrence list. The existing Parquet row-group buffer remains
limited to 16,384 observations; this change introduces no whole-source cache.
A focused test also exercises seven-row groups across ten typed source parts.

A source-leaf row-count check now uses the already-open Parquet footer instead of
decoding source columns again. Details already admit and read every source row.
Details and facets retain their existing physical-reader admission paths; removing
those reads would need a maintained in-memory source interface rather than an
adapter pretending to have physical Parquet metadata.

## Executed checks

Baseline focused suite: 40 passed, one native-binary qualification skipped.
Final suite: 120 passed, three native-binary qualifications skipped, 18.53 seconds.
The following command used the shared dependency environment with this worktree's
modules explicitly first on `PYTHONPATH`:

```sh
PYTHONPATH=packages/viewer_publication/src:packages/congress_api/src:packages/congress_shared/src /Users/mikewolfd/Work/congressional-tech/.venv/bin/python -m pytest -p no:cacheprovider packages/viewer_publication/tests/test_filename_observations.py packages/viewer_publication/tests/test_filename_exports.py packages/viewer_publication/tests/test_filename_native_sources.py packages/viewer_publication/tests/test_filename_decoded_budget.py packages/viewer_publication/tests/test_filename_details.py packages/viewer_publication/tests/test_filename_native_upgrade.py packages/viewer_publication/tests/test_filename_native_recoveries.py -q
```

The combined test opens each of six source owners once and produces byte-identical
browser and Parquet assets to the separate maintained publishers. The giant typed
sequence test opens 40 parts once, previously twice for browser publication alone.
Corruption tests reject changed values, reordered references, null/empty changes,
and trailing rows with the streaming fingerprint, without reopening the source.
Existing decoded-byte admission and failure tests pass. `git diff --check` passes.

These are local tests. No production build, memory benchmark, upload, deployment,
remote pointer change or native-binary qualification was performed. Object upload
acceptance and routine remote readback removal belong to the separate client work.
