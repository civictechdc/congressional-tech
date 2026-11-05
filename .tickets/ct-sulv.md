---
id: ct-sulv
status: closed
deps: []
links: [ct-9s7b]
created: 2026-11-02T15:33:09Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [recordings, captions]
---
# Recordings publish one caption body as both live and caption productions

impl-r4-c 2026-11-02: 765 recordings publish one body under both live and caption productions, because two recording-source registry URL patterns match one fetch. Separate from ct-9s7b.

## Acceptance Criteria

Each fetched body maps to exactly one (format, language, production) per recording; registry patterns are disjoint or ranked; a native check refuses a body published under two productions.


## Notes

**2026-11-05T17:11:18Z**

Closed as superseded on 2026-11-05. Remaining scope, acceptance and evidence are explicitly transferred to ct-9s7b. This is consolidation, not a claim that unfinished implementation or publication has passed. Original criteria and historical notes remain here. See the surviving owner and the reviewed consolidation report under .cache/archive-release/investigations/open-ticket-clusters-20261105T161237Z/consolidation-review/REPORT.md.
