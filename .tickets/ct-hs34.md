---
id: ct-hs34
status: open
deps: []
links: []
created: 2026-11-17T11:28:14Z
type: task
priority: 2
assignee: mikewolfd
tags: [ci, hosted]
---
# CI gaps found by the 2026-11-17 workflow survey that are not fixed yet

Left open after ct-pz32's CI hardening (99d4bfcc..ba607808, b8b50642). Evidence: .cache/archive-release/reviews/ci-health-20261117/REPORT.md and the agent reports of 2026-11-17.

1. Dependabot pull requests cannot be validated: runs Dependabot triggers get no Actions secrets, so setup-local-job-runtime fails for want of DOCSPEC_ENGINE_CREDENTIALS. Needs that value added as a Dependabot secret (owner, repository settings), or someone pushing to each Dependabot branch.
2. Branch protection requires no checks, so a red push validation blocks nothing (owner, repository settings).
3. 51 open Dependabot alerts (20 high); security-update PRs are off. One aiohttp patch bump (3.14.3 to 3.14.4) clears 17. lxml and soupsieve bumps move byte-hashed parser versions and each need an equivalence decision.
4. The capture cron (03:23 UTC) starts 7.3 to 8.4 hours late, so the nightly really runs around 11:00 to 12:00 UTC. Accept and document, or trigger capture from a Cloudflare Worker cron with a fine-grained actions:write token.
5. Tests that run in no CI lane: test_upload_byte_identity.py::test_real_boto_put_consumes_the_checked_body (no lane); test_archive_multipart.py (storage-loopback lane, which no workflow runs). Skips that hide a real check in CI: test_body_text_derivation.py:97 (Apple Vision OCR rule, macOS only), test_docmeta_v6_1_ingestion.py:362 (needs a local .cache bundle), test_body_text_origin.py:268 (live-origin network test).
6. Recorded shard durations (.github/scripts/test-shard-durations.json) lack 24 or more test files against a limit of 25; refresh from passing JUnit output once every shard is green on main (dev.py refresh-shard-durations --merge).
7. bls-cpi-update.yml still installs unpinned pandas/openpyxl/requests with pip: openpyxl is not a declared dependency of apps/inflation_gsheets, so uv sync --locked cannot serve it without a lock change.
8. First Sunday under the data-only gate (weekly pipeline-data refresh) may exceed its caps and stop for a record; tune the caps from that report.

## Acceptance Criteria

Each item is fixed, or closed with a recorded owner decision.


## Notes

**2026-11-17T14:20:00Z**

Added from the gate 5 review of 2026-11-17 (`.cache/archive-release/reviews/gate5-chain-20261117/REVIEW.md`):

9. The nightly's preflight (`lake/daily.py` `_producer_bases`) accepts any existing head record, while gate 5 judges it: daily can append onto a base the gate then refuses (an operator record from an unmerged commit, a staged delta), which stops every later night after the append. Move the gate's base-acceptance check into `congress_api.lake.producer_records` and call it before daily appends.
10. Since the fix that lets a daily chain end on another registered producer's snapshot, a chain's trust root can be a bucket record an operator script wrote (the 2026-11-17 capture integration, ct-z4w5), not only a checked-in import anchor. A stronger rule: have the capture path write a standard `base` and keep walking through it. Owner decision.
11. Out-of-band writes to production lake tables between nightlies (operator integrations) are not coordinated with the hosted nightly; they share no lock with `raw-source-mirror`.
