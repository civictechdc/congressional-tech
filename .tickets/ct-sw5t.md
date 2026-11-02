---
id: ct-sw5t
status: open
deps: []
links: [ct-5hnu, ct-m104, ct-adoh]
created: 2026-11-02T19:50:29Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-m104
tags: [mcp, search, relationships, chaos-test]
---
# Complete MCP entity/document search: bills.short_title, nominations transcripts, document-section columns, unknown-filter errors, and rosters guidance

Chaos test run chaos-mcp-20261101T200453Z against publish_v21 (448651e7) uncovered five entity/document search and discovery defects that remain unfixed on both main and r3-mcp:
1. CT-CHAOS-101a: search_entities(table='bills', text='One Big Beautiful Bill') returns 0 rows because reader.py text search omits bills.short_title (764 of 10,352 bills with a short_title do not repeat it in bills.title).
2. CT-CHAOS-102: get_entity(table='nominations', id=..., section='documents') returns 0 rows for 100% of nominations because document_links['nominations'] resolves to list.measure_keys (which holds only bill_ids), ignoring nominations.transcripts -> detail.package_id (which links 539 of 747 nominations to confirmation hearing transcripts).
3. get_entity(..., section='documents') omits l.congress, l.document_date, and l.document_kind (plus d.document_date_source, l.first_captured, l.date_kind on r3-mcp), unlike search_documents.
4. CT-CHAOS-104b: search_entities with a nonexistent filter column (e.g. filters={'congress': 119} on bills) raises 'Use a scalar published filter; query_sql supports nested congress', falsely claiming the nonexistent column is nested.
5. CT-CHAOS-101b: search_entities(table='rosters', text='<member name>') returns 0 rows because rosters only carries seat role title ('Chair') and bioguide_id, without tool docstring guidance pointing to committee_roster or members.

## Design

Owner: apps/explorer_mcp/src/congressional_explorer_mcp/reader.py, server.py, and model/registries/release-schema.json.
1. Add `'short_title'` to `TEXT_FIELDS` / text-search column list in `reader.py` (and set a non-null `short_title` on the `bills` fixture row in `apps/explorer_mcp/tests/conftest.py:78`).
2. **Preserve `r3-mcp`'s single-owner schema boundary (`published_entities(schema)`) and the direct-annotation vs. transcript-recipe boundary (`ct-1xt0`):**
   - Do **not** add a hardcoded `if query.table == 'nominations':` branch in `Reader.get_entity` (which would override `published_entities(schema)`, violate the direct `list.<col>[]` vs. `package_id` transcript boundary enforced by `test_relationships.py:106-113`, and break `test_entity_to_documents` in `test_reader.py:39-46`).
   - Instead, update the `get_entity` and `search_documents` tool docstrings in `server.py` (and the `document_nominations` note in `release-schema.json`) to state explicitly that `get_entity(section='documents')` and `search_documents` match direct `list.<col>[]` document annotations (`list.measure_keys` holds `bill_id`s), and direct callers to the `nomination_transcripts`, `bill_hearing_transcripts`, and `witness_transcripts` recipes for `package_id`-linked hearing transcripts.
3. Extract a shared document-summary column projection in `reader.py` so `get_entity(..., section='documents')` returns `l.congress, l.document_date, l.document_kind, l.saved_kind` (plus `d.document_date_source, l.first_captured, l.date_kind` on `r3-mcp`) while **preserving `l.hidden`** on `get_entity(..., section='documents')` so `test_reader.py:45` (`assert all(not r['hidden'] for r in result['rows'])`) remains green.
4. In `Reader.search_entities` filter validation, check `if name not in columns:` **before** the nested-column check (`'[]' in columns[name] or columns[name].startswith(('STRUCT', 'MAP'))`). Raise `ExplorerError(f'Unknown filter field {name!r} on {query.table}; scalar filter fields are: ...')` for unknown columns, and keep the exact `'Use a scalar published filter; query_sql supports nested ...'` message for nested columns so `test_reader.py:55-56` passes.
5. Update `search_entities` docstring in `server.py` to note that `rosters` holds seat assignments (`bioguide_id`, `system_code`, role `title`) and point to the `committee_roster` recipe or `members` table for member names.

## Acceptance Criteria

- `search_entities(table='bills', text='One Big Beautiful Bill')` matches `bills.short_title` and passes `test_every_entity_table_is_text_searchable_or_explicitly_not` on `r3-mcp`.
- `get_entity(..., section='documents')` returns the full document metadata columns alongside `l.hidden`, and `test_entity_to_documents` (`test_reader.py:39-46`) passes without hardcoded table branches overriding `published_entities(schema)`.
- `get_entity` and `search_documents` docstrings in `server.py` clearly direct callers to `nomination_transcripts`, `bill_hearing_transcripts`, and `witness_transcripts` for hearing transcripts.
- Filtering `search_entities` by an unknown column raises an `'Unknown filter field'` error listing valid scalar columns, while filtering by an actual array/struct column still raises `'Use a scalar published filter; query_sql supports nested ...'` (`test_reader.py:55-56`).
- All `explorer-mcp` unit and stdio integration tests pass.

