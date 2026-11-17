---
id: ct-na9t
status: in_progress
deps: []
links: []
created: 2026-11-17T18:18:49Z
type: task
priority: 2
assignee: mikewolfd
tags: [ci]
---
# Small CI gaps left after 2026-11-17

From ct-hs34: tests that run in no CI lane (test_upload_byte_identity loopback test; the storage-loopback lane); bls-cpi-update installs unpinned packages with pip; 17 Dependabot alerts cleared by one aiohttp patch bump.

## Acceptance Criteria

Each is fixed by a green pull request or closed with the reason.


## Notes

**2026-11-17T18:30:38Z**

Findings (re-derived from test-suites.toml, scripts/dev.py and every workflow, not from ct-hs34's list):

1. Lanes CI runs: production-offline (validate-explorer, six shards), active-experiment-regression and native-loopback (validate-explorer validate job), explorer-mcp (validate-congress-mcp, publish-congress-mcp). No workflow runs storage-loopback; frozen-reproduction is empty by design. File-level inventory assigns every test file to a lane, but production-offline deselects `loopback` tests, so a loopback test runs only in a loopback lane whose roots hold its file. Loopback-marked files: congress_api test_r2_body_files_native, test_rust_fetch_native, test_body_text_origin, test_producer_records_loopback (all run by native-loopback via its packages/congress_api/tests root); viewer_publication test_recovery_publication_journey (native-loopback, listed); test_archive_multipart.py (storage-loopback only: runs nowhere in CI); test_upload_byte_identity.py::test_real_boto_put_consumes_the_checked_body (in no loopback lane: runs nowhere). Both missing ones are S3 SDK against a local HTTP fake: they need no source-fetch binary or live storage and can run on a hosted runner. native-loopback takes about 1 minute in the validate job.
2. bls-cpi-update.yml runs pip install pandas openpyxl requests. Neither script imports openpyxl or reads Excel (fetch-cpi-convert-csv.py calls the BLS JSON API and reads/writes CSV); inflation-gsheets is a workspace member whose pandas and requests are in uv.lock. update-data.yml already installs locked workspace packages with setup-uv 0.11.21 and uv sync --locked --no-dev --package.
3. Open Dependabot alerts (gh api, 52 open): 17 aiohttp (uv.lock, 3.14.3, patched 3.14.4; 13 high), pulled in only through aiobotocore (congress-api). Separately, 17 filelock alerts (uv.lock, 4.2.0, patched 4.2.1) are another single patch bump, not in this ticket's scope.

**2026-11-17T18:36:40Z**

Done on branch ct-na9t-small-ci-gaps, one commit per item:
1. native-loopback (which validate-explorer's validate job runs) now lists test_archive_multipart.py and test_upload_byte_identity.py; storage-loopback stays a local subset (scripts/run_lanes.py) and gains the second. Guards in .github/tests/test_offline_shards.py: a lane no workflow runs may hold only files a run lane with the same marker selects; every file with a loopback marker sits under a run loopback lane's roots. Both guards fail on main's test-suites.toml, naming storage-loopback and exactly those two files. The two files pass locally (32 loopback tests).
2. bls-cpi-update.yml installs inflation-gsheets from uv.lock (setup-uv 0.11.21, uv sync --locked --no-dev --package, as update-data.yml). openpyxl was never used (no read_excel in the app's history). The workflow itself runs only on its schedule or dispatch, so the pull request does not exercise it; dispatch it once after merge.
3. aiohttp 3.14.3 -> 3.14.4 in uv.lock, the only package that moved, plus an aiohttp>=3.14.4 constraint floor. definition-change.py: model definition and job pins unchanged.
Not in scope, found while checking: 17 more Dependabot alerts on filelock 4.2.0 in uv.lock are cleared by one patch bump to 4.2.1.
