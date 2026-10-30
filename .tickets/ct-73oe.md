---
id: ct-73oe
status: open
deps: []
links: []
created: 2026-10-30T14:10:02Z
type: feature
priority: 1
assignee: mikewolfd
parent: ct-082q
tags: [html-metadata, extruct, congress-api, parsers]
---
# Add a shared extruct reader that preserves metadata and partial failures

Congressional page readers currently preserve only selected metadata and raw JSON-LD text. Add a reusable reader for all six extruct formats plus the generic head tags outside extruct's coverage.

User value: richer source descriptions and update information remain recoverable even when one metadata format is malformed.

Evidence: docs/experiments/extruct-metadata-20261030/report.md and summary.json. Full extraction and comparison artifacts are under output/extruct-metadata-20261030/ (local, Git-ignored); preserve portable fixtures and manifests needed for tests rather than relying solely on these local paths.

## Design

Owner: packages/congress_api. Add parsers/html_metadata.py and an explicit source result model; integrate through the existing committee-page and archive readers instead of duplicating extraction logic. Pin the tested extruct version in the package/lock and include the relevant code, dependencies, and options in the reader fingerprint.

Retain raw values, ordering/multiplicity, declared base, generic meta/link fields, and format-specific status/errors. Keep existing structured_data/raw_html compatibility. Preserve literal relative URLs in body-level output; resolution is contextual. Extruct is an implementation dependency, not the public model. Reuse existing supervised worker limits; capture failure must not erase successfully read formats or prevent raw retention. Include a cheap marker check only if tests establish it cannot suppress supported metadata.

## Acceptance Criteria

- Retained fixtures exercise JSON-LD, Microdata, Open Graph, Microformats, RDFa, Dublin Core, generic head tags, and repeated Open Graph keys.
- Valid formats survive malformed neighboring formats; absent, failed, and skipped formats remain distinguishable. Include the audit's recursion/timeout cases or minimal reproductions tied to original hashes.
- Non-HTML and error responses are not admitted as substantive page metadata solely because extraction returns values.
- Unknown properties and original values remain available; no remote vocabulary/context fetch is required.
- Consumers share the reader, existing source fields remain readable, and dependency/fingerprint checks prove changed extraction versions cannot masquerade as earlier results.

