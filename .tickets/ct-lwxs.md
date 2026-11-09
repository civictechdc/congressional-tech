---
id: ct-lwxs
status: open
deps: []
links: []
created: 2026-11-09T00:51:32Z
type: epic
priority: 2
assignee: mikewolfd
tags: [entities, witnesses, organizations]
---
# Link witness appearances to organizations (organizations first)

Owner decision 2026-11-08: organization entity matching first; people later (linking ~5,900 Member rows without bioguide_id is the first people step, not this epic). Design: docs/plans/org-entities-20261108.md. Measurement: .cache/archive-release/investigations/entity-matching-measure-20261108/ (fed_agency.json, org_score.json, org_variants.json, org_labels.json, org_hand_check.txt, em-wd-accept.py -> wd_accept.txt). Release 630164505301.

## Acceptance Criteria

All four child phases closed with their gates met; witness text unchanged; every published org_id resolves (live or redirect) across consecutive releases.

