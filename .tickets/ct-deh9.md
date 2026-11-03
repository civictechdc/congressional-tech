---
id: ct-deh9
status: closed
deps: [ct-itcg, ct-d0o0]
links: [ct-zpbl]
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

**2026-11-02T15:53:12Z**

2026-11-02 spec-run: html entry proven in full on 5a3121c (124,651 kept rows, 0 differences, 5.79 GiB peak), committed f7b4b594 on candidate-r1b; all five registry entries validate. Selective job (captures rebuild, html re-read, D3, D4) started with the input manifest pinned (f8b509bc).

**2026-11-02T17:34:10Z**

2026-11-02 spec-run: under the size-bound predicate (PAGE_PARSE_MAX_BYTES 25,165,824), the full html proof passed: 124,651 kept rows, 0 differences, 1,056 s, peak 5.57 GiB. All 75,185 missing xml/json bodies were fetched into the mirror as exact stored objects, each verified for stored size, MD5 where captures records it, decoded sha256 and length; three passes, covering 1 truncated read and 6 transient 502/520 errors. Full xml and json proofs are running.

**2026-11-02T17:45:21Z**

2026-11-02 owner direction on RCA items 1-2: don't re-do work unless absolutely necessary; the version hash should be a warning plus a manual check. Filed as ct-zpbl (post-release). This release keeps the current registry and proofs, which are done or running.

**2026-11-02T17:49:45Z**

2026-11-02 spec-run: full html proof (predicate) 124,651 rows, 0 differences; full xml proof (predicate) 118,001 rows, 0 differences; both entered (candidate-r1b 32cac73c). json is blocked: 187 old readings have no new reading. Cause: 211 mirror bodies (187 json plus the 24 bundle bodies) are R2 objects stored gzip under a suffixless key, with Content-Encoding gzip. Production reads the header (readings.py:761, :814); the local path infers gzip from a '.gz' name (readings.py:87, compatible_proof.py:114, :138), so sniff says 'other'. Owner decision: the reader detects gzip itself, verified by the body sha, through one shared helper (_page_entity's rule) replacing suffix inference; no leaf-parser pin may move. impl-e2 is implementing on r1b-det; spec-run stays paused before D2.

**2026-11-02T18:17:08Z**

2026-11-02 spec-run: json full proof after the gzip-detection fix (r1b-det 1313aead; only the readings bundle moved to 586d05c9): 2,489 rows, 0 differences, 58 s, peak 2.28 GiB; entered as candidate-r1b 60eb6963. The registry holds sniff (lock_only), html, xml and json (predicate, full, size-bounded). D2/D3 started 13:16; they need the registry, so they can't overlap the proof. D4 follows from this run's D1-D3 tables, on release-train code (r1b-h3 moves the meeting, appearance, video and committee pins).

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
