# corpus-recovery

Import name: `corpus_recovery`.

Keep recovered congressional document files in the public archive and add only the new mappings.

Use this after a recovery pass has produced document files. The library classifies the archived HTML, checks that a finished import still holds the previous capture rows and download-state rows, and merges the new mappings into the public list of accepted recoveries.

Seal one local batch with `scripts/prepare_corpus_recovery_batch.py`. Combine finished batches with `scripts/coalesce_corpus_recovery_batches.py`. Check the sealed batch against the stored document files with `scripts/reconcile_corpus_recovery_bodies.py`, import it with `scripts/dispatch_corpus_recovery_import.py`, and publish it with `scripts/dispatch_corpus_recovery_publication.py`.

Those commands live in `scripts/`. The prepare script contains the sealing step. Coalesce, reconcile, import, and publication call this library.
