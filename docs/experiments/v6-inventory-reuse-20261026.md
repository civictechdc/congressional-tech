# Viewer inventory handoff simplification, 2026-10-26

## Result

The local inventory path performs fewer repeated filesystem checks while keeping
fresh custody checks at use boundaries. This is local fixture evidence; no
production preparation, upload, publication, or remote mutation was performed.

- `issue_inventory` checks each supplied `VerifiedFile` once. It no longer checks
  the complete inventory again immediately after constructing the issued result.
- Plan acceptance checks the incoming inventory and binds its plan metadata to
  those same issued file facts. `InventoryValidation.bind_context` changes only
  the input binding; it does not reissue or rescan every file. Copied and plain
  dictionary proofs still cannot establish authority.
- `AcceptedViewerPlan.require` still checks the complete current inventory and
  exact plan context. Per-file reads and transfer checks still require custody.
- `verify_prepared` reuses the complete file-name set returned by the publisher's
  existing size-limit traversal, eliminating its second directory walk. Missing
  and additional files still refuse before publication.

## Evidence

Baseline: 42 attempt tests passed in 14.86 seconds. The initial inventory-only
change passed 72 targeted tests in 12.92 seconds. The complete coordinated change
passed 73 targeted tests in 15.04 seconds:

```sh
PYTHONPATH=packages/viewer_publication/src:packages/congress_api/src:packages/congress_shared/src:packages/docspec_client/src:tests /Users/mikewolfd/Work/congressional-tech/.venv/bin/python -m pytest -p no:cacheprovider packages/viewer_publication/tests/test_viewer_inventory_reuse.py packages/viewer_publication/tests/test_viewer_publication_attempt.py packages/viewer_publication/tests/test_filename_native_upload.py packages/viewer_publication/tests/test_native_recovery_preparation.py packages/viewer_publication/tests/test_native_preparation.py -q
```

The added tests establish one file-proof check per inventory member at issuance,
one complete check at plan acceptance plus its manifest read, zero file scans
while rebinding context, and one complete check on later plan use. They cover
same-size corruption, missing and additional files, altered digest facts, altered
plan context, copied inventory objects, and serialized digest dictionaries.

A bounded 13-file fixture measured physical `Path.stat` calls on the inventory
members against the original implementations from HEAD:

| Operation | Original | Changed |
| --- | ---: | ---: |
| Inventory issuance | 104 | 65 |
| Plan acceptance | 147 | 43 |

The measurement harness loaded the original inventory and plan modules with
`git show HEAD:<path>`, used identical issued files and a publisher stub, and
counted only stats on those 13 files. The temporary reproducible harness is
`/tmp/ct-inventory-reuse-measure.py`. These counts isolate inventory bookkeeping;
they do not estimate full publication runtime or remote cost. The committed
regressions count the underlying proof checks directly. Complete prepared-output
verification now performs one publication directory traversal instead of two.

`git diff --check` passed.

## Integration requirement and retained checks

The `attempt.py` change requires the parent's coordinated
`publish_viewer_r2.validate_prepared_output` change: return the set of relative
file names observed by its existing size-limit traversal. All prior size,
control-byte, and manifest checks remain owned there. Verification above used a
temporary copy of the parent's publisher file from
`/Users/mikewolfd/.codex/worktrees/v6-continuation-capacity/congressional-tech`.
That temporary overlay was restored and is excluded from this commit. Integrate
both sides before running the complete changed attempt flow.

Fresh restored artifacts still hash every accepted member. Later preparation
verification still compares complete membership, checks accepted binding and
phase evidence, and checks file custody. Directory membership can change between
traversal and later use, as before; ordinary file checks still catch changed or
missing accepted members. This change introduces no filesystem snapshot or new
concurrency guarantee. The separate size admission before initial phase acceptance
remains because it rejects unsupported outputs before accepting preparation.
