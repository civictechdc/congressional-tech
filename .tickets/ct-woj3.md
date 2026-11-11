---
id: ct-woj3
status: open
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

