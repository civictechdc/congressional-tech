---
id: ct-c5xf
status: open
deps: [ct-73oe]
links: []
created: 2026-10-30T14:10:02Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-082q
tags: [html-metadata, extruct, congress-api, content]
---
# Use publisher-marked article and testimony content for cleaner text

The audit found 4,180 bodies with RDFa article content, including Veterans Affairs testimony pages. Current text can include navigation and other page-wide material.

User value: cleaner testimony text and useful previews, with fewer navigation words in downstream reading and analysis.

Evidence: docs/experiments/extruct-metadata-20261030/report.md and summary.json. Full extraction and comparison artifacts are under output/extruct-metadata-20261030/ (local, Git-ignored); preserve portable fixtures and manifests needed for tests rather than relying solely on these local paths.

## Design

Owner: congress_api HTML/archive parsing. Treat content:encoded and equivalent explicit article-body properties as main-content candidates. Compare them with the existing extraction before choosing one. Retain original HTML and the exact body/property selector; produce safe text rather than executing or directly rendering publisher markup. Preserve paragraph order and document links where applicable.

Keep title, short publisher description, and full article text distinct. Boilerplate, empty, partial, nested, or contradictory annotations need an explicit fallback. Store large extracted content through an existing retained/derived-content mechanism with a typed reference, not in every browser browse row. This task does not introduce a full-text search service.

## Acceptance Criteria

- A recorded representative cohort covers marked testimony, ordinary articles, multiple content candidates, boilerplate, malformed markup, and unannotated pages.
- Side-by-side review shows the selected content removes unrelated navigation without omitting testimony; failures retain the existing fallback and are counted.
- Original source bytes and exact selection evidence remain accessible. Text is safe for display and preserves meaningful order.
- Report candidate/selected/fallback counts and output sizes; presence of RDFa alone is not counted as an improvement.
- Publishable content references and bounded snippets are available to downstream mapping without duplicating full text across document rows.

