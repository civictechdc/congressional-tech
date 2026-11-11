---
id: ct-eofd
status: open
deps: []
links: []
created: 2026-11-11T13:50:59Z
type: feature
priority: 2
assignee: mikewolfd
tags: [spicy-regs, members, witnesses, pins]
---
# Adopt spicy-regs members name_middle, name_suffix and name_official_full in Member matching

spicy-regs ticket ss-mbia is done (2026-11-11): the members table now publishes name_middle, name_suffix and name_official_full (generation sha256:26d652e1…, 12,770 rows; non-null 8,768 / 457 / 1,140), from spicy-docs 0.85.0 (fork main 9597e195), spicy-regs PR #164. All 43 Members whose name_first is a bare initial now have name_middle (14 also name_official_full), e.g. H001072 'J. French Hill'; acceptance list .cache/archive-release/investigations/member-appearances-20261110/v4/ma4-initial-only-members.csv. CT pins spicy-docs ==0.84.0 and a members generation, and selects members columns by name, so adopting it moves a model input for the whole release: do it after the MODS + ct-kw85 release, and tell the spicystack session before CT's pin moves. Expected gain measured by ct-kw85: 8 shown witness rows recovered as Member appearances (Gorton x2, Akin, Steube, Cleland, Correa, French Hill, Sensenbrenner); ct-kw85's 'initial' match basis may then become unnecessary (measure, then decide).

## Acceptance Criteria

CT pins the new members generation and spicy-docs 0.85.0; the Member-appearance step uses name_middle/name_official_full; the 8 rows become Member appearances and no other row changes unexplained; the raw check's plants pass; the spicystack session was told before the pin moved.

