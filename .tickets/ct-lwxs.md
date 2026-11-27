---
id: ct-lwxs
status: closed
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

**2026-11-25T12:01:56Z**

2026-11-25: Phase 1 (ct-6him) merged in PR #240 (6374ea1f) and closed, unblocking ct-w34j (Phase 2 RefSpec agencies) and ct-39u8 (Phase 3 Wikidata). Minor note from pre-merge review: witness-level org_decisions currently apply to field_rank=1 (organization); consider witness:<wk>:<field> support for on_behalf_of in Phase 2/3 if needed.

**2026-11-25T22:23:00Z**

2026-11-25 P3 follow-ups: `ct-aory` shipped RefSpec 1.4 (`Formspec-Labs/RefSpec#2` + PR #251 `586cbd43`, lifting `house_xml` federal coverage to `90.31%`) and closed. `ct-39u8` merged live-probe refinements, capture/qualification wiring, and AC #3 fresh 150-link hand audit (`0–1/150` wrong <= `3/150`) in PR #252 (`73575906`); `ct-39u8` and `ct-lwxs` remain open solely for live R2 `wikidata/reconcile` capture + `include_wikidata_links=True` activation.

**2026-11-27T13:45:00Z**

Epic closed: all four child phases (`ct-6him`, `ct-w34j` + RefSpec `ct-aory`, `ct-39u8`, `ct-lvdf`) are closed and shipped live in combined release `efd7973e200f05a15c5f9d732d343a3b2bab1ac88915d15b7053cba096d8943c` (`Archive publish` run `46007066768`, live at `2026-11-27T13:38:29Z`; PRs #254, #256, #259, #260, #261).
- Live release summary: `50,409` canonical organizations (`9,125` Wikidata-anchored, `293` FR agency-anchored, `7` RefSpec target-anchored, `40,984` token-bag clusters), `68,563` `organization_ids`, `154,841` `witness_organizations` links (`43,969` `wikidata_auto`, `40,587` `registry`, `70,285` `token_bag`), and `11,154` 1-hop `organization_redirects` (`10,970` -> `wikidata`, `179` -> `fr_agency`, `5` -> `refspec_target`). Synchronized across R2 `manifest.json`, `derived/body_text/current.json`, SpicyEngine hybrid search (`320,671` documents, `10,874,972` passages), and hosted Cloudflare MCP (`21/21` tools passing `smoke.py`).
