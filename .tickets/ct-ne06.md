---
id: ct-ne06
status: closed
deps: []
links: []
created: 2026-10-22T17:34:59Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-syem
tags: [committee-meeting, youtube-api, architecture, duplication]
---
# Break circular youtube_api <-> congress_api dependency and decouple Catalog.check_graph_with from private SpilledRecordSequence internals

CS300 Audit Finding (Committee, Naming & YouTube Auditor):
1. Undeclared Circular Package Dependency (packages/youtube_api/src/youtube_api/fetch/youtube_event_fetcher.py:11-15 vs packages/youtube_api/pyproject.toml:6-13): youtube_event_fetcher.py imports YoutubeChannelItem, YoutubePlaylistItem, and YoutubeVideoItem from congress_api.models.transcription, even though youtube_api/pyproject.toml does not depend on congress-api (and congress-api depends on youtube-api, creating a circular dependency). Furthermore, packages/youtube_api/src/youtube_api/tables.py:15-17 hardcodes Path(__file__).parents[3] / 'congress_api/Make/data/youtube-accounts.csv'.
2. Encapsulation, Law of Demeter & CQS Violations + 180-line Copy-Paste in Catalog.check_graph_with (packages/committee_meeting/src/committee_meeting/catalog.py:149-406 & apps/committee_youtube/src/committee_explorer/export.py:106-109):
   - catalog.py:216-218 reaches two levels into private attributes of SpilledRecordSequence (defined in apps/committee_youtube): self.records._spilled._by_kind.keys() and getattr(self.records, '_extra', ()).
   - catalog.py:329-332 mutates self.records._cited_json_pointers = cited_pointers as a hidden side effect of validation, which export.py:106-109 reads and delattrs.
   - catalog.py:155-333 (lazy path) and catalog.py:335-406 (eager path) duplicate all 14 graph invariants across 250 lines instead of validating against a unified RecordIndex protocol.
3. Model Duplication & Dead Code in committee_meeting:
   - Duplicate sitting fields between MeetingSitting (meetings.py:14-25) and MeetingOccurrence (meetings.py:49-66); duplicate artifact fields and retained_digest_matches validator between MaterialFile (materials.py:58-84) and Representation (materials.py:132-153); denormalized duplicate fields on Appearance (meetings.py:100-124).
   - Dead files/symbols: 0-byte packages/committee_meeting/src/__init__.py, unused MaterialCategory (materials.py:17-22), unreferenced committee_meeting/main.py:1-15, and broken uninitialized submodule submodules/congress_meeting_map (.gitmodules:1-3, README.md:94).

## Acceptance Criteria

1. Move YoutubeChannelItem/YoutubePlaylistItem/YoutubeVideoItem (and youtube-accounts.csv path resolution) into youtube_api or congress_shared so youtube_api has zero imports from congress_api. 2. Refactor Catalog.check_graph_with to use a clean RecordIndex protocol without touching _spilled._by_kind or monkey-patching _cited_json_pointers, collapsing the 180-line duplicate lazy/eager validation branches into one pass. 3. Deduplicate SittingFields and PayloadArtifactBase in committee_meeting, delete packages/committee_meeting/src/__init__.py and MaterialCategory, and remove the dead submodules/congress_meeting_map gitlink.


## Notes

**2026-10-22T17:42:50Z**

Subagent Self-Review Additions:
- Explicitly include resolving packages/committee_meeting/src/committee_meeting/main.py:1-15 in Acceptance Criterion 3 (either wire into [project.scripts] in pyproject.toml or delete).
- Deduplicate Provenance.reported / Provenance.derived source_ref/sel_type construction (packages/committee_meeting/src/committee_meeting/provenance.py:84-88, 107-111).

**2026-10-22T18:33:46Z**

Lead Architect Review (Defend Intent + Compromise):
1. DEFEND + REFACTOR: In Catalog.check_graph_with (packages/committee_meeting/src/committee_meeting/catalog.py:177-186), collecting _cited_json_pointers during graph validation is an intentional single-pass optimization so export.py can prune uncited JSON subtrees from spilled source records without scanning the entire corpus a second time. Keep the single-pass collection during check_graph_with, but return the cited pointer set explicitly (or pass an optional collector parameter) and expose a public self.records.kinds() method instead of reaching into self.records._spilled._by_kind and monkey-patching _cited_json_pointers.
