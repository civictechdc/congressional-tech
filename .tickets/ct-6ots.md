---
id: ct-6ots
status: closed
deps: []
links: [ct-m104]
created: 2026-10-31T00:05:22Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-m104
tags: [mcp, correctness, chaos-test]
---
# Reject lossy numeric coercion in MCP entity lookups and filters

MCP convenience tools accept strings for integer fields and let DuckDB convert them. get_entity(table="meetings", id="118299.9", section="record") returns event 118300; search_entities(table="meetings", filters={"event_id":"118299.9"}) also returns it, and a roster filter congress="118.9" returns Congress 119. This silently rounds an exact identifier/filter.

Identity is then interpreted differently for document lookup: get_entity(table="meetings", id="0118300", section="documents", limit=100) returns zero rows, while the same id resolves the record and canonical id=118300 returns 38 documents in the retained release. Whitespace-suffixed and decimal/scientific spellings reproduce the mismatch. MCP arguments belong inside a query object.

Diagnosis: source revision 052b6111cb816b81446cf29b7b2d82aad5517d05; retained release 0db23484fe86c7f5a5e50e44f078ec34e74e793873b26c4a15f0b9e9efa17b69. Local evidence: .cache/chaos-mcp-20261030T233124Z/diagnosis/report.md and its probe files. That ignored local directory may not exist in another checkout; the decisive reproduction is included below. Tests establish local source behavior, not current public-pointer or installed-package behavior.

## Design

Owner: apps/explorer_mcp/src/congressional_explorer_mcp/models.py and reader.py. EntityQuery.id and EntitySearch.filters accept scalar alternatives; reader.py:243-246 and :268 delegate integer conversion to DuckDB, then :281 reuses str(query.id) for string-key relationships. Pydantic can also coerce a boolean ID to an integer before the reader sees it.

Use one small shared validator against existing published column types. Validate original values before Pydantic or DuckDB can perform lossy conversion. For integer fields, accept integer values excluding booleans and base-10 integer strings; normalize leading zeros and surrounding whitespace, and reject decimal/fractional spellings, scientific notation, booleans and values outside the published integer type's range. Preserve textual identifiers as text and leave ordinary query_sql semantics unchanged.

Use the canonical validated value consistently for record selection, filters and cursor binding. After exact validation, use the stored primary key for related-document lookup. A rounded database match cannot establish valid identity. Reuse maintained validation and existing query paths; avoid a separate SQL parser, type system or identity registry. This fix requires an application release, not republished Parquet.

In addition (from chaos test run `chaos-mcp-20261101T200453Z`, `CT-CHAOS-103` & `CT-CHAOS-104a`), extend the same input validation and canonicalization boundary across `Page`, `SqlQuery`, `DocumentSearch`, and `DocumentQuery`:
1. Validate `Page.limit`, `SqlQuery.limit`, `DocumentSearch.congress`, and `DocumentSearch.include_hidden` using `mode='before'` validators (`exact_scalar(..., 'INTEGER' / 'SMALLINT' / 'BOOLEAN', ...)`) so booleans (`congress=True`, `limit=True`) and floats (`limit=1.0`) are rejected before Pydantic coerces them.
2. Accept `DocumentSearch.meeting_key: StrictStr | StrictInt | None = None` and normalize it via `str(exact_scalar(v, 'BIGINT', 'meeting_key'))` in a `mode='before'` validator so both `meeting_key=118300` and `meeting_key="0118300"` match `"118300"` in `list.meeting_keys`.
3. Normalize `DocumentQuery.link_key` to lowercase hex in its model validator (`v.lower()`) so uppercase hex (`"6EA8C1FAD7D36439"`) matches the lowercase `link_key` stored in pagination cursors for `section="sources"` / `"recoveries"`.
4. **Preserve exact case on general `VARCHAR` entity keys** (`models.py:1,37` `"preserve the published identifier or value exactly"`) so `r3-mcp`'s case-sensitive keys (`videos.video_key = 'youtube:agHearing01'`, `recordings.video_key = 'youtube:dQw4w9WgXcQ'`, `channels.handle = '@AgRepublicans'`, `detail.package_id = 'CHRG-118hhrg1'`) and `query_sql` parity are never corrupted. Either document canonical identifier casing (`lowercase` `system_code`/`bill_id`/`nomination_id`/`witness_key`, `UPPERCASE` `bioguide_id`) in `server.py` tool docstrings, or if field-level case normalization is applied, scope it strictly to the explicit legislative identifier fields (`system_code`, `parent_system_code`, `committee_key`, `bill_id`, `nomination_id`, `measure_key`, `witness_key` -> lowercase; `bioguide_id`, `sponsor_bioguide_id` -> uppercase) without touching `video_key`, `handle`, `package_id`, `record_key`, or `match_id`.

