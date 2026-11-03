---
id: ct-o7t4
status: closed
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

Owner: apps/explorer_mcp/src/congressional_explorer_mcp/{server.py,reader.py,models.py,release.py}, apps/explorer_mcp/pyproject.toml, and packages/viewer_publication/src/viewer_publication/archive_model.py.
1. Architectural & security constraints to preserve (identified by Red/Green Team review):
   - apps/explorer_mcp/src/congressional_explorer_mcp/worker.py:16-18, 43 hard-disables all network sockets inside the query worker subprocess (socket.create_connection = _offline) and reader.py:75 sets SET enable_external_access=false.
   - Therefore, on-demand HTTP fetching of saved_url from archive_origin MUST execute in the parent MCP process (server.py) outside the air-gapped DuckDB query Worker subprocess.
2. User Decision (A1 — Option A Selected):
   - Perform on-demand HTTP fetch of saved_url from archive_origin in server.py (parent process), verify sha256(raw_bytes) == bytes.fromhex(detail.saved_body) before decompressing (.gz) or parsing, and cache extracted text locally under <data_dir>/bodies/<saved_body>.json (or bounded local body cache).
   - Add a lightweight wheel-based PDF parser dependency (e.g. pypdf or pypdfium2) to apps/explorer_mcp/pyproject.toml to extract page-indexed text from verified PDFs, alongside HTML/XML/plain-text extraction for non-PDF bodies.
   - Expose body reading/search through get_document (e.g. section='text' with page/offset/max_chars or query snippet matching) and update server.py instructions + tool annotations cleanly.
   - In addition, in archive_model.py title selection, enrich generic PDF metadata titles ('Witness Statement', 'Testimony', 'Prepared Statement', 'Witness Biography', 'Truth in Testimony') with the linked witness's name (when len(witness_keys)=1 after ct-2o4d) so document browse/search listings are self-descriptive even before fetching body text.

## Acceptance Criteria

- Given a valid document reference (release_id, link_key), the MCP fetches saved_url from archive_origin in the parent server.py process (while keeping Worker air-gapped with socket.create_connection disabled), verifies sha256(bytes) == bytes.fromhex(detail.saved_body), caches extracted text in <data_dir>/bodies/, and returns bounded page/offset text or keyword/regex snippets.
- Unverified URLs (outside archive_origin), missing saved_body digests, mismatched SHA-256 digests, oversized decompression streams, and unsupported binary formats fail closed with a clear ExplorerError.
- Response payloads respect MAX_BYTES and timeout guarantees, covered by unit and fault-injection tests.


## Notes

**2026-11-03T12:48:59Z**

Implemented and verified on r3-mcp / release-train (4d583687): added body_reader.py and get_document(section='text', page, offset, max_chars, query) in parent server.py keeping DuckDB Worker air-gapped, verifying sha256 against detail.saved_body, enforcing _NoRedirectHandler, monotonic deadline + abandon_on_cancel=True, ReDoS/zero-length regex protection, 256-entry cache bound under <data_dir>/bodies/, and generic witness statement title enrichment in document-normalized.sql / document-recovery-normalized.sql.
