# Repair capacity-test saved-event receipts

Baseline: `fefa92132c59445f9f733f6c24cc5207f7f05536`. Only the capacity test fixture changes; production journal/client/custody code and capacity limits remain unchanged.

The counted `Continuation.save` replacements returned `None`, while durable append now consumes the saved receipt's SHA-256. The repaired fixture issues a frozen, test-only receipt over the exact immutable bytes. Paired acceptance checks receipt identity, source/target sequence names, fake-remote body and size before clearing its single pending receipt. Real restore staging still calls `VerifiedFile.require` on the exact staged source. The fixture intentionally counts append persistence instead of writing/fsyncing every event; small real-file tests qualify that disk behavior.

Both new refusal cases pass: substituting an equal-valued receipt or changing the accepted fake-remote bytes refuses without advancing sequence, byte count, digest or continuation state. Independent static review approved the fixture and its bounded retention.

## Execution evidence

The 100,000-upload interruption/restore/replay case passed. It restored accepted preparation, reconciled the one uncertain outcome, replayed 50,000 payloads without duplicate PUTs, completed 100,002 journal events, and refused late-chain corruption without replacing accepted state. Final state was 73,138,502 bytes; journal history was 75,089,052 bytes; 97 checkpoint calls stayed within the maintained bound. The test body took **97.241 seconds**; the maintained runner took **99.86 seconds**. Peak process RSS was **1,273,987,072 bytes** (about 1.19 GiB).

The worst-case ordering case passed at the full configured **131,328-write** limit, with **153,217 events** and **97,181,183 journal bytes**, preserving all state/count/byte assertions. The maintained runner took **8.38 seconds**; peak process RSS was **399,032,320 bytes** (about 381 MiB). These two cases ran in separate processes; macOS reports `ru_maxrss` in bytes. `/usr/bin/time -l` confirmed the same maximum RSS values; its separate wrapper memory-footprint field is not substituted for test-process RSS.

**All 10 capacity cases passed** across the targeted invocations: the two requested full-scale cases, both added refusal cases, and six remaining capacity/guard cases (six passed, four deliberately excluded because already run, in 3.49 pytest seconds / 5.46 runner seconds). The remaining cases retain count/byte refusal and exercise 100,000 inventory assets with 1,563 pages / 101,563 references. Both added refusal checks passed. Raw full-case, worst-case, refusal, remaining-guard logs and machine-readable `results.json` remain under this worktree's `output/capacity-proof-fixture-20261026/`.

The first maintained-runner attempt stopped at the environment doctor because the shared venv's editable imports pointed at the primary checkout. No test ran in that attempt. Explicit checkout-local `PYTHONPATH` fixed resolution without dependency installation; that failed log is retained as `counterexamples.log`, and the successful retry is `counterexamples-local-paths.log`.

The successful command environment is:

```sh
export PYTHONPATH="$PWD/packages/house-naming/src:$PWD/packages/committee_meeting/src:$PWD/packages/congress_shared/src:$PWD/packages/docspec_client/src:$PWD/packages/youtube_api/src:$PWD/packages/congress_api/src:$PWD/packages/viewer_publication/src:$PWD/packages/corpus_recovery/src:$PWD/packages/news_lake/src:$PWD/apps/committee_youtube/src"
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
```

Each node uses the maintained offline lane and captures macOS resource statistics:

```sh
/usr/bin/time -l /Users/mikewolfd/Work/congressional-tech/.venv/bin/python -B scripts/dev.py test production-offline --path packages/viewer_publication/tests/test_publication_capacity.py::test_full_release_inventory_upload_interrupt_restore_and_replay -- -p no:cacheprovider -s -q
/usr/bin/time -l /Users/mikewolfd/Work/congressional-tech/.venv/bin/python -B scripts/dev.py test production-offline --path packages/viewer_publication/tests/test_publication_capacity.py::test_noncoalesced_journal_accepts_write_capacity -- -p no:cacheprovider -s -q
```

The other focused invocations used the same environment and maintained lane:

```sh
/Users/mikewolfd/Work/congressional-tech/.venv/bin/python -B scripts/dev.py test production-offline --path packages/viewer_publication/tests/test_publication_capacity.py -- -p no:cacheprovider -k counted_evidence -q
/usr/bin/time -l /Users/mikewolfd/Work/congressional-tech/.venv/bin/python -B scripts/dev.py test production-offline --path packages/viewer_publication/tests/test_publication_capacity.py -- -p no:cacheprovider -s -k 'not full_release_inventory_upload_interrupt_restore_and_replay and not noncoalesced_journal_accepts_write_capacity and not counted_evidence'
```

These are synthetic offline metadata/recovery capacity exercises, not a production publication, full release qualification or hosted throughput measurement.
