# GPO evidence and ZIP buffer efficiency — 2026-10-26

Settled GPO acquisition now skips rewriting unchanged retained evidence. ZIP range reads freeze their buffer once after completion or when retaining a rejected/partial response. CSV/pending writes, manifest preflight, range cache, version checks, receipt fields and stream cleanup keep their existing owners and ordering. No MODS cache, XML proof changes, Arrow changes or storage-format changes are included.

Baseline: `7242f0419f589ffcf9e52f5f5068fb4edd5b6c44` (local integration baseline; pushed main remained `0bfeb21e`). The prior survey is `output/duplication-validation-20261026/gpo/report.md` in the primary checkout. Implementation was isolated in branch `codex/gpo-xml-boundary`, worktree `/Users/mikewolfd/.codex/worktrees/gpo-xml-boundary/congressional-tech`.

The collector compares only records returned by acquisition/backfill, rather than copying or serializing the entire evidence snapshot to detect a no-op. Transcript backfill builds the updated nested transcript dictionary before comparison so a mutation cannot hide its own change. New success and failure observations still trigger persistence before CSV completion and pending removal. A missing empty evidence file is initialized once. Loading retained evidence still validates digests.

The transport retains a mutable local buffer during streaming. It freezes on success, byte-limit refusal, or a caught transport interruption. It clears the local buffer reference after successful materialization so a later context-close failure reuses those same bytes. Rejections after response validation retain the complete received body. Preflight and standard-library ZIP validation are unchanged.

## Measured operation counts

One deterministic offline run per arm, Python 3.12.13, installed dependencies unchanged. The maintained fake range transport supplies identical archive bytes to both arms; all member/rejection SHA-256 values match across arms. Fake collection/MODS responses and a dummy key avoid network and credential access. Pacing is disabled only in the measurement harness because counts, not time, are measured.

| ZIP fixture | Baseline copies / copied bytes | Candidate copies / copied bytes | Requests before → after |
| --- | --- | --- | --- |
| Successful selected member | 16 / 426,272 | 4 / 65,680 | 4 → 4 |
| Oversized first response | 9 / 360,469 | 1 / 65,557 | 1 → 1 |
| Interrupted stream | 2 / 24,576 | 1 / 16,384 | 1 → 1 |
| Incorrect Content-Range | 10 / 426,026 | 1 / 65,557 | 1 → 1 |
| Changed ETag | 12 / 426,086 | 2 / 65,587 | 2 → 2 |

Success copies 84.59% fewer bytes in this fixture. Every recorded response stream closes. This measures copy work, not wall-clock or production throughput.

The settled collector fixture makes zero upstream requests in both arms. Baseline rewrites 1,740 byte-identical gzip bytes once; candidate writes **zero evidence bytes**. A subsequent malformed MODS response still causes one evidence write, retains exact rejected bytes and the prior CSV, keeps the new version pending, and exits 1 in both arms. Failure gzip sizes differ slightly because recorded retrieval timestamps differ; compression size is not an optimization claim.

Raw observations, source-file hashes, and the bounded harness are retained in [gpo-io-efficiency-20261026/](gpo-io-efficiency-20261026/): `baseline.json`, `candidate.json`, `measure.py`, and `harness-failure.txt`. The candidate observations were made on the dirty candidate over the baseline HEAD; file hashes identify the exact measured implementation. Local collector fixture files are preserved under `output/gpo-io-efficiency-20261026/`. The initial harness-only attempt rejected a missing keyword argument in its pacing override; this is recorded and corrected without changing criteria.

From this worktree, reproduce an arm with:

```sh
env PYTHONDONTWRITEBYTECODE=1 /Users/mikewolfd/Work/congressional-tech/.venv/bin/python docs/experiments/gpo-io-efficiency-20261026/measure.py SOURCE_CHECKOUT OUTPUT_JSON
```

`SOURCE_CHECKOUT` must contain the desired baseline or candidate source. The harness imports this commit's focused fixture helpers and uses the selected checkout's application modules. It only writes the designated output JSON and fresh fixture directories beside it. Retain earlier JSON before repeating a trial.

## Focused verification

The existing XML/ZIP/source-fidelity baseline passes **75 tests**. The first eight new checks fail on the baseline for the intended redundant writes/copies. Final checks pass **149 tests in 5.03 seconds**, including ten new cases for settled writes, parser refresh, new failure and pending retry, changed/equivalent transcript backfill, missing-file initialization, evidence-write failure ordering, and successful/oversized/interrupted/invalid-range/changed-ETag buffers. Existing tests additionally cover digest corruption, CRC corruption, allocation limits, encoding, source-version changes, streamed retry cleanup, workflow ordering and package boundaries.

Executed final command from the owned worktree:

```sh
env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=packages/congress_api/src:packages/congress_shared/src:packages/committee_meeting/src:packages/docspec_client/src /Users/mikewolfd/Work/congressional-tech/.venv/bin/python -m pytest -q -p no:cacheprovider packages/congress_api/tests/test_gpo_io_efficiency.py packages/congress_api/tests/test_gpo_acquisition_xml_failures.py packages/congress_api/tests/test_zip_member_transport.py packages/congress_api/tests/test_gpo_source_fidelity.py packages/congress_api/tests/test_gpo_csv_writer.py packages/congress_api/tests/test_congress_api_boundaries.py packages/congress_api/tests/test_congress_api_imports.py packages/congress_api/tests/test_http_policy.py packages/congress_api/tests/test_http_response_metadata.py
```

`git diff --check` passes. No full release build, external acquisition, publication, push, deployment or main merge was performed. Integration must cherry-pick the resulting GPO commit; operational qualification is separate. The optimization still reads/validates existing evidence and writes CSV/pending state; it removes only the two measured redundant operations.