## Acceptance Criteria

- Fractional and decimal integer inputs such as "118299.9", "118.9" and "118300.0", scientific notation, booleans and out-of-range integers return actionable validation errors before lookup across `get_entity`, `search_entities`, `search_documents` (`congress`, `meeting_key`, `include_hidden`), and `Page.limit` / `SqlQuery.limit`. Exercise the actual MCP/Pydantic input boundary as well as the reader.
- Integer 118300 and strings "118300", "0118300" and "118300 " return the same record and related-document set in both `get_entity` and `search_documents(meeting_key=...)`. Accepted spellings use the same canonical value for query and cursor binding.
- Uppercase `DocumentQuery.link_key` (e.g. `"6EA8C1FAD7D36439"`) pages cleanly through `section="sources"` and `"recoveries"` without raising `"Cursor does not match this query"`.
- Case-sensitive entity identifiers on `r3-mcp` (`videos.video_key = 'youtube:agHearing01'`, `channels.handle = '@AgRepublicans'`, `recordings.video_key`) remain preserved exactly.
- Cover get_entity and search_entities, including meeting event_id and roster congress. Preserve textual identifiers, absent-entity errors and pagination behavior.
- Add a compact regression fixture with a known numeric entity and related documents. Replay retained event 118300 when available: accepted forms return the same 38 visible rows; rejection never looks like an empty successful search.
- Run the existing explorer-mcp test lane in its independent environment and actual stdio regressions. Prove these behaviors before release preparation; record source/package identities and distinguish local completion from release delivery.

## Notes

**2026-10-31T00:56:20Z**

Implemented locally in models.py and reader.py: strict input unions prevent Pydantic coercion; one shared validator checks published integer ranges, normalizes integer strings, and preserves text/boolean values. Record selection, document lookup and cursor binding use canonical values. General query_sql behavior remains unchanged.

Verification: 85 MCP tests passed in the independent DuckDB 2 environment, including actual stdio and native-release integration. A 30-call retained-release replay returned the same 38 documents for accepted spellings of meeting 118300, continued pagination across spellings, and rejected malformed IDs and roster filters. Release: 0db23484fe86c7f5a5e50e44f078ec34e74e793873b26c4a15f0b9e9efa17b69. See apps/explorer_mcp/VERIFICATION.md and local .cache/mcp-ticket-fixes-20261030/retained-replay-result.json for source hashes and evidence.

Local implementation and verification are complete. Application packaging/distribution remains pending; the editable version still reports 0.4.0. Ticket remains open for delivery; no public pointer or retained release selection changed.

**2026-11-02T19:50:59Z**

Expanded scope from chaos test run chaos-mcp-20261101T200453Z (CT-CHAOS-103 & CT-CHAOS-104a): also cover DocumentSearch.congress and Page.limit / SqlQuery.limit boolean/float rejection, DocumentSearch.meeting_key integer/zero-padded normalization, DocumentQuery.link_key lowercase canonicalization before cursor binding, and case-insensitive normalization for published string identifier keys (committee_key/system_code, bioguide_id, measure_key/bill_id/nomination_id, witness_key).

**2026-11-03T14:38:09Z**

Completed, verified (123 passed in explorer-mcp lane), and published in congress-mcp-v0.5.0 (d675e540).
