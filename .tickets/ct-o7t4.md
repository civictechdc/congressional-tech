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

Owner: packages/viewer_publication/src/viewer_publication/archive_model.py (and/or companion text export) and apps/explorer_mcp/src/congressional_explorer_mcp/{release.py,reader.py,server.py,models.py}.
1. Architectural & security constraints to preserve (identified by Red/Green Team review):
   - apps/explorer_mcp/src/congressional_explorer_mcp/worker.py:16-18, 43 hard-disables all network sockets inside the query worker subprocess (socket.create_connection = _offline) and reader.py:75 sets SET enable_external_access=false.
   - server.py:50-51 and tests/test_cli.py:27 enforce openWorldHint=False once a release is prepared locally.
   - readings in the lake only stores text_head (not full page text), and apps/explorer_mcp/pyproject.toml depends only on duckdb and fastmcp (with no PDF parser library).
2. Preferred implementation path (Option B — Offline Optional Companion Parquet + Title Enrichment):
   - Publish a compact optional companion Parquet table (e.g. document_text.parquet or texts.parquet in release.py:OPTIONAL, keyed by list_row / saved_body with page/offset text or extracted testimony passages from readings / ct-c5xf / body store) so the air-gapped DuckDB Reader worker can serve get_document(section='text') / substring or FTS snippet queries 100% offline with openWorldHint=False and zero PDF parsing dependencies in explorer_mcp.
   - In addition, in archive_model.py title selection, enrich generic PDF metadata titles ('Witness Statement', 'Testimony', 'Prepared Statement', 'Witness Biography', 'Truth in Testimony') with the linked witness's name (when len(witness_keys)=1 after ct-2o4d) so document browse/search listings are self-descriptive.
   - (If Option A on-demand archive_origin fetching is ever used as a fallback when no companion Parquet is installed, the HTTP fetch and SHA-256 verification against detail.saved_body must run in the parent server.py process outside the air-gapped Worker, with explicit opt-in configuration.)

## Acceptance Criteria

- Given a valid document reference (release_id, link_key), the MCP can return bounded page/offset text or keyword/regex snippets from captured PDF/HTML/text bodies after verifying the body SHA-256 against detail.saved_body.
- Unverified URLs, mismatched SHA-256 digests, oversized decompression streams, and unsupported binary formats fail closed with a clear ExplorerError.
- Response payloads respect MAX_BYTES and worker timeout guarantees, covered by unit and fault-injection tests.

