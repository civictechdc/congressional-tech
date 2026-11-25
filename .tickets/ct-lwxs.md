---
id: ct-lwxs
status: open
deps: []
links: [ct-f6qv, ct-kt2o]
created: 2026-11-09T00:51:32Z
type: epic
priority: 2
assignee: mikewolfd
tags: [entities, witnesses, organizations]
---
# Link witness appearances to organizations

People and person aliases shipped in ct-ha10. This epic supplies organization IDs and reviewed affiliation context for ct-kt2o. Organization aliases cannot change a person_key. Agency names and free-text aliases come from a RefSpec release pinned directly by digest (shared with SpicyRegs). Every normalized org string gets an org ID after fuzzy matching. Wikidata auto-accept: single clear winner, score 90+.

Design: docs/plans/org-entities-20261108.md. Measurement: .cache/archive-release/investigations/entity-matching-measure-20261108/ (fed_agency.json, org_score.json, org_variants.json, org_labels.json, org_hand_check.txt, em-wd-accept.py -> wd_accept.txt, em-fuzzy.py -> fuzzy_L2.json / fuzzy_L3.json / fuzzy_*sample*.txt). Release 630164505301.

ct-w34j needs a verifiable RefSpec agency generation. The November 8 design refers to RefSpec branch claude/agency-aliases.

## Acceptance Criteria

All four child phases closed with their gates met; witness text unchanged; every published org_id resolves in one hop (live or redirect) across consecutive releases; each release reports retired org IDs by cause.

## Notes

**2026-11-21T05:58:20Z**

The organization plan and the review of sample witness appearances are complete. All four delivery tickets are open. Start by giving the same organization a stable ID across spelling variants while preserving the witness's original affiliation text. Then check federal agency names and Wikidata matches before exposing the links in Explorer and its API. [Stable organization IDs](ct-6him.md) · [Federal agencies](ct-w34j.md) · [Wikidata matches](ct-39u8.md) · [Public organization links](ct-lvdf.md)

**2026-11-22T19:53:35Z**

2026-11-22 Owner decision A3: Attach Ban, Park & You (APSR 2023, doi:10.1017/S0003055422000405) 9-parent / 18-child witness organization taxonomy to resolved organizations cleanly in parallel with DocMeta V7 (zero blocking dependency on ct-o7j0). Reference: docs/plans/docmeta-v7-consulting-plan-20261122.md.
