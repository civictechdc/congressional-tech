# Archive publication and shared write boundaries

`archive_model_job` builds the document model. `archive_release` defines the
release schema and exports the reader files. `archive_publish_job` produces and
checks a release through the engine; `archive_controller` uploads accepted files
and selects the release only after the archive contract and canary pass.
`archive_maintenance` retains the release inputs and receipt pins.

The site reads these files through `apps/site/src/components/explorer/reader/archive.ts`.
The seed and successor fixtures exercise the same reader and release registry.
The old v6 preparer, viewer CLI, upgrade attempt and resume routes are retired.

The `client` namespace firewall and shared constants stay available to kept
consumers. `require_publication_client` requires mutation retries to be disabled.
The raw continuation, durable journal, local event log and reconciliation helpers
remain unchanged, with their custody, byte limits and refusal tests.

`review_provenance` converts the pinned published review selections into raw review
records. It reads the canonical files under `data/`; `filename_review_binding`
still validates their identities. The old public review staging and viewer export
are retired. Recovery labels enter the model as raw records.

## Large release assets

`NativeArchiveStore` keeps small assets and controls on the pinned native
create-only path. Files at least 64 MiB use the existing publication boto3 client
with sequential 8 MiB multipart uploads. SDK mutation attempts remain one.
Completion always carries `If-None-Match: *`; a HEAD-before-write check never
replaces that condition. This applies to derived release assets, including
`search_index.sqlite`; raw body writers keep their existing behavior.

Before any multipart request, a bounded local pass verifies the manifest's
whole-file SHA-256, MD5 and size and computes the expected part checksums.
The upload pass verifies consumed bytes and exact file custody again, supplies
Content-MD5 for each part, and checks returned part ETags before completion.
After completion, HEAD must match the exact size and expected multipart ETag.
Multipart ETags are separate transport facts, never the manifest's whole MD5.

The version 2 asset journal retains that transport plan and exact owned upload
ID/stage. Version 1 native acknowledgements remain valid. A resumed acknowledged
asset uses custody plus HEAD without reopening the payload. Failed parts abort
only their owned upload ID; an unknown completion stays pending until HEAD
reconciles it. Resume closes any remaining owned attempt before acknowledgement
or another conditional attempt. Missing acknowledged objects and changed local
or remote identities refuse. Resume restarts parts rather than continuing them.

The fixed part inventory supports at most 10,000 parts (78.125 GiB). Memory is
bounded by part buffers and metadata; local source verification reads the asset
twice on first upload. Admission must still cover the complete candidate, the
previous release used by comparison, and reader preparation. Comparison hashes
all retained manifest assets, including the previous SQLite index. Omitting it
would remove a custody check. Hosted preparation still needs its own actual
disk, download/hash time and cold-start proof.

The storage-loopback lane tests the real adapter and SDK against a local S3
fake. Provider qualification must separately cover conditional completion,
competing writers, exact readback and owned multipart cleanup whenever that
provider or SDK behavior changes.
