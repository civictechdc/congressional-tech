---
id: ct-2cig
status: closed
deps: []
links: [ct-2uc9, ct-flq8, ct-jmwq, ct-u3eh, ct-bwyj, ct-69ly]
created: 2026-11-18T14:01:54Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-ihe7
tags: [docmeta]
---
# DocMeta rule and scorer defects reported by the 2026-11-18 training-set audit

Reported by the training session's audit (fast-gemma4 artifacts/gap_swarm_20261118/SUMMARY.md, items 9, 10, 11, 13; details in its L4_, L5_, L7_ folders). The code now lives in packages/congress_docmeta. Left out of the move (ct-ihe7) because the move had to keep behaviour unchanged. None of these counts has been re-derived here; treat them as leads.

1. Rule R4 (relational_rules_v6.py): labels 'Vice Chairman X' as chair, and _name_parts duplicates a name that carries a trailing comma. Audit: 6 wrong in 40 added people read; 655 people added by R4-R6 in the training gold.
2. Rule R7 (relational_rules_v6.py, the subcommittee name lookup near line 770): the test 'start_year <= y_end' lets the next Congress's subcommittee name match, because y_end is the first year of the next Congress. Audit: 46 valid subcommittees dropped of 106.
3. Lock rule govinfo_chrg_pkg_lock forces hearing_transcript on annual-report reprints (15 to 115 rows); 64 lock rules covering 5,150 queue rows have no labeled document.
4. Scorer (eval_blind.score): held-out gold is edited by the rule being scored (32 of 331 people; people F1 +6.7, headline +1.7 by the audit's figure); dates are matched without their role; a wrong value on a key the gold lacks costs nothing; subcommittee punctuation costs 3.5 to 4.6 points; people are matched on the last word only.

Each fix changes labels or scores, so each needs its own before/after eval and, for the rules, a rebuild of the training gold additions.

## Acceptance Criteria

Each item is either fixed with a before/after eval on valid_sweep and the count of training-gold rows it changes, or closed with the measurement that shows the report was wrong. Scorer changes report old and new metrics side by side for the current production model.


## Notes

**2026-11-20T17:29:15Z**

2026-11-20: Fixed and verified all 2026-11-18 DocMeta rule and scorer audit items — R4 Vice Chair & trailing comma handling, R7 start_year bound, govinfo_chrg_pkg_lock annual-report exclusion, reconcile_queue_lock_v6 in cover_locks_v6.py, and non-mutating gold matching in eval_blind.score (commit 0e554d3f). Verified via test_docmeta_audit_remediation.py, CI run 44776340037, and before/after live MLX hardware eval (.cache/archive-release/docmeta-move-20261117/eval_after_ct2cig_cts9l2_20261120.json).
