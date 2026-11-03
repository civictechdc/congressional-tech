---
id: ct-o7t4
status: open
deps: []
links: [ct-jnm9, ct-93zs, ct-m104, ct-c5xf]
created: 2026-11-03T01:00:04Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-m104
tags: [mcp, documents, text, search, phase2]
---
# Add bounded document body text reading and snippet search to Congress Explorer MCP

In the double-blind MCP evaluation (.cache/chaos-double-blind-20261102T2304Z/report.md), all 5 investigative briefs achieved 100% metadata accuracy (294/294 verified claims) but every single brief terminated at 'partial' completeness because the MCP server only exposes metadata ('This server searches metadata; it does not read document bodies', server.py:35). Once an agent locates the exact witness statement PDF, committee report, or CHRG-* hearing transcript via search_documents / get_entity, it receives only a saved_url pointing to a raw .pdf or .gz object in R2 and cannot read or search inside the testimony text to answer substantive questions (e.g. comparing SBF vs. John Ray testimony, Boeing whistleblower claims, or VA scientific posture on burn pits).

## Design

Owner: apps/explorer_mcp/src/congressional_explorer_mcp/server.py, reader.py, models.py, and (optionally) companion text/snippet export from readings / ct-c5xf.
1. Add a bounded read_document_text (or get_document section='text' / snippet query) capability to Congress Explorer MCP that resolves a published document reference (release_id, link_key) to its verified saved_url (or pinned local/companion extracted text from readings/ct-c5xf), verifies the SHA-256 digest against saved_body, extracts/decompresses text safely in the worker subprocess, caches extracted text in a size-bounded local cache directory, and returns page-bounded text or regex/keyword match snippets within MAX_BYTES.
2. Enforce strict security and resource invariants: only fetch/read SHA-256-verified bodies belonging to the selected release's archive_origin; enforce timeouts, decompression bomb caps, and MAX_BYTES truncation flags; never execute publisher markup.

## Acceptance Criteria

- Given a valid document reference (release_id, link_key), the MCP can return bounded page/offset text or keyword/regex snippets from captured PDF/HTML/text bodies after verifying the body SHA-256 against detail.saved_body.
- Unverified URLs, mismatched SHA-256 digests, oversized decompression streams, and unsupported binary formats fail closed with a clear ExplorerError.
- Response payloads respect MAX_BYTES and worker timeout guarantees, covered by unit and fault-injection tests.

