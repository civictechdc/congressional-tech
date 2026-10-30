---
id: ct-pocg
status: open
deps: [ct-73oe]
links: []
created: 2026-10-30T14:10:02Z
type: feature
priority: 1
assignee: mikewolfd
parent: ct-082q
tags: [html-metadata, extruct, congress-api, retention]
---
# Retain versioned HTML metadata and selectively replay saved bodies

Metadata improvements should benefit historical captures without another publisher crawl or a full archive rebuild.

User value: historical records improve faster and at lower processing cost, while the evidence behind prior results remains available.

Evidence: docs/experiments/extruct-metadata-20261030/report.md and summary.json. Full extraction and comparison artifacts are under output/extruct-metadata-20261030/ (local, Git-ignored); preserve portable fixtures and manifests needed for tests rather than relying solely on these local paths.

## Design

Owner: congress_api/lake/readings.py, its reading schema, parser-version calculation, and the maintained retention interfaces. Append versioned extraction results through the existing bounded workers and immutable storage. Plan work by body hash plus extractor version. Preserve raw literal URL values and resolve separately for each capture URL/base context, so identical bytes under different URLs do not acquire the wrong links.

Extend existing schema/version handling rather than adding a parallel metadata store. Keep format-level partial results and error codes. Work from a frozen selection with explicit counts of missing bodies, excluded formats, error pages, and completed/partial readings. Reuse owned local verified bodies and measure actual reads/reprocessing; do not equate selective inserts with a selective job.

## Acceptance Criteria

- Unchanged body/version pairs are reused; an extractor change selects the intended HTML bodies without rereading unrelated PDFs, transcripts, or source families.
- A fixture with identical HTML at different capture URLs resolves relative links correctly while sharing body extraction; missing context remains unresolved.
- Interrupted work resumes without duplicate readings, deleting originals, or replacing unrelated versions; older schema parts remain readable.
- A selected retained replay records body hashes, reader versions, completeness, partial-format failures, bytes read/downloaded, elapsed time, and peak resource use under existing limits.
- No publisher refetch is necessary for available retained bodies; unavailable body references are reported as gaps, never successful empty extraction.

