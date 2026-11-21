---
id: ct-flq8
status: open
deps: []
links: [ct-u3eh, ct-2cig, ct-jmwq, ct-2uc9]
created: 2026-11-18T22:04:50Z
type: task
priority: 2
assignee: mikewolfd
tags: [docmeta, gold]
---
# DocMeta gold: owner hand review of held and not-applied second-opinion rulings

Filed 2026-11-18 from /Users/mikewolfd/Work/congressional-tech/.cache/archive-release/docmeta-v65-raretypes-20261118/HANDOFF.md. The second-opinion pass produced 523 rulings (lookups_and_gold/second_opinion_rulings.jsonl: 467 apply, 12 modify, 44 reject). Stage 1 applied 271 through rule C2 of scripts/normalize_gold_v6_5.py; the checker then failed 91 rows, so nothing was re-sealed. Stage 3 (hold every ruling the checker disputes, fix two missing signal entries, re-check, re-seal only if clean) was still running as an agy job at 17:04 on 2026-11-18 and lookups_and_gold/second_opinion_held.jsonl did not exist yet. FIRST check its result: _scratch_c2/ and ssot/MANIFEST.json. If lookups_and_gold/gold_v6_5n_*.jsonl do not pass contract/gold_contract.py check (commands in contract/CONTRACT.md), restore them from _sealed_backup_20261118_1522/; the sealed file (sha256 33f97821...9b3f, 3,733 rows) is valid either way. For the owner to review by hand in the viewer (viewer/serve.py --port 8765, launch entry docmeta-viewer in /Users/mikewolfd/Work/.claude/launch.json; rebuild the bundle after any re-seal; verdicts land in viewer/review_notes.jsonl): the held rulings, and the 24 not_applied ones in lookups_and_gold/second_opinion_applied.jsonl, 12 of which ask to remove a person role, which the format forbids (the usual right fix is to remove the person). Bring each new convention question to the owner one at a time with the raw text; source text is truth. Also open: the blind sets (56 documents) were not cleaned; no test document has more than 10 people; dd85ac39a196cbaa has a vote-sheet date too damaged to read and needs the source page.

## Acceptance Criteria

1. Stage 3 result recorded: counts applied, held by checker rule, not applied, rejected; the sealed file either re-sealed with its new sha256 or confirmed unchanged. 2. Every held and not-applied ruling has an owner verdict in viewer/review_notes.jsonl and is applied or dropped. 3. The owner states in writing that the training and test data are signed off, or lists what still blocks that.

