---
id: ct-a3le
status: closed
deps: []
links: [ct-8kl2, ct-mi03, ct-czsd, ct-2ukk, ct-oc2g, ct-xu1o, ct-8ax6, ct-dzyf, ct-13cn, ct-dmca, ct-gziq, ct-n6lj, ct-sb0s, ct-te1p, ct-aia9, ct-2yl5, ct-bwac, ct-gi01, ct-d8cf, ct-4nyy, ct-5kto, ct-77zb]
created: 2026-10-21T20:53:32Z
type: task
priority: 2
assignee: mikewolfd
external-ref: ss-023x,ss-65bz,ss-6gwu
tags: [house, diagnostics, tests, cleanup]
---

# Keep the House-site diagnostic with its maintained code

Keep the operator's exact-request diagnostic and its two tests usable when historical research folders move. Two tests in `packages/congress_api/tests/test_house_diagnostic_recovery.py` dynamically import `docs/youtube-coverage/research/scripts/probe_house_sites.py`. Production retry tests in that file already call maintained collector code. Earlier site test cleanup is delivered; News Lake belongs to `ct-d8cf` and `ct-4nyy`.

## Acceptance Criteria

- Move the single diagnostic implementation to an importable Congress API CLI module and import it directly in the two diagnostic tests. Preserve its request/output flags, retained response bytes and digest, response closure, discovery results, and distinct files for different POST requests to the same URL. Keep the production collector and its tests separate.
- Update the existing operator invocation, preserve the historical research record, and verify the new local CLI help and scoped diagnostic tests with mocked requests through the declared test lane. No live request is needed for this move.
- Verify that `apps/site`, `packages`, `scripts` and `.github/workflows` contain no executable imports or CI hashes of `docs/youtube-coverage` files. Distinguish prose links and the separate historical test-suite root from executable dependencies.
- Keep this as standalone maintenance. The completed News bridge ticket `ct-n6lj` is not a prerequisite. Preserve prior audit history, transferred News ownership and the existing Phase 2 acceptance owners.

[Third-round root-cause analysis](../docs/plans/production-mvp-root-causes-round3-20261105.md).

## Audit 2026-10-24

- Verdict: PARTIAL (batch kl2a1aa).
- Grades: proposal 87 → 87, work 74 → 74.
- Problem: C5 leak, reproduced by the fork reviewer: expiry is computed only from captures present in the read (analysis/export.py:83-88; docspec/export.py:84-91), so a versions-only read exports expired text.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/kl2a1aa/kl2a1aa-verdicts.md:40
- Status: Reopened. Unmet: AC1's cross-table C5 redaction (a subset read exports expired text); owner WS8 fix 4 (ct-d8cf), and under the engine-first rule the fix goes into the engine's export-rights policy, not a second Python gate. AC2 (3 tests still load scripts from `docs/youtube-coverage`) has no plan owner and stays here.
- See docs/reviews/2026-10-24-ticket-audit/README.md

## Notes

**2026-11-05T17:11:15Z**

Scope narrowed on 2026-11-05: retain only the remaining non-News diagnostic dependency on docs/youtube-coverage/research and its scoped import/CI-hash check (packages/congress_api/tests/test_house_diagnostic_recovery.py:59–64). Preserve the diagnostic behavior while moving the helper to a maintained location. News upserts, bridges and legacy news export retirement move to ct-d8cf; C5 cross-table rights/expiry moves to ct-4nyy. Earlier site cleanup remains completed evidence. Standalone and linked to ct-77zb/ct-5kto for context; do not make this diagnostic-only cleanup a new Phase 2 gate.

**2026-11-05T20:18:16Z**

Applied the accepted third-round scope update. The current description records the root cause, delivered work, remaining behavior and bounded checks; historical notes remain unchanged. No implementation or operational action was performed. [Third-round root-cause analysis](../docs/plans/production-mvp-root-causes-round3-20261105.md).

**2026-11-05T21:17:22Z**

Merged in `030b91d6` via independently reviewed commit `9afc8670`. The single diagnostic moved byte for byte to `congress_api.cli.probe_house_sites`. CLI help and the 33-case diagnostic and recovery file passed in the focused production-offline run. Both mocked probes verified the saved bytes, digest, response closure, discovery, and separate files for distinct POST bodies at the same URL. The scoped audit found prose and navigation references, with the historical test-suite root separately declared. [Quality lane evidence](../.cache/archive-release/implementation/production-mvp-round3-20261105T205727Z/quality/STATUS.md)
