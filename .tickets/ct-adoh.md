---
id: ct-adoh
status: open
deps: []
links: [ct-5hnu, ct-m104, ct-sw5t]
created: 2026-11-02T19:50:29Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-m104
tags: [mcp, schema, recipes, chaos-test]
---
# Replace placeholder recipe example parameters in release-schema.json and remove test parameter overrides

In model/registries/release-schema.json (CT-CHAOS-105a from chaos-mcp-20261101T200453Z), `witness_documents` and `witness_transcripts` advertise the synthetic placeholder `witness_key='0123456789abcdef'`, requiring `test_relationships.py` (`test_every_recipe_executes_and_has_the_declared_result_grain`) to override `witness_key` with `'appearance-1'` instead of testing `[p['example'] for p in recipe['parameters']]`. In addition, several other recipe `example` parameters (`event_id=118001` in `hearing_documents`/`recording_tracks`, `nomination_id='119-pn-730-2'` in `nomination_transcripts`, `list_row=3` in `document_editions`) are coupled to the synthetic unit-test / native-producer fixtures (`conftest.py` and `test_phase2_model_entities.py`) and may not match every live release snapshot (`publish_v21` `448651e7` vs `r1b` `c94bfedc` vs `CURRENT`).

## Design

Owner: model/registries/release-schema.json, docs/release-relationships.md, apps/explorer_mcp/tests/conftest.py, apps/explorer_mcp/tests/test_relationships.py, and apps/explorer_mcp/src/congressional_explorer_mcp/server.py.
1. Replace the placeholder `'0123456789abcdef'` in `model/registries/release-schema.json` with valid 16-hex-char `witness_key` values from the target release:
   - In `publish_v21` (`448651e7`, v1 witness keys): `witness_documents` `'0001497931f99cd1'` (or `'0ba3184ba5a188b2'`), `witness_transcripts` `'0000b43c099edbc2'`.
   - In `r1b-h` (`c94bfedc`, `witness-occurrence-v2` keys on `release-train` / `main`): `witness_documents` `'000222ef6e3cee4e'` (`Ms. Maura Calsyn`, `event_id=101778`, 2 rows), `witness_transcripts` `'000156c36d8a8a5e'` (`James Weinstein`, `CHRG-112shrg80540`, 1 row).
   (Note: `witness_key` in `release-schema.json:519` is a 16-character lowercase hex hash, not a 24-character key; `448651e7` and `c94bfedc` share 0 `witness_key` strings because `witness-occurrence-v2` hashes `record_sha_hex` and `context_key`. Also note that `committee_roster` with `system_code='hsif00'` and `congress=119` already returns 54 rows in both `448651e7` and `c94bfedc`; for the remaining recipes across both `448651e7` and `c94bfedc`, `hearing_documents(118300)` returns 39/38 rows, `nomination_transcripts('119-pn-11-10')` returns 2/1 rows, `recording_tracks(335286)` returns 5 rows, and `document_editions(8)` returns 1 row.)
2. Keep `118001`, `'hsif00'`, `'119-pn-730-2'`, `'appearance-1'`, `'appearance-2'`, and `list_row=3` intact in `conftest.py` and `test_phase2_model_entities.py` so the 25+ existing unit and native-release assertions in `test_reader.py`, `test_exact_entities.py`, `test_server.py`, and `test_native_release.py` remain untouched; append/align the 16-hex witness keys (and any updated recipe example keys) in `conftest.py` (and `test_phase2_model_entities.py` if needed on `r3-mcp`) so `test_every_recipe_executes_and_has_the_declared_result_grain` runs `params = [p['example'] for p in recipe['parameters']]` with zero overrides and asserts `expected['witness_transcripts'] == 1`.
3. In `server.py:get_dataset_info` docstring, clarify that recipe `example` parameters illustrate parameter types/formats and that callers should substitute keys discovered via `search_entities` or `search_documents` when querying a specific release.
4. Standardize all 6 document-returning recipes in `model/registries/release-schema.json` (`bill_documents`, `bill_hearing_transcripts`, `hearing_documents`, `witness_documents`, `witness_transcripts`, `nomination_transcripts`) so they consistently join `detail d USING (list_row)`, project `lower(hex(d.link_key)) AS link_key`, and filter `NOT coalesce(l.hidden,false)` so recipe outputs can be passed directly into `get_document` without hidden-row noise. Add `"detail"` to `requires` and `"document_detail"` to `relationships` on `hearing_documents` and `witness_documents`, update `bill_documents.notes[1]` (`line 3231`), and leave `document_editions` (`lines 3454-3474`) on `"list"` alone so `test_nested_lists_do_not_multiply_votes_or_document_editions` (`test_relationships.py:83-86`) is preserved.
5. Add a `hearing_dossier` recipe to `model/registries/release-schema.json` (keyed by `event_id`, example `118001`, `requires: ["meetings", "committees", "witnesses", "list", "detail"]`, `relationships: ["meeting_committees", "witness_meeting", "document_meetings", "document_detail"]`) using a single `?` placeholder (`WHERE m.event_id=?` per `archive_schema.py:144`), portable `meetings` columns (`m.event_id, m.chamber, m.meeting_date, m.meeting_type, m.status, m.title, m.subject_keys` — omitting `m.congress` so `conftest.py:47` `meetings.parquet` works), and correlated `coalesce(list(struct_pack(...)), [])` subqueries for `committees`, `witnesses`, and `documents` (with `lower(hex(d.link_key))`), and add `'hearing_dossier': 1` to `expected` in `apps/explorer_mcp/tests/test_relationships.py:65-67`.
6. Regenerate `docs/release-relationships.md` and run `.venv/bin/python -m viewer_publication.archive_schema --check`.

## Acceptance Criteria

- `witness_documents` and `witness_transcripts` in `model/registries/release-schema.json` use valid 16-hex-char `witness_key` examples (`'0001497931f99cd1'` and `'0000b43c099edbc2'`) rather than `'0123456789abcdef'`.
- All document-returning recipes in `model/registries/release-schema.json` project `lower(hex(d.link_key)) AS link_key` and filter `NOT coalesce(l.hidden,false)`.
- `hearing_dossier` recipe is published in `model/registries/release-schema.json` and passes `test_every_recipe_executes_and_has_the_declared_result_grain`.
- `test_every_recipe_executes_and_has_the_declared_result_grain` in `test_relationships.py` executes `[p['example'] for p in recipe['parameters']]` with no parameter overrides and passes (`witness_transcripts` expected count `>= 1`).
- `test_native_release.py` (on `r3-mcp`) and `.venv/bin/python -m viewer_publication.archive_schema --check` pass with `docs/release-relationships.md` up to date.


## Notes

**2026-11-03T01:00:52Z**

2026-11-02 (3-Agent Retrospective): Expanded scope with Tasks 1.3 and 4.2 from Guided Persona Tester (b3585182) and Unassisted Blind MCP User (14cd6e41): (a) standardize all document-returning recipes in release-schema.json on lower(hex(d.link_key)) AS link_key and NOT coalesce(l.hidden,false); (b) add a composite hearing_dossier recipe keyed by event_id.
