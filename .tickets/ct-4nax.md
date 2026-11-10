---
id: ct-4nax
status: in_progress
deps: []
links: []
created: 2026-11-10T19:07:52Z
type: task
priority: 0
assignee: mikewolfd
---
# Release gate: a changed link passes only as a named correction in the reviewed record

The link rule refuses any live link key, lookup key or address that answers another file, and no record overrides it (ct-4qld, ct-wscb). The owner's record corrections (ct-u9y4) change 30 link keys and 38 lookup keys on purpose, so release aef93461 cannot pass. Owner decision 2026-11-10 (questions dialog): 'Accept named corrections': the gate lets a changed answer through only when the reviewed cause record names that exact key with its live file, its candidate file and the correction decision; any key not named still refuses; missing, dangling and unchecked stay absolute. Follow-up for the data-proven form is a separate ticket.


## Notes

**2026-11-10T19:26:02Z**

2026-11-10 branch claude/ct-gate-corrections (local, not pushed). The cause record takes an optional `corrections` list; each entry is exactly {kind: link_key|lookup_key|address, key (as the report prints it), live_body, candidate_body (SHA-256), decision, tickets (>=1, each a file in .tickets)}, one per (kind, key, live body); load_causes refuses unknown or missing fields, bad hex, a bad key, a duplicate or a missing ticket file. verdict (release_gate.named_corrections) lets a changed, lookup_changed or address_changed key through only when an entry matches its kind, key and both bodies (a lookup key or address must reach that one file on every row); an unnamed key, a key beyond the report's sample and an entry that matches nothing refuse; a record bound to another pair waives nothing; missing, dangling and unchecked are untouched. Report: lookup and address answers now carry candidate_bodies and list the first 100 keys whole (row-sampling could hide a key's second live row behind its first; a planted test shows the old SQL would have passed it). release-gate.json gains named_corrections (waived count and keys per kind); the release note lists each entry. Real data (investigations/gate-corrections-20261110/gc_01_planted.out): compare on 619db5f9e08e vs build-release-b equals the proof report in every link_rule field and in failing; the 30 link keys and 38 lookup keys (30 lookup_key + 8 alias_key of effect-A.csv) agree with effect-A on both bodies, both directions; a 68-entry record leaves exactly the 43 non-link-rule reasons; a wrong body, a wrong key, a dropped entry and a lookup named as an address each refuse and name what they should. Cannot see: whether the new file is the right document or whether the change was meant (a list copied from the report passes): that is the review's; ct-faan is the data-proven form. Full lanes not run (machine busy); focused files only.
