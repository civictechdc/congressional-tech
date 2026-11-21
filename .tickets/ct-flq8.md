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

## Stage 3 Result (2026-11-21)

- `second_opinion_rulings.jsonl` (`523` lines) processed via filtered Stage 3 with checker-disputed holds (`lookups_and_gold/second_opinion_held.jsonl`: `90` rulings): `256 applied`, `109 already_true`, `90 held_for_owner`, `24 not_applied`, `44 rejected_by_ruling` (`200` rows touched / `259` values changed).
- Held breakdown by checker rule: `P03_committees_stated=25`, `P05_doc_date_stated=13`, `P02_chamber_stated=12`, `P04_subcommittees_stated=11`, `P06_event_date_stated=8`, `D16_stated_date_not_lost=8`, `T03_ref_numbers_in_text=5`, `T01_name_tokens_in_text=5`, `T08_party_state_basis=2`, `P07_due_date_stated=1`.
- `gold_contract check`: `status=pass`, `blocking_errors=0`, `D15_removed_values_in_signal: 0 failures`.
- Pre-Stage-3 SSOT (`33f978210cbeb8f25960fb66c96090b8139d2e4f2321e64dd7f8e53b56ce9b3f`) preserved at `_sealed_backup_ssot_20261118_33f97821/` alongside `_sealed_backup_20261118_1522/`. New sealed SSOT SHA-256: `43b351d0ec9cbeca76244511e1f64ce22b12cccba355e683544961b296b08195` (`verify-manifest --exports` exits `0`).
- Viewer bundle rebuilt (`3,733` docs, `has_open_findings=1012`, `needs_owner`: `425` docs / `637` findings, surfacing all `90` `C2_held` and `24` `C2_not_applied`) and served on `http://127.0.0.1:8765`.
- Remaining open items before closing `ct-flq8` / lifting training hold (`ct-u3eh`): owner hand-review verdicts in `viewer/review_notes.jsonl` for the `90` held + `24` not_applied rulings (and other open `needs_owner` findings), plus the noted open items (`56` blind-set docs uncleaned, `>10`-person test coverage, `dd85ac39a196cbaa` source page check).


