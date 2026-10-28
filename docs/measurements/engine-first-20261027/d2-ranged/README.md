# D2 ranged raw readings

The producer uses the existing `R2Store` and read-once worker. Each GET is
conditional on the selected physical object's captured stored MD5, or its exact
listed ETag when captured MD5 is absent. Opaque and multipart ETags remain
versions, not checksums. Range responses must
match the requested interval and captured total size. Pages use bounded full
prefetch or complete the existing disjoint ranges, then verify the decoded
SHA-256 before parsing. Successful input caches are removed after the readings
append returns; pending and failed inputs retain their evidence.

Local checks cover fake SDK responses and five owner-fetched parent bodies
(52,942 stored bytes). They do not qualify a live R2 run, corpus parity, or
nightly memory use. The five bodies are portable fixtures under
`packages/congress_api/tests/fixtures/ranged-parent-bodies/`.

## Required owner inputs

`codex-raw/run2/d2-ranged/full.spec.json` remains gated on an accepted D1 captures
pin and the complete native body listing. The stopped D1 proof did not create an
accepted captures generation. Do not substitute a partial inventory or the old
readings cache. The engine owner's maintained adapter supplied
`$COORD/shared/body-listing-28f59cf4/listing.parquet`: 1,343,571 unique keys,
with unchanged `key`, `size` and `etag` fields. The producer reads this directly
through native SQL; it does not parse the original LIST JSON.

The spec requires `captures` (a native table pin or Parquet input),
`body_inventory` (selected Parquet inventory, or `null` for direct listing),
`local_root`, a fresh `work` directory,
`decided_at`, `parser: null`, and
`apply: {"catalog_root": "...", "table": {"namespace": ["..."], "name": "..."}}`.
The readings table must exist. The ranged path does not read `local_root`.
The inventory has one selected physical object per body, with fields
`body_sha: FixedSizeBinary(32)`, `physical_key: Utf8`, `relative_path: Utf8`,
`stored_bytes: Int64`, and `stored_gzip: Boolean`.
`stored_gzip` describes actual storage encoding, not the filename suffix.
Stored MD5 and size come from captures grouped by the exact SHA and suffix.
Native selection considers only capture-recorded copies, in bare, `.gz`, `.pdf`
order. An absent or conflicting copy falls back to the next recorded copy,
using that copy's own size and version. No verifiable copy leaves the body
pending. A supplied selected inventory remains authoritative; it receives only
exact-key listing enrichment. No suffix supplies a different suffix's checksum.

The intended owner catalog is under `codex-raw/run2/rebuild-885/catalog`, with
the readings location `tables/readings_v1_g20261028_885`. These paths do not
establish an accepted captures pin or table identifier.

## Owner commands

From the raw worktree, with `COORD` and `RAW` set to their protocol scratch
directories and the accepted spec written, run the metadata-only plan first:

```sh
DOCSPEC_JOB_CONFIG="$COORD/shared/engine-b2fd2d8/narrow.runtime.json" \
  .venv/bin/python -I -m congress_api.cli.readings \
  --spec "$RAW/run2/d2-ranged/full.spec.json" \
  --mode backfill --plan --batch-size 32 \
  --raw-bucket congressional-tech-raw \
  --body-listing "$COORD/shared/body-listing-28f59cf4/listing.parquet" \
  --raw-cache-bytes 4294967296 --raw-get-workers 64
```

Planning creates no raw SDK client and performs no body GET. Its `raw_custody`
report counts missing physical objects, captured MD5s and stored sizes for bodies
that need reads. `capture_md5` and `listing_etag` distinguish the selected pin's
source; `missing_pins` counts bodies still requiring custody. `md5_conflicts`
and `size_conflicts` describe a selected-copy contradiction;
`fallback_missing`, `fallback_conflict` and `fallback_pin` count rejected copies
by reason before a usable choice, or all rejected copies if none is usable.
`capture_conflicts` counts contradictory facts within a selected captured copy.
The exact native coverage query is the `raw_custody` query in
`<spec.work>/plan/job.json`; the complete selected facts are in
`<spec.work>/plan/work-list.parquet`. Execution refuses missing pins before any
body GET. The owner approved this exact-key listing fallback; no checksum is
guessed and no unrecorded copy is selected. Known oversized page
decisions that require no GET are excluded from this read-custody count.

After the owner accepts coverage and supplies a fresh spec work directory,
the live command is:

```sh
DOCSPEC_JOB_CONFIG="$COORD/shared/engine-b2fd2d8/narrow.runtime.json" \
  .venv/bin/python -I -m congress_api.cli.readings \
  --spec "$RAW/run2/d2-ranged/full.spec.json" \
  --mode backfill --execute --batch-size 32 \
  --raw-bucket congressional-tech-raw \
  --body-listing "$COORD/shared/body-listing-28f59cf4/listing.parquet" \
  --raw-cache-bytes 4294967296 --raw-get-workers 64
```

This second command is owner-gated: credentials are runtime environment only,
and terminal parser failures can append unreadable provenance to raw storage.
The 4 GiB cache budget leaves room within the agent scratch limit; GET
concurrency is capped at 64. This cache limit is distinct from the owner's process-memory guard.
The owner must run it under the approved process-memory and disk monitoring.
Re-entry reads the current readings table and makes a new work list; retained
cache files are evidence, not a resume journal.

A prefix-only body with gzip bytes and no storage-encoding observation remains
pending when its full object exceeds the prefix already held. The execution
report counts these as `ambiguous_gzip`; it emits no settled format or unreadable
decision and fetches no additional bytes. If the entire object already fits in
the prefix, its SHA can distinguish original from storage gzip without another
GET. Resolving larger ambiguous bodies requires an owner-approved fact source
or additional-read budget. The listing's suffix alone is not that fact.

Main's 491,699 old reading parts are only a format-comparison oracle. They are
never work-list or readings inputs. Full format comparison remains owner-gated
until the raw rebuild has accepted inputs and completes.
