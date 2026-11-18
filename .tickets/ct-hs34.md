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

**2026-11-17T17:05:00Z**

More from the reviews of 2026-11-17, not done:

12. Every retry of a stopped night rebuilds the model (about 22 minutes, 10 GiB): hosted runners keep nothing, so committing a cause record and re-running repeats the build of an identical candidate. Six of the day's eight publish runs did. Keep the built candidate (about 170 MB) keyed by its input identity and resume at the gates.
13. The fetch queue holds case variants of addresses already saved (`EventSingle.aspx` beside `eventsingle.aspx`), so the capture fetches the same page again and its link key changes. This produced the 2026-11-17 recapture. Do not queue an address whose normalized form is already saved.
14. A blind review judged gate 1 overbuilt for nights where only the data moved: with an identical definition, absolute checks (invariants, contract, canary, a column emptied, rows removed, links intact) may be enough, without a cause for every unverified difference. Owner decision; would replace the per-group shape list and caps in `data_only_night.py`.
15. The idle-connection fix (f051364a) has not yet been exercised by a night with a long daily ingest; the retry that passed had nothing left to ingest.
16. Item 1 again: Dependabot pull requests still cannot be validated until the engine credential is a Dependabot secret.

**2026-11-17T19:10:00Z: where each item stands**

Done: 5 (the two orphaned loopback tests run in CI and a guard test keeps new ones from appearing; the macOS-only skips stay as they are), 7 (CPI job installs from the lock; openpyxl was never used) and the aiohttp part of 3, all in pull request 191 (ct-na9t). 13 closed with no change: measured, the queue holds no saved address, only case variants kept apart on purpose (ct-1qr7). 15 is superseded: an unacknowledged write is now looked for before the job fails (pull request 189).

In review: 9 and 11 (ct-medh, pull request 193), 12 (ct-31qi, pull request 192).

Has its own ticket: the rest of 3's filelock alerts (ct-f4lk); the record-chain reads that grow by one a night (ct-k7rw).

Owner only, repository settings: 1 and 16 (the engine credential as a Dependabot secret), 2 (required checks in branch protection).

Waiting on evidence, no action now: 4 (the late cron is accepted and written down in docs/nightly.md), 6 (refresh shard durations when convenient), 8 (first Sunday refresh under the data-only gate), 10 and 14 (owner decisions about the gate's shape; leave the caps alone for seven scheduled nights first). The lxml and soupsieve alerts in 3 each need an equivalence decision because they move parser versions.

**2026-11-17T21:25:00Z**

Item 6, tried and taken back out: refreshed from main's green run 44162145022, `packages/viewer_publication/tests/test_archive_selective.py` measures 1,093 s by itself (879 s recorded before), over the 1,050 s a shard may hold, and the guard test refused the refresh. One file cannot be split across shards. Split that file (64 cases; `test_fresh_process_resume_matches_an_uninterrupted_run` is 213 s over five cases) and then refresh; do not raise the budget to fit it.

Item 3: 23 more alerts cleared by pull request 194 (ct-f4lk closed); what is left is listed there.

**2026-11-17T22:20:00Z: owner decisions (questions tool) on the owner-only items**

- Items 1 and 16 (Dependabot pull requests cannot be validated): no Dependabot secret. Dependency updates are gathered into one squashed change, tested and merged ("Squash all locally, test and merge"). First such batch: pull request 197, every open alert that has a fix (lxml, soupsieve, idna, requests, dnspython, rustls, astro with Node 22.23.5), with a 400-body reader comparison for the lxml and soupsieve move. picomatch has no patched release.
- Item 2 (branch protection requires no checks): "Require checks to merge". Pull request 198 adds the always-running merge gate and the rule file `.github/rulesets/main.json`; the rule is applied after it merges.

**2026-11-18T19:16:42Z**

2026-11-18 where each item stands.
Done: 2 (main requires the merge-gate check since 2026-11-18, ruleset 27549282; a pull request with checks running was refused, and admin pushes of tickets and docs go through with GitHub noting the bypass); 3 (pull request 197 cleared 11 of 12 alerts; picomatch has no patched release; lxml moved four producer identities, kept under reviewed equivalence on 66,490 re-produced records).
Changed: 1 and 16 (Dependabot pull requests cannot be validated) no longer block anything by the owner's decision of 2026-11-17 to batch updates by hand.
Open: 4 (the capture cron fires 7 to 9 hours late and later each day: 10:42, 11:15, 11:47, 12:07 UTC on 11-14 to 11-17, and 11:57 on 11-18; owner to accept it or trigger from outside GitHub); 6 (split test_archive_selective.py before refreshing shard timings); 8 (Sunday's weekly refresh may trip the unattended rule's caps); 10; 14; 15.
Not yet shown: a data job's own push to main under the new rule. commit-and-push.sh stamps its commit with the merge-gate status first, tested against a local stand-in only. I did not dispatch update-data.yml by hand on 2026-11-18: it is the whole weekly refresh (YouTube, GPO, committee metadata, pipeline data), and running it the evening before the first schedule-started night on the new code would likely stop that night. The first real proof is the scheduled run of Sunday 2026-11-22 00:00 UTC; if GitHub refuses the stamped push the job fails and ci-alerts opens an issue.
Also from today: the publish re-run after a cause record rebuilt instead of resuming (ct-31qi); the first schedule-started night on the final code is 2026-11-19.
