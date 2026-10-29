---
id: wor-il4d
status: closed
deps: []
links: []
created: 2026-10-29T08:50:59Z
type: task
priority: 1
assignee: mikewolfd
---
# Release every model relation after its final native reader

Compute complete SQL dependencies with the maintained locked parser; retire unused lazy views and materialized steps safely, and orient corpus join builds.

## Acceptance Criteria

Fixture proves every actual reader remains available and no named step survives its true last reader; native raw-to-release guards and output parity pass; every physical join build is audited with bounded fixture plans.


## Notes

**2026-10-29T09:24:52Z**

Focused source completion at59d4eea4: model suites57PASS; final registry/profile/release/rebuild48PASS; final shared seed/controller/publication/model/lifetime/removal107PASS. Whole-job EXPLAIN covers181 readers and331 physical joins with no unbounded WindowAggExec. Final47 materialized+4lazy providers remain for real exports/guards; metadata and50-body width calibration cannot prove corpus fit. Review continuation pending. Correction to commit-body line counts: archive_seed.py236 to237 at59d4eea4, not269 to270; document-removals.sql8 to17 at542bab86, not8 to16. No history rewritten.

**2026-10-29T09:25:38Z**

SAME independent review APPROVE f720102b..59d4eea4; report S/codex-impl/cx_model_systematic_review/review.md. All review findings resolved; final107 focused shared/model checks passed with bounded physical monitor. Complete graph and331 physical-build audit delivered. Full-corpus retained bytes, hash reservations and fit remain explicitly unqualified and require the lead-owned next corpus attempt.
