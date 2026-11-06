# Archive publication and shared write boundaries

`archive_model_job` prepares the document model and resumes an original pinned
request. DDK owns the dataset definitions; `archive_format` binds them to accepted
native exports and writes separate release controls. `archive_publish` verifies
the exact accepted file inventory and retains conditional upload and pointer
reconciliation. External activation through `archive_publish_job` is unavailable
until the shared runtime supports a frozen publication intent.
`archive_maintenance` retains the release inputs and receipt pins.

The site reads these files through `apps/site/src/components/explorer/reader/archive.ts`.
Fixtures exercise the same current catalog reader. The old preparer, schema
registry, model checkpoint journal and daily checkpoint import are retired.

The `client` namespace firewall and shared constants stay available to kept
consumers. `require_publication_client` requires mutation retries to be disabled.
The raw continuation, durable journal, local event log and reconciliation helpers
remain unchanged, with their custody, byte limits and refusal tests.

`review_provenance` converts the pinned published review selections into raw review
records. It reads the canonical files under `data/`; `filename_review_binding`
still validates their identities. The old public review staging and viewer export
are retired. Recovery labels enter the model as raw records.
