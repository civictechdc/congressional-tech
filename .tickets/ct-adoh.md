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
# Replace placeholder recipe example parameters in release-schema.json with retained published keys

In model/registries/release-schema.json (CT-CHAOS-105a from chaos-mcp-20261101T200453Z), 6 of the 11 published SQL recipes advertise placeholder or unretained example parameter values that return 0 rows when executed against publish_v21 (448651e7): hearing_documents (event_id=118001), witness_documents (witness_key='0123456789abcdef'), witness_transcripts (witness_key='0123456789abcdef'), committee_roster (system_code='hsif00'), recording_tracks (event_id=118001), and document_editions (list_row=3). In addition, test_relationships.py hardcodes 'appearance-1' for witness_key instead of testing the published example value.

## Design

Owner: model/registries/release-schema.json, docs/release-relationships.md, apps/explorer_mcp/tests/conftest.py, and apps/explorer_mcp/tests/test_relationships.py.
1. Update the 6 recipe example values in model/registries/release-schema.json to real retained keys present in publish_v21:
   - hearing_documents: event_id 118300
   - witness_documents: witness_key 'f7dc5fd61b82f27f9d4a6523'
   - witness_transcripts: witness_key 'c7fa9a05d1c0c5a18ca8bd04'
   - committee_roster: system_code 'hsju00' (House Committee on the Judiciary)
   - recording_tracks: event_id 115538
   - document_editions: list_row 1
2. Update apps/explorer_mcp/tests/conftest.py fixture data to include those exact keys and remove the 'appearance-1' override in test_relationships.py so every recipe is tested directly with [p['example'] for p in recipe['parameters']].
3. Regenerate docs/release-relationships.md and run viewer_publication.archive_schema --check.

## Acceptance Criteria

- Executing every recipe in model/registries/release-schema.json with its declared example parameters returns >= 1 row against both the unit test fixture and the retained release.
- test_every_recipe_executes_and_has_the_declared_result_grain passes using [p['example'] for p in recipe['parameters']] with no parameter overrides.
- .venv/bin/python -m viewer_publication.archive_schema --check passes and docs/release-relationships.md is up to date.

