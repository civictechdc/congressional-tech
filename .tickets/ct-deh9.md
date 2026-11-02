---
id: ct-deh9
status: open
deps: [ct-itcg, ct-d0o0]
links: []
created: 2026-11-01T20:08:13Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [etl, parser-versions, phase2]
---
# Select compatible parser versions through one shared view with a raw primary-key preflight

Narrow parser fixes currently re-stamp unchanged rows. Allow declared compatible versions without weakening completeness admission. Split from ct-9gmr after independent review.

## Design

1. A registry of compatible versions, each with the predicate proving its rows are unaffected.
2. One selection view, used by pinned-readings, link-inputs, profile-completeness and archive_model_profile.py, which filter separately today.
3. Natural keys are the table primary keys: readings (body_sha, parser, parser_version); filename_readings (filename, source_url, catalog_version); D4 (record_sha, source, parser_version).
4. The preflight runs on raw primary-key rows before selection and rejects. Use GROUP BY ... HAVING, not COUNT(DISTINCT (a,b)), which exhausted resources on both engines when tested.
5. Prefer an anti-join over a window (measured 2.7s vs 4.8s at 1.35M rows). Respect the AGENTS.md rule against aggregating captures or readings before a candidate join.

## Acceptance Criteria

- validate_parser_versions, archive_model_job.py and profile-completeness.sql accept the registry; older compatible versions are not reported missing.
- A differential proof shows non-matching rows are unchanged between versions.
- The preflight fails on an injected duplicate primary key.
- Tests run on the pinned engine through scripts/dev.py.


## Notes

**2026-11-02T04:01:45Z**

Code on worktree-agent-a5550c04138214670 @ b3c4aa3c (b3c4aa3c). Review: merge, stay open, unwired because impl-c SQL was frozen. Non-true predicates cannot prove: a table against itself gives only_new 18,251; limit new rows to predicate keys. Proof numbers are self-reported; bind them to old and new pins and the predicate. Replace the load_schema monkeypatch with the real schema. Sorting 192K wide rows failed at a 4 GiB pool; the materialized form is unmeasured.
