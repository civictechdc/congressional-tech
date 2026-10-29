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
