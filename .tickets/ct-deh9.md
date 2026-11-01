---
id: ct-deh9
status: open
deps: [ct-itcg, ct-d0o0]
links: []
created: 2026-11-01T20:08:13Z
type: task
priority: 2
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

