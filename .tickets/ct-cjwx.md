---
id: ct-cjwx
status: closed
deps: []
links: [ct-r4rd]
created: 2026-11-02T00:40:43Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [parser, meetings, phase2]
---
# Fix House sitting times and rooms in meeting_records.py at the next parser version move

Owner decision 2026-11-01: do both. Congress.gov comes first for sittings now (annex §1.2, under ct-r4rd), and the House parser is fixed too. Live House sittings run 4-5 hours early on 6,157 events and lose locations, and meeting_records.py misses House rooms. The file is byte-hashed, so this moves its pin and reparses about 6,179 House XML bodies; batch it with the next planned version move.

## Acceptance Criteria

House records state correct local times and rooms against raw XML; House building names are reconciled with Congress.gov's so ct-r4rd value agreement holds; pin and backfill recorded.


## Notes

**2026-11-02T04:01:45Z**

Code on worktree-agent-a704015cc138b456b @ da425206. Review verdict: merge. Open: backfill, and House and Congress.gov building names not shown reconciled.

**2026-11-05T17:11:17Z**

Closed as superseded on 2026-11-05. Remaining scope, acceptance and evidence are explicitly transferred to ct-r4rd. This is consolidation, not a claim that unfinished implementation or publication has passed. Original criteria and historical notes remain here. See the surviving owner and the reviewed consolidation report under .cache/archive-release/investigations/open-ticket-clusters-20261105T161237Z/consolidation-review/REPORT.md.
