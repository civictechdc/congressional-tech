---
id: ct-ha10
status: open
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

