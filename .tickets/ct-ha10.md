---
id: ct-ha10
status: closed
deps: [ct-46f3]
links: []
created: 2026-11-11T00:35:01Z
type: feature
priority: 3
assignee: mikewolfd
parent: ct-woj3
tags: [data-model, witnesses, identity, site]
---
# Witness identity slice 2: people (automatic merge on normalized exact name + organization), person aliases, person pages

See .cache/archive-release/investigations/witness-identity-20261110/PLAN.md section 2. Members by Bioguide ID first (publisher ID, then ct-kw85 matched_bioguide_id). Others: person key minted once from Unicode-normalized (NFKC), case-folded exact name plus organization (owner D2), carried through its appearances; no name-only merge. person_aliases.parquet for merges, splits and regroupings; reviewed decisions append-only in model/registries/person-decisions.json; ?person= pages. Extract the same-person rule copied in witness-precedence.sql:43-46 and witness-key-map.sql:31-34 (and ct-kw85's reader) into one shared step first.

## Acceptance Criteria

At least 95% precision on 100 random people read against raw records; no name-only merges; a raw check judging sampled people by facts the rule does not use (dates, titles, middle initials, Member terms), both directions, with a planted merge of two different people, confirmed by a second reviewer.


## Notes

**2026-11-11T03:02:45Z**

2026-11-11 (session congress-1): the joint person-identity contract with spicy-regs is drafted, reviewed by the spicy-stack session (ENDORSE WITH CHANGES, all applied) and revised: .cache/archive-release/investigations/person-identity-contract-20261111/pc-contract-draft.md (v1 kept beside it; spicy-regs review in spicy-regs-review/). Ownership: CT builds and keeps people from its hearing records and shows their pages; spicy-regs stores only cross-source decisions, which name a CT appearance (witness_key), never a CT person key; digests cover content only. Owner decisions: 'Design it jointly first'; first slice 'Just do the simplest/fastest thing with the best results and the least errors. It doesn't need to be perfect. We'll come back to this' = Members by Bioguide, everyone else on Unicode-normalized case-folded exact name plus the FULL normalized organization (no first-comma cut: it collapsed 17,495 organization strings into 4,734), middle-initial and suffix guards, never an empty organization; no cross-employer links, model extraction, web search or LinkedIn in this slice; corrections via the site's existing 'Public GitHub issues' link. Reach on 77673bfb8fcf: 12,111 non-Member people at 2+ hearings (38,207 appearances) plus 593 Members by publisher Bioguide. CT-2 can ship on a computed person key with alias rows without waiting for ct-46f3. Replace the acceptance's '95% on 100 random people' with: every risky group (guards, accents, suffixes) read plus 200 random people, at most 2 wrong.

## Closeout Note (2026-11-12)

Shipped in `claude/ct-wave-5-identity`:
- Extracted the shared same-person rule (`person-nicknames.sql`, `person-same-family.sql`, `person-given-matches.sql`) across `witness-precedence.sql`, `witness-key-map-fresh.sql`, `congress-gov-retained-witnesses.sql`, `print-meeting-agreement.sql`, and `witness-member-names.sql`.
- Built `people.parquet` (`101,880` people, including `12,111` multi-hearing non-Member people + `1,004` Members by Bioguide; carrying `ranks`, `name_variants`, `organizations`, `positions`) and `person_aliases.parquet` with append-only reviewed overrides in `model/registries/person-decisions.json`.
- Shipped Explorer `?person=` profile pages (`PersonDetail.tsx` with military rank/credentials rendering, alias redirects, ambiguous split notices, and full cross-links) plus Explorer MCP `person` entity lookup/search (`reader.py`, `citations.py`).
- Verified via `test_person_identity.py` and independent bidirectional raw check `scripts/measure/people_raw_check.py` (risky guard/suffix/accent cohorts + 200 random people audited against raw receipts with 0 false merges; planted cross-person merge caught and confirmed by independent verifier).
