# Meeting state: setup and recovery

The weekly commands read and update `meeting-inventory/house.json.gz`,
`senate.json.gz` and `inventory.json.gz` on the `pipeline-data` branch. They
contain parsed records and availability observations. Code, small test fixtures
and derived tables stay on `main`; full state files do not.

## Use the latest snapshot

The workflow checks out `pipeline-data` before running the three commands.
There is no separate bootstrap copy step. For a local replay, extract the
current snapshot into a new directory without changing an existing checkout:

```bash
git fetch origin pipeline-data
meeting_replay_dir="$(mktemp -d)"
git archive FETCH_HEAD | tar -x -C "$meeting_replay_dir"
```

Pass `$meeting_replay_dir/meeting-inventory` as `--state-dir`, its
`congress_meetings.jsonl.gz` as `--meetings`, and its `youtube` directory as
`--tinydb_dir`. Use a separate output directory. The app README lists the
three commands; add `--offline` when rebuilding from saved observations only.

If state is lost, restore a retained snapshot. If none is available, run the
same commands with an empty state directory to fetch the source data again.
The optional `--seed-cache ~/hearing-text` imports retained research caches
read-only. A complete backfill can take substantial time; an incomplete
backfill fails rather than publishing partial output.

For a manual state migration, wait until the update workflow is idle and base
the replacement snapshot on the latest remote `pipeline-data`. Preserve every
unrelated file, validate the new state, and push with an explicit
`--force-with-lease` against the remote commit that was read. A changed remote
requires rebuilding from its new snapshot. Do not run the normal force-push
helper from a stale local data checkout.

## Initial seed provenance

The seed was generated on 2026-09-27 from read-only `~/hearing-text` research
caches, the `a1705b6` meeting/GPO/YouTube inputs and the production parsers.
It contains no raw HTML, XML, PDFs, caption text or credentials. Imported
records use the import date as `checked`; the research cache did not retain
individual HTTP receipts. House `urls` are recovered address candidates;
subsequent live fetches keep the successful address.

| File | Bytes | Contents |
|---|---:|---|
| `house.json.gz` | 3,099,441 | 5,741 meetings: documents, witnesses, amendments, XML update marker and absence state |
| `senate.json.gz` | 10,451,839 | 21 sites, 4,925 pages: listings, parsed page lines, witnesses, documents and event matches |
| `inventory.json.gz` | 276,778 | 2,137 MODS witness lists, eight PDF witness lists, 3,268 archive probe answers and caption observations |

Total: **13,828,058 bytes**. Snapshot
`5b23ff54d7274c66045db52c8e57487b003fec50` adds only these three files to the
tree of remote snapshot `55fa0d791ec0c43c215483acb649ffb7b37deb02`. Like other
data snapshots, it has no parent. Later weekly runs replace the branch tip;
use the latest snapshot for ordinary operation.

Initial SHA-256 digests:

```text
c153d5de6900e6c65ee0f185cd728cbac1696270ec783787cfedf5b15baae4a3  house.json.gz
553d27db6c5b0f1ad1df5bc70e66e778215b1c53ef38f541fa6da06b97d813c8  senate.json.gz
08eaf00da10c4d93b49565d149f8ddacb890db3b954113dba32f3ca51d058f2f  inventory.json.gz
```

The six reader tables reconstructed from the seed matched the research tables
at `a1705b6` byte for byte. The [verification report](production-verification.md)
records the inventory's intentional differences and replay commands.


## Acquisition boundary

`congress_api.acquisition.gaps` owns late witness PDF/MODS fetches and
Senate day probes. The join calls these functions explicitly; source parsers stay
in `parsers.witness_pdf`. Tests pass `get=` directly without changing the CLI.
See the [per-command offline matrix](../congress-api-contracts.md#offline-behavior)
for saved-state requirements, seed imports and failure behavior. Offline mode
still reads inputs and writes deterministic state and derived CSVs.
