---
id: ct-17op
status: open
deps: []
links: [ct-wy4c, ct-6mvl, ct-auhc, cat2-ddas, ct-lft6]
created: 2026-11-11T14:57:19Z
type: feature
priority: 2
assignee: mikewolfd
tags: [parser, witnesses, mods, schema]
---
# Keep witness military rank and credentials in their own fields instead of dropping them

Owner decision 2026-11-10 (questions dialog, recorded on ct-wy4c): rank and credentials go in their own field, not in the name and not dropped. The follow-up parser work was said to join ct-6mvl's version step, but ct-6mvl does not mention it and the MODS witness-list branch (claude/ct-mods-zs48-3aap, shipping 2026-11-11) adds no such field (found by the release session's ticket audit 2026-11-11). Measured on ct-wy4c: after ct-rg34, 299 more MODS witness rows no longer show a rank or credential (47 rank, 291 credential); the live release already drops rank on 944 rows and credentials on 6,474 across sources. Nothing is lost in raw. Note: appearance-people.sql drops credentials and ranks as words for its same-person key; that is a keying choice and stays. Scope: every appearance producer that strips a rank or credential (find where each does), two new nullable fields in the appearance records and the published witnesses table (e.g. rank, credentials as stated), the release schema text, and the site/Explorer display. A new lake column needs a new table today (the pinned engine cannot add columns: see ct-auhc, the refactor team's X9 add_columns); fold it into the next appearance schema change or the first one after X9.

## Acceptance Criteria

Every row whose raw line states a rank or credential carries it in the new field, verbatim as printed (normalized spacing only); names no longer contain them; counts per source match a raw check reading the raw lines independently, both directions, with plants (a rank left in a name; a credential dropped); removals 0 against the live generation; the owner's decision cited.

