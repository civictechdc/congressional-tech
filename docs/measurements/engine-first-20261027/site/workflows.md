# F1 workflows and phase-one F4 receipt evidence

At `547f18e6`, the full `production-offline` lane ran with the explicit `engine-37ccde0` local snapshot: **11,612 passed, 33 failed, 3 errors, 117 skipped, 50 deselected**, in 568.89 seconds. All 36 baseline failure identities match; none were added or removed. The first full attempt stopped on a remaining legacy workflow-test import; the forward fix migrated only its retired workflow assertions, retaining the preparation/helper tests (62 focused checks passed).

The workflow/helper group passed 185 focused checks. Review fixes passed 23 checks; the merged native prerequisite runner group passed 40; seven capture-shell checks verify exact arguments, weekly seeds and budget refusal. A fresh production-origin Astro build and the hand-release browser contract passed desktop, phone-sized and changed-release 404 checks. Two recorded missing-body reads reached the local fixture store. F0's saved-copy canary passed in **13.25 seconds**, and its desktop/phone/404 contract passed. These are local profiles, not real-device qualification.

Both independent review sets identified bounded concerns: local contract/canary order, writer account settings, and production-origin fixture body reads. Forward fixes bind the order and endpoint variables and isolate fixture reads in the browser harness. No extra review round was performed. DM §8.1 now defines the agreed receipt-list bytes and field name.

The disabled viewer workflow and its 30-minute cron are gone: **287 → 0 lines**. Engine confirmed that the direct owner instruction authorizes this specific deletion. Other old capture paths remain until the switch. The new capture wrapper remains disabled by `ARCHIVE_CAPTURE_ENABLED`; raw confirmed its flags and need for a pinned local native runtime. The added local-runtime preflight has seven focused passing checks; the approved Linux local-job distribution remains an owner gate.

Local commands, using an explicitly approved `DOCSPEC_JOB_CONFIG` where required:

```sh
.venv/bin/python scripts/dev.py test production-offline
VIEWER_BENCHMARK_MODULES="$PLAYWRIGHT_MODULES" npm --prefix apps/site run contract:archive-ci --workspaces=false -- --work "$EVIDENCE/hand" --browser-executable "$CHROME"
.venv/bin/python -I .github/scripts/run-archive-job.py publish
.venv/bin/python -I .github/scripts/run-archive-job.py backfill
.venv/bin/python -I .github/scripts/run-archive-job.py maintenance
```

The last three commands deliberately refuse their pending bindings. Engine owns their real stages and specs, including adopting the receipt helpers before an unchanged-output stop and before retention. No live publication, deletion, workflow dispatch, GitHub API call or push ran.

Owner configuration names, never read: `ARCHIVE_PUBLISH_ENGINE_CREDENTIALS`, `ARCHIVE_PUBLISH_R2_ACCESS_KEY_ID`, `ARCHIVE_PUBLISH_R2_SECRET_ACCESS_KEY`, `ARCHIVE_MAINTENANCE_ENGINE_CREDENTIALS`, `ARCHIVE_MAINTENANCE_R2_ACCESS_KEY_ID`, `ARCHIVE_MAINTENANCE_R2_SECRET_ACCESS_KEY`, `ARCHIVE_CAPTURE_R2_ACCESS_KEY_ID`, `ARCHIVE_CAPTURE_R2_SECRET_ACCESS_KEY`, `DATA_GOV_API_KEY` (Congress.gov header authentication), and optional existing `ZYTE_TOKEN`. Public variables supply the account, pointer, budgets and approved runtime descriptor. The offline CI lane requires an approved **local** Linux configuration; the remote credential-bearing runtime cannot satisfy that prerequisite. Actual consumer integration, real-device targets, uploaded HTTPS acceptance and the switch remain explicit gates. Spicy-regs pins remain phase two.
