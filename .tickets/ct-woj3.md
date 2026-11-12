---
id: ct-woj3
status: closed
deps: []
links: []
created: 2026-11-11T00:35:01Z
type: epic
priority: 2
assignee: mikewolfd
tags: [data-model, witnesses, identity]
---
# Witness identity: carried appearance keys and a person layer

Owner decisions 2026-11-10/11 (session congress-1, questions dialog): 'Both layers, designed together'; key design 'Carry forward, like Wikidata' (mint once, keep, redirect on merge; the formula meeting + print + name + organization + role only mints keys for new witnesses); person merges 'Unicode Normalized iexact name + organization automatically, later we'll try to pull identity info from their statements'; ct-uywf 'Ship it, trim later'; reorders on a proved re-fetch 'Publish the new order'. Plan, measurements and the independent review: .cache/archive-release/investigations/witness-identity-20261110/PLAN.md (scripts wi-01..06, greybeard/gb-01..06). Why: today's witness key hashes the record body, so every re-fetch re-keys (ct-uywf), and the key map cannot follow parser changes (25 Senate keys already resolve nowhere).

## Acceptance Criteria

Slices 1-3 done; see children.


## Closeout Note (2026-11-12)

Closing parent Witness Identity epic per Owner Policy Decision `A2`:
- **Slice 1 (`ct-46f3`) — SHIPPED & CLOSED:** Carried witness appearance keys from `base_release` (`witness-appearance-v3` minting for new occurrences), `lost_witness_keys` export refusal, 25 historical Senate key backfills, and Explorer/MCP map lookup.
- **Slice 2 (`ct-ha10`) — SHIPPED & CLOSED:** Shared same-person SQL layer, `people.parquet` (`101,880` people; Members by Bioguide + exact NFKC case-folded name + full organization with middle-initial/suffix guards and military `ranks`), `person_aliases.parquet`, `model/registries/person-decisions.json`, `?person=` UI pages, and MCP `person` lookup/search.
- **Companion (`ct-960v`) — SHIPPED & CLOSED:** Retained dropped Congress.gov witnesses, documents, bills, and nominations marked `'no_longer_listed'` so keys and links never break on re-fetch nights.
- **Slice 3 (`ct-kt2o`) — INTENTIONALLY OPEN:** Per Owner Policy Decision `A2`, `.tickets/ct-kt2o.md` (LLM/statement-extracted cross-employer person identity enrichment) intentionally remains `status: open` for follow-on work.
