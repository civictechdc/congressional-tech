---
id: ct-kw85
status: in_progress
deps: []
links: []
created: 2026-11-10T14:46:13Z
type: feature
priority: 1
assignee: mikewolfd
tags: [model, witnesses, members]
---
# Sitting Members acting officially are Member appearances, not witnesses

Owner decisions 2026-11-10 (questions dialog, session congress-1). Policy, in the owner's words: 'Members shouldn't be witnesses unless they are not in an official capacity, i.e. normal witnesses.' Chosen handling: 'Show them as Member appearances, not witnesses': a reader still finds every Member who spoke at a hearing, under their own label (the data already has a member_statement type), and witness lists and counts hold only outside witnesses. Edge cases decided: former Members speaking for an organization are ordinary witnesses; a sitting Member testifying before another committee about their own bill, and a home-state Senator introducing a nominee, are Members acting officially. Measured scope (pattern estimates, .cache/archive-release/investigations/mods-rebase-20261110/review-2/r2-members.json): about 8,000 witness rows shown today are sitting Members: MODS about 3,600 shown (4,710 of 107,985 parsed; about 420 Member Day, 640 nominations, 3,650 other of which about 760 carry a bill number in the title), house_xml about 1,900 of 15,055 (1,840 carry the publisher's bioguide id), congress_gov about 2,300 of 28,492 (about 1,610 Member Day), senate_page about 250 of 13,503; former Members at most about 300. The pattern cannot see Members with no office phrase and a nickname mismatch, and it has name collisions (a 'John G. Edwards, Photonic Sensor' matched a Member). Asker lines in MODS (questions, responses, requests) are handled on the MODS branch (ct-zs48), not here.

## Acceptance Criteria

A model-level rule decides Member-in-office from identity and term dates (members and roster data), not from line shape, and applies to all four publishers. Exact counts by publisher and hearing kind replace the estimates, with every row that changes listed for review and former Members shown to stay witnesses. Witness lists, witness counts, meeting coverage and the witness key map exclude Member appearances; the Member rows stay findable from the hearing and from the Member. The site shows the label. The release gate difference is explained by one recorded cause. An independent reviewer confirms a planted case in each direction (a Member left as a witness; an outside witness retyped).

