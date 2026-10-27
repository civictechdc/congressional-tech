# Published assistant reviews: local provenance stage

All 86 pinned published reviews were converted by the native SQL job into `kind_override` decisions on their bodies' stable link keys. The five unsupported-form annotations retain their published selected kinds. The stage contains 86 assistant-authored records, 46,169 bytes, SHA-256 `d758fbf294458dadea7f4c3f803da50ff8597454ddf8e828865defe15b8f2407`. The explicit migration decision time is `2026-10-27T14:12:48Z`; no historical review time was invented.

Source `reviews.json` is 292,002 bytes, SHA-256 `322869766390f46a26bb9b430ac020c13152283c08c959d1aab549ae2a24066e`. The descriptor and all 86 identity rows match its catalog and review pins. Native joins verify one-to-one identity/body matching before provenance is staged. The job used the immutable shared engine at source `adabc57681a83600504a909b254ae2e4febe07a7`; this is local source qualification, with no live import.

The immutable handoff is `codex-coord/shared/raw-reviews-a1b8bfe0/` under the coordination scratch root. `manifest.json` pins the inputs and provenance bytes; `reviews.parquet` and `jobs/` retain native output and SQL evidence. Engine reads that provenance root during E4 parity.

Local staging command, from this worktree (`B8_STAGE` must be a fresh owner directory):

```sh
.venv/bin/python -I -m viewer_publication.review_provenance --reviews /Users/mikewolfd/Work/congressional-tech/apps/site/public/data/document-reviews/reviews.json --stage "$B8_STAGE" --decided-at 2026-10-27T14:12:48Z --native-config "$DOCSPEC_JOB_CONFIG"
```

After E4 parity and from a clean application checkout, the owner imports the reviewed immutable stage. `B8_STAGE` can point to the shared handoff above; inspect first, then apply:

```sh
.venv/bin/python -I -m congress_api.cli.provenance --stage "$B8_STAGE"
.venv/bin/python -I -m congress_api.cli.provenance --stage "$B8_STAGE" --bucket congressional-tech-raw --apply
```

The apply command verifies staged hashes, record counts and record fields before resolving a clean HEAD/lockfile writer identity or connecting to storage. It creates one `provenance/reviews/` object through the common body store. A reused object key fails; nothing is overwritten. The owner preserves the command's writer identity output with the import receipt.

Focused native B7/B8 tests: 9 passed. Package import fences: 22 passed. The implementation commit body said three fence tests; the retained runner log and ticket correction give the actual 22. No PDFs, credentials, live storage or network writes were read or used for this measurement.
