# Metadata-node proof and byte-cache reuse

Baseline: local `7242f0419f589ffcf9e52f5f5068fb4edd5b6c44`. The implementation is the commit containing this note. This changes local viewer preparation only; it does not publish or select remote objects.

`ViewerAssets.put_node` now consumes the `VerifiedFile` returned by the maintained renderer copier and calls `require(destination)` to check current process/inode/size/mtime/ctime custody. It avoids immediately hashing that fresh destination again. Existing destinations and direct writes still undergo `file_identity` admission, and copied bytes still receive their independent streaming hash.

`read_node` caches `(immutable bytes, verified digest, byte count)` in the existing 16-entry cache. It compares each supplied reference against the cached facts. Every call still parses a new mutable JSON object; callers do not share parsed objects. Acquisition buffers are detached before hashing/caching, and size mismatches refuse before hashing.

## Measured operation counts

Same 41-byte fixture and metadata-only instrument from the prior read-only validation:

| Operation | Baseline | Implementation |
|---|---:|---:|
| Fresh retained-node SHA passes | 3 (address, copy, destination) | 2 (address, copy) |
| Fresh retained-node bytes hashed | 123 | 82 |
| Destination file_identity after fresh retained copy | 1 | 0 |
| SHA passes across three reads of one node | 3 | 1 |
| Bytes hashed across those reads | 123 | 41 |
| Physical reads / JSON parses across those reads | 1 / 3 | 1 / 3 |

Plain nonretained creation remains at two SHA passes. An existing destination still gets independently hashed. These are deterministic tiny-fixture counts, not throughput measurements or production speedup claims.

Baseline evidence: `/Users/mikewolfd/Work/congressional-tech/output/duplication-validation-20261026/index/probe-02.log`. Current raw instrument output: `/tmp/ct-metadata-node-counts.json`; instrument and retained logs are under this worktree's `output/metadata-node-reuse-20261026/`. The instrument uses original methods with counting wrappers; it does not substitute a copier or parser implementation.

## Regression evidence

- Existing baseline source/index/upgrade checks: **23 passed, 5 skipped** (`/tmp/ct-metadata-node-baseline.log`).
- New regression checks before implementation: **8 passed, 4 expected failures** (`/tmp/ct-metadata-node-before.log`): duplicate operation counts, mutable acquisition buffer, and expected custody-specific refusal. Preserve this record rather than treating newly specified behavior as a pre-existing passing baseline.
- Focused implementation checks: **45 passed, 5 skipped** (`/tmp/ct-metadata-node-regression.log`). Covers node proofs/cache, source routes, indexes, bounded browsing, initial resume, and abrupt worker exit during node/file copying.
- New dedicated checks preserve collision rejection, supplied-reference validation, fresh-reader corruption refusal, independent parsed results, exact-copy custody failure, copy-error propagation, and 16-entry eviction/reload behavior.

Run from the checked-out source root using the existing read-only shared runtime, with this checkout's sources first:

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/tmp/ct-v6-index-test-deps:packages/viewer_publication/src:packages/congress_api/src:packages/congress_shared/src:packages/docspec_client/src:packages/house-naming/src:packages/congress_api/tests:packages/viewer_publication/tests:tests:scripts/publication:scripts \
/Users/mikewolfd/Work/congressional-tech/.venv/bin/python -m pytest -q -p no:cacheprovider \
  packages/viewer_publication/tests/test_metadata_node_reuse.py \
  packages/viewer_publication/tests/test_filename_native_sources.py \
  packages/viewer_publication/tests/test_filename_native_indexes.py \
  packages/viewer_publication/tests/test_filename_native_upgrade.py \
  packages/viewer_publication/tests/test_filename_initial_resume.py \
  packages/viewer_publication/tests/test_filename_browse_pages.py
```

The five skipped cases require an explicitly qualified native CLI absent from this worktree. No native build, install, remote request, full-catalog release, push, merge, deployment, or public-pointer mutation was performed. Root integration remains separate.
