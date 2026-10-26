# Journal evidence writes, 2026-10-26

The journal now writes and syncs each request payload once. After a successful
conditional upload, its accepted evidence name links to the already saved file.
Both the nonce-bound request and accepted event remain available under their
existing names. The cloud event format and recovery rules stay the same.

Previously, `DurableJournal._append` wrote identical bytes to
`journal-intents/<sequence>-<nonce>.json` before the request and
`journal/<sequence>.json` after acceptance. Each save performed a file sync.
The first name preserves uncertain-request evidence; the second records acceptance.
Those separate meanings require separate names, but do not require separate copies
of the same data.

`Continuation.save` now returns the existing shared atomic writer's `VerifiedFile`
receipt. Acceptance checks that receipt's file identity before creating a hard link.
This detects a changed request file without rereading its contents. Link creation
cannot overwrite conflicting accepted evidence. Equal separately extracted files
remain valid, so artifact copy and recovery do not depend on hard-link preservation.
Directory-sync behavior is unchanged from the existing evidence saves.

Measured local comparison against `61d0e2f29f08c0ca2c486528883af02df278c966`,
using 20 real journal appends, real atomic saves and real file syncs:

| Measurement | Before | After |
| --- | ---: | ---: |
| Payload writes | 40 | 20 |
| Payload bytes written | 13,842 | 6,921 |
| File syncs | 40 | 20 |
| Evidence names | 40 | 40 |
| Distinct evidence files | 40 | 20 |

The comparison excludes attempt initialization and counts application payload bytes,
not filesystem metadata or storage-device writes. It establishes a 50% reduction
in these payload writes and file syncs; it does not establish production speedup.

Focused tests cover sync-before-upload, failed sync before remote mutation,
interruption before upload, interruption after cloud acceptance, failure while
linking accepted evidence, copied artifacts, changed request files, conflicting
local evidence, complete-prefix corruption refusal, and competing runners.

Validation command, from this worktree:

```sh
PYTHONPATH=packages/viewer_publication/src:packages/congress_shared/src:packages/congress_api/src /Users/mikewolfd/Work/congressional-tech/.venv/bin/python -m pytest -p no:cacheprovider packages/viewer_publication/tests/test_publication_state_bounds.py packages/viewer_publication/tests/test_viewer_publication_attempt.py packages/viewer_publication/tests/test_publication_capacity.py packages/viewer_publication/tests/test_checkpoint_costs.py -q
```

The unchanged baseline state/attempt suites passed 72 tests. The final four suites
passed 92 tests, including the bounded 100,000-upload interruption/recovery exercise
and the 262,657-event completion-order case. Those scale exercises count local
evidence operations rather than performing hundreds of thousands of file syncs;
the 20-event comparison and focused journal tests perform actual local writes.

Integration needs: retain the three `accept_saved` mocks in the existing capacity
harness, which intentionally does not create per-event files. The parent task owns
upload success/readback policy and write reconciliation; this change does not alter
those paths. Hard-link support is required within an attempt directory. If linking
fails, the cloud prefix and original request remain available for explicit recovery.
No production build, cloud upload, publication, push, or deployment was performed.
