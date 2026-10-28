# Retain completed recovery metadata admission

This follow-up to `8d46ba4c` retains the completed selected-table metadata index
across a later native open, timeout or truncated stream. Native payloads and
recovery results are still rebuilt through their maintained validation paths;
only completed metadata admission is reused.

The retained 32-page replay admitted 2,048 components / 2,766 logical source rows
in **1.354 seconds**, then deliberately failed at the native read boundary. Retry
verified the 16,977,920-byte database and reached that same boundary in
**0.022 seconds**, with zero metadata admissions or component binding checks.
These are one local checkpoint comparison, not a full production runtime claim.
The complete recovery JSON from the shared four-source / three-document fixture
was byte-identical to the prior baseline after a deliberately truncated native
stream and a successful retry.

## Exact reuse boundary

`SelectedCatalogTable.iter_batches(admission_directory=...)` is opt-in. Its
ordinary callers retain temporary selected metadata. `NativeCatalogSnapshot.table`
supplies a private copy of the exact selected source identity and component root.
Recovery preparation supplies the path only when it has an owned
`preparation_binding`; the private directory is a sibling of its publication
output, normally `publication.recovery-admission/`.

The original metadata admission statements were moved intact into `_admit`.
Fresh builds still validate every component binding, schema, ownership, physical
chunk identity and complete logical row count before native data is delivered.
An independent reviewer compared their syntax trees against the previous commit
and confirmed equivalent statements apart from SQL whitespace.

The completed checkpoint consists of `admission.sqlite` and `complete.json`:

- A fresh SQLite index builds in a private `.building-*` directory. Validation,
  commit, close and file fsync precede its atomic rename into place.
- A maintained streamed file identity supplies the database size and SHA-256.
  The shared atomic JSON writer publishes and syncs `complete.json` last.
- The receipt binds exact selected source/component root, full logical schema
  digest, label, row count, ordered-read bound, validator/runtime requirements,
  and implementation digests for admission, partitions and immutable metadata.
- Reuse checks that binding, database size and SHA-256 before opening SQLite
  read-only with `query_only=ON`. Maintained file custody checks surround its
  lifetime. It does not query or reuse a concurrently active operational DB.
- A nonblocking private-directory lock covers both building and consuming the
  checkpoint. Symlink directories/files and competing owners refuse.

An interrupted build has no completion marker. Receiptless orphan data is never
read as admission: a fresh build runs all original checks. A completed checkpoint
with a missing, changed, corrupt or mismatched file/receipt refuses; it is not
silently repaired or migrated. The completion marker covers metadata only and
never represents completed native rows or a completed recovery output.

## Verification

**98 tests passed; 11 qualified-native-runtime tests skipped.** Cases include:

- Failure before native open and after partial Arrow delivery; the next reader
  skips component enumeration/admission and produces the same rows and order.
- Recovery-level failure followed by reuse, with exact canonical JSON bytes.
- Partial metadata interruption, absent completion and fresh orphan replacement.
- Changed source, schema, row count, implementation policy or version type;
  same-size file corruption, truncation, missing files and symlinks.
- Concurrent ownership refusal and unchanged default temporary behavior.
- Owned preparation alone choosing the private sibling directory.
- Prior cache, transient exact-pin GET retry, native stream, initial recovery,
  schema refusal and preparation tests.

```sh
PYTHONPATH=packages/viewer_publication/src:packages/congress_api/src:packages/congress_shared/src:packages/docspec_client/src \
  /Users/mikewolfd/Work/congressional-tech/.venv/bin/python -m pytest \
  -p no:cacheprovider \
  packages/congress_api/tests/test_selected_admission_checkpoint.py \
  packages/congress_api/tests/test_catalog_coalesced_batches.py \
  packages/viewer_publication/tests/test_initial_recovery_scan.py \
  packages/viewer_publication/tests/test_native_preparation.py \
  packages/viewer_publication/tests/test_native_recovery_budget.py \
  packages/viewer_publication/tests/test_filename_native_recoveries.py \
  packages/congress_api/tests/test_docspec_host.py -q
```

[Replay result](recovery-admission-checkpoint-20261027/result.json),
[script](recovery-admission-checkpoint-20261027/replay.py),
[recovery bytes](recovery-admission-checkpoint-20261027/recovery.json), and
[source hashes](recovery-admission-checkpoint-20261027/source-hashes.json) retain
bounded evidence. The replay uses only retained local immutable metadata and
previously generated private native Arrow fixture bytes. Real payload delivery
is deliberately stopped at a fake native boundary in the metadata comparison;
the private recovery replay tests real maintained parsing over fixture Arrow.
No new provider downloads occur.

The independent review approved the completed-admission boundary, original
validation, binding/hash/custody checks, locking and recovery-only wiring. Review
was static; the owner ran the focused tests and private replay. No operational
runtime, checkpoint, source receipt or worker was changed. Parent owns source
installation and the compatibility helper for the final producer pin.
