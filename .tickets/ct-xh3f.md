---
id: ct-xh3f
status: open
deps: []
links: []
created: 2026-11-18T19:16:01Z
type: task
priority: 3
assignee: mikewolfd
tags: [congress-api, coverage]
---
# Check Congress.gov API known issues against our coverage gaps, and watch its change log

From the 2026-11-18 survey of the Library of Congress's GitHub (.cache/archive-release/reviews/ticket-state-20261118/LOC-HANDOFF.md). The public tracker for the Congress.gov API (github.com/LibraryOfCongress/api.congress.gov) has open reports that may explain gaps we treat as our own defects: issue 435 (committee meeting IDs starting 'LC' cannot be listed or found), 176 (Senate markup meetings have no documents), 171 (hearing data not fresh). Our docs cite the endpoint documentation (packages/congress_api/SOURCE_MODELS.md, matching/committees.py) but neither these issues nor the repository's ChangeLog.md. Reported by the survey agent; the issues were not re-read here.

Do: read the three issues and any others touching committee meetings, hearings and witnesses; for each, say whether a current coverage gap or gate finding matches it, and cite it where the gap is documented. Add a light watch on ChangeLog.md (a check that reports when it changes is enough). spicy-docs calls the same API (sources/congress/), so share what is found.

## Acceptance Criteria

Each relevant upstream issue is either cited beside the gap it explains or recorded as not affecting us; a change to the upstream change log is noticed.

