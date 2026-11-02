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

**2026-11-02T12:28:28Z**

Round 1b 2026-11-02 (lead): Readings: sniff, xml and json are lock-only or proven unchanged (xml 260/260, json 260/260 byte-equal across 45/32 strata; proof .cache/rounds/r1b/g/differential/xj_proof.json). html is compatible outside HTML_REREAD_SQL (67,540 of 192,191 re-read). Re-stamp deleted. impl-e2, r1b-e2.

**2026-11-02T13:08:43Z**

2026-11-02 (lead): the html re-read set (67,540 bodies, one html parser_version, 1 already local) and the D4 candidate bodies (16,102 non-MODS, 446 MODS; 725 were missing) are now in the local mirror. All 68,264 downloads were checked: size and MD5 against captures, then sha256 and size of the decompressed bytes. The filename catalog (D3) reads no body bytes.

**2026-11-02T14:19:08Z**

2026-11-02 spec-run: on candidate-r1b (integrate + e1 2deb969a + e2 6cdc1825 without e73505b2 + g 89285289; pins ae2fa2a3; registry 17bc2892), the registry proofs show 0 differences: sniff 2,000 rows, xml 2,000, json 123, readings bundle dd70d745 25 (decision bodies fetched and sha-matched). The html proof failed on a defect in prove_unchanged (dedda4f0): it compared new-side rows that leave the re-read set (1,147 intended fingerprint fills), while the 817 rows outside the set on both sides matched. Fix: compare old-side rows outside the predicate (impl-e2). D4 selection refuses without a D4 run, so D4 runs speculatively now and again after impl-f.

**2026-11-02T14:46:34Z**

2026-11-02 (lead): red-e2 (request changes): prove_unchanged fix 8240567c confirmed. Open items: 1-row sample proofs accepted for whole and predicate bases; an html whole entry accepted despite its re-read set; two old versions can select one body; the proof tooling lives in the bundle-hashed file and moves the readings pin. Sent to impl-e2.

**2026-11-02T15:35:26Z**

2026-11-02 spec-run: registry entries proven with 0 differences (sniff lock_only 2,000; xml whole 2,000; json whole 123; bundle dd70d745 full 25). The full html proof hit a HashJoinInput refusal on the frozen eb40c54 engine (pool 14 GiB, peak 12.8 GiB, readings.plan → pending_bodies over 124,651 bodies / 322,923 captures; known_formats inlined 3x, expression-key joins; plan in .cache/archive-release/r1b-run/explain/html-pending/). Re-running on 5a3121c (ss-ud8y fixes that class). The bundle proof is flaky on one 38.8 MB XML body (ct-61ys).
