---
id: ct-28tj
status: open
deps: [ct-4kuo]
links: [ct-m704, ct-krdp, ct-082q]
created: 2026-11-05T23:51:58Z
type: feature
priority: 2
tags: [mcp, mcp-research-20261105, mcp-proposal-014, search-retrieval]
---
# Return stable citations for PDF pages, caption cues, and witness statements

Use the existing release-bound document references, PDF page and offset results from [ct-o7t4](ct-o7t4.md), selected testimony from [ct-082q](ct-082q.md), and cue timing from [ct-4kuo](ct-4kuo.md). Give researchers a consistent way to cite and reopen a passage.

## Acceptance Criteria

- Return a stable source reference and an appropriate location for a PDF page, a timestamped caption or transcript cue, or a witness statement. Carry release and body identity where available, plus the witness occurrence when the source supports that association.
- Reuse existing source and body identities across text retrieval and search results. Define how a reference resolves against its pinned release and reports an unavailable or different source.
- Round-trip one reference of each supported kind to the original evidence. Reuse the passage check in [ct-082q](ct-082q.md) when the locator is unchanged. Check a changed body, an ambiguous witness match, and a missing source so references retain their original meaning.

