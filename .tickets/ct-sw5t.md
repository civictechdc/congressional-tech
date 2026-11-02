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

Owner: apps/explorer_mcp/src/congressional_explorer_mcp/reader.py and server.py.
1. Add 'short_title' to TEXT_FIELDS / text-search column list in reader.py.
2. In Reader.get_entity(..., section='documents'), add an explicit nominations branch checking (list_contains(l.measure_keys, ?) OR EXISTS (SELECT 1 FROM nominations n, unnest(n.transcripts) t(package_id) WHERE n.nomination_id=? AND d.package_id=t.package_id)) with args [str(query.id), str(query.id)].
3. Project the same document metadata columns in get_entity(..., section='documents') as in search_documents.
4. In Reader.search_entities filter validation, check 'if name not in columns:' first and raise ExplorerError listing the table's scalar filter columns; reserve 'Use a scalar published filter; query_sql supports nested ...' for actual array/struct/map columns.
5. Update search_entities docstring in server.py to note that rosters holds seat assignments (bioguide_id, system_code, role title) and point to the committee_roster recipe or members table for member names.

## Acceptance Criteria

- search_entities(table='bills', text='One Big Beautiful Bill') returns 119-hr-1.
- get_entity(table='nominations', id='119-pn-11-9', section='documents') returns its linked confirmation hearing transcript(s) via nominations.transcripts -> detail.package_id, with full document metadata columns.
- Filtering search_entities by an unknown column raises an 'Unknown filter field' error listing valid scalar columns, while filtering by an actual array/struct column still raises the nested-field error.
- All explorer-mcp unit and stdio integration tests pass.

