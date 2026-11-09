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

Owner decisions 2026-11-08: organizations first; people later (linking ~5,900 Member rows without bioguide_id is the first people step, not this epic). Agency names and free-text aliases come from a RefSpec release pinned directly by digest (shared with SpicyRegs). Every normalized org string gets an org ID after fuzzy matching. Wikidata auto-accept: single clear winner, score 90+.

Design: docs/plans/org-entities-20261108.md. Measurement: .cache/archive-release/investigations/entity-matching-measure-20261108/ (fed_agency.json, org_score.json, org_variants.json, org_labels.json, org_hand_check.txt, em-wd-accept.py -> wd_accept.txt, em-fuzzy.py -> fuzzy_L2.json / fuzzy_L3.json / fuzzy_*sample*.txt). Release 630164505301.

External dependency: the RefSpec agency release prepared on RefSpec branch claude/agency-aliases (blocks ct-w34j).

## Acceptance Criteria

All four child phases closed with their gates met; witness text unchanged; every published org_id resolves in one hop (live or redirect) across consecutive releases; each release reports retired org IDs by cause.
