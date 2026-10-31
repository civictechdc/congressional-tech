---
id: ct-1xt0
status: open
deps: []
links: [ct-m103, ct-m104]
created: 2026-10-31T00:05:23Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-m104
tags: [mcp, relationships, discovery, chaos-test]
---
# Expose bill-linked hearing transcripts through published relationship recipes

search_documents(query={measure_key:"119-hr-1", document_kind:"published-hearing"}) returns zero rows in the retained release, although meeting 118300 has subject_keys=["119-hr-1"] and links transcript CHRG-119hhrg61207 at list_row 145163 (document reference a80bbbc83acf1c12). The document has meeting_keys=["118300"] and measure_keys=[].

A bounded bill -> meeting -> transcript query succeeds today. The existing bill_documents recipe checks only list.measure_keys despite its broad title, "Documents related to a bill". This is a discovery/semantics limitation, not evidence that the direct-filter implementation should invent document annotations.

Diagnosis: source revision 052b6111cb816b81446cf29b7b2d82aad5517d05; retained release 0db23484fe86c7f5a5e50e44f078ec34e74e793873b26c4a15f0b9e9efa17b69. Local evidence: .cache/chaos-mcp-20261030T233124Z/diagnosis/report.md and its probe files. That ignored local directory may not exist in another checkout; the decisive reproduction is included below. Tests establish local source behavior, not current public-pointer or installed-package behavior.

## Design

Owner: producer-owned model/registries/release-schema.json recipes/relationship descriptions, generated docs/release-relationships.md, and MCP tool guidance where needed. Reuse existing meeting_bills, meeting_transcript_documents and document identity relationships; expose the traversal through generic get_dataset_info and query_sql rather than adding a second MCP join registry.

Clarify that the existing measure_key filter and bill_documents recipe use direct document keys. Add a bounded, parameterized recipe using meetings.subject_keys and meetings.transcripts[].list_row to find hearing transcripts associated with a bill. Return one row per unique document, with its distinct supporting meeting IDs, so multiple paths do not duplicate documents or hide why they matched. Use deterministic document and meeting ordering.

Preserve visibility and query limits. Do not copy indirect bill relationships into direct document keys or introduce a new graph system. Missing required tables must remain unavailable rather than look like an empty complete answer. Prove the recipe with a compact native fixture through the actual MCP client before preparing release metadata.

## Acceptance Criteria

- Discovery makes direct-document and meeting-mediated relationships clear; users can find the new recipe from the existing metadata surface.
- The parameterized traversal for 119-hr-1 returns transcript CHRG-119hhrg61207/reference a80bbbc83acf1c12 once, with supporting meeting 118300, on the retained release without altering direct document measure_keys.
- Add maintained fixture cases for a transcript with no direct bill key, repeated paths within one meeting, multiple supporting meetings, a genuinely empty relationship, missing required tables and hidden documents. Return one row per document with unique supporting meeting IDs; preserve deterministic ordering, visibility rules and row/byte limits.
- Preserve direct-filter behavior and clarify its scope; do not infer witnesses or historical completeness from relationship availability.
- Regenerate relationship documentation and execute the discovered recipe through actual stdio MCP against native fixture output. Record source and schema/release identities.
- Reuse the existing metadata-publication path and preserve unchanged Parquet bytes when no data change is required. Distinguish local metadata preparation from delivered/selected release verification.

## Notes

**2026-10-31T00:56:20Z**

Implemented locally: producer-owned bill_hearing_transcripts recipe follows meeting subjects and transcript list_row references. It returns each visible document once with distinct sorted supporting meeting IDs. Updated direct bill recipe descriptions, MCP guidance, and generated docs/release-relationships.md.

Verification: 85 MCP tests and 12 focused publication-schema tests passed. Fixtures cover duplicate paths, multiple meetings, hidden documents, empty matches, unavailable meetings, and row/byte limits. Actual stdio executed all 11 recipes over retained native producer output with refreshed metadata; all 16 Parquet hashes were preserved. No fresh producer data-generation job was run. The new SQL also returned CHRG-119hhrg61207/reference a80bbbc83acf1c12 exactly once for 119-hr-1 on the retained full release, supported by meeting 118300, while the direct document filter remained empty.

Local implementation and verification are complete. Updated discovery metadata still needs publication and selection before existing releases advertise the recipe; no public release or pointer changed. Ticket remains open for delivery. See apps/explorer_mcp/VERIFICATION.md and local .cache/mcp-ticket-fixes-20261030/native-metadata-receipt.json and retained-replay-result.json.
