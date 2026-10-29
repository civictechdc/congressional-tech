# B0 old-writer repair and receipt cleanup release

All 2,289 receipt files (2,596,054 lines) passed the five-step rewrite on scratch copies. The final full scan found zero targeted header or local-path occurrences. No bucket was accessed, and the source cache was read only. This qualifies the tool locally; the live cleanup and lock remain owner actions.

The source was the existing `r2-immutable/receipts` mirror under the primary checkout's `.cache/docspec-catalog/`. Its complete, fixed inventory was copied into scratch before the accepted scan. An earlier scan started during copying was interrupted and excluded.

| Measurement | Result |
|---|---:|
| Original compressed bytes | 1,082,812,244 |
| Changed receipts | 887 |
| Header removals | 1,138,754 |
| Local-path removals | 1,549,970 |
| Pointer-protected local keys requiring refusal | 0 |
| Cleaned compressed bytes | 948,672,297 |
| Initial scan | 458.75 seconds; 5,258,313,728 bytes peak RSS |
| Rewrite, backup and readback verification | 2,483.89 seconds; 6,084,034,560 bytes peak RSS |
| Final scan | 434.65 seconds; zero matches |

These are measurements on this Mac, not qualification of the Linux 16 GB runner. Each scan streams lines, but one unusually large JSON line and its parsed copies determine peak memory. The scan report groups identical JSON paths, keeping at most three safe examples per field. This bounds report growth by fields rather than occurrences; it does not bound an individual line.

`scan.json` contains counts by field and safe examples for the owner's pattern decision. Header values are never reported. `receipt-identities.json` records each original and cleaned local file identity, size and verification result. `verification-summary.json` holds machine-readable totals. Raw receipts, private backups and detailed verification logs remain in scratch.

The focused cleanup, privacy, probe and pipeline contracts pass: 56 tests. At the public-writer change, the complete production-offline lane had exactly the same 33 failures and three setup errors as the initial baseline: 11,318 passed versus 11,296 initially. See the scratch ledger for full logs and exact failed-test identities.

## Standalone release and checks

Branch `release/b0-old-writers`, worktree `/Users/mikewolfd/Work/wt/ct-release-b0`, starts at shared `origin/main` `7411f5b7`. Maintained source comes from integration `ef66bb97`; the legacy emission repair is the two-call-site change from `d306f02a`. Capture and recovery apply one shared privacy helper before storing public receipts. The release keeps the original writer inputs intact.

A forward review fix makes backup file contents and all directory entries durable before replacement; a sync failure blocks the live write, including a retry that finds a previously linked backup. **52 focused tests pass**, covering both writer emission points, conditional replacement, backup/readback, crashes, races, inventory and final rescan. The larger historical local qualification above remains historical evidence; it was not repeated for this release and no real storage was accessed.

```sh
cd /Users/mikewolfd/Work/wt/ct-release-b0
uv sync --locked
.venv/bin/python scripts/dev.py test production-offline \
  --path packages/congress_api/tests/test_receipt_cleanup.py \
  --path packages/congress_api/tests/test_public_receipts.py \
  --path packages/corpus_recovery/tests/test_public_recovery_receipts.py \
  --path packages/corpus_recovery/tests/test_import_corpus_recovery_batch.py \
  --path packages/corpus_recovery/tests/test_native_import_preservation.py \
  --path packages/corpus_recovery/tests/test_verify_corpus_recovery_import_preservation.py
```

The owner's [ordered checklist](../owner-raw-safety.md) gives push/merge, drain, inventory, cleanup, final coverage verification, receipt lock and stop commands. Run this release's commands from the worktree above after `uv sync --locked`. Keep private backups on a durable disk independent of scratch. No native runtime configuration is needed for these focused checks or the cleanup CLI.

## Owner procedure

First confirm both patterns in `scan.json`: recorded authorization/cookie headers and absolute local paths, with URLs and pointer targets protected. Deploy the patched old writers and drain their prior revisions; pause recovery imports and the weekly raw writer for the cleanup window. Use a dedicated cleanup credential, supplied outside this report.

Run from `/Users/mikewolfd/Work/wt/ct-release-b0`. Set `B0_WORK` to a private, durable owner directory with enough room for originals and the final mirror. The following commands are prepared, not executed against live storage:

```sh
.venv/bin/python -I -m congress_api.cli.receipt_cleanup --bucket congressional-tech-raw --list-inventory --inventory "$B0_WORK/keys.json" --report "$B0_WORK/listing-before.json"
.venv/bin/python -I -m congress_api.cli.receipt_cleanup --bucket congressional-tech-raw --inventory "$B0_WORK/keys.json" --backup-root "$B0_WORK/originals" --scratch "$B0_WORK/work" --records "$B0_WORK/verification.jsonl" --report "$B0_WORK/rewrite.json" --apply
```

The rewrite verifies the backup's size and MD5 before conditional replacement, reads back every changed receipt, preserves URLs, full `links` values and pointer targets, and records every receipt, including unchanged ones. Uncut lines keep their exact bytes. It refuses concurrent changes. A rerun uses the durable verification log; after a crash following replacement it reconciles against the original backup. Live verification records are batched under `provenance/verification/`.

Pause capture before the final listing and keep it paused until the lock is read back. Repeat the rewrite with the final inventory to cover receipts added during cleanup, then download and scan every final receipt:

```sh
.venv/bin/python -I -m congress_api.cli.receipt_cleanup --bucket congressional-tech-raw --list-inventory --inventory "$B0_WORK/final-keys.json" --report "$B0_WORK/listing-final.json"
.venv/bin/python -I -m congress_api.cli.receipt_cleanup --bucket congressional-tech-raw --inventory "$B0_WORK/final-keys.json" --backup-root "$B0_WORK/originals" --scratch "$B0_WORK/work" --records "$B0_WORK/verification.jsonl" --report "$B0_WORK/final-rewrite.json" --apply
.venv/bin/python -I -m congress_api.cli.receipt_cleanup --bucket congressional-tech-raw --scan-live --inventory "$B0_WORK/final-keys.json" --mirror-root "$B0_WORK/final-mirror" --report "$B0_WORK/final-scan.json"
```

Require zero matches, one verified record for every final key, and agreement between the final listing and verification identities. Only then lock `receipts/` indefinitely and read the rules back. B3 is built on the integration branch: `BodyStore` and its R2/local adapters serve the new raw writers (BIND §3.1, inspected at `ef66bb97`). This standalone B0 release ports the public-receipt repair into the two running legacy writers and retains the cleanup's conditional replacement as its separate one-time adapter. Deploying B0 does not deploy the integration branch.

Release review: the semi-formal code review approved the package after the backup-durability correction (`01594e57`, `35914df5`); no BLOCKER or CONCERN remains. Correction to the latter commit's body: `receipt_cleanup_stores.py` is **87 → 104** lines, as the committed file shows.
