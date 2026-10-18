# Environment implementation validation — 2026-10-18

The shared environment and focused portability checks pass locally on macOS and
Linux. The complete macOS native lane also passes, as detailed below. These
results establish local behavior, not a hosted CI run, frozen research
reproduction, production release or complete Linux native qualification.

The root workspace enumerates six Python members, resolves their editable
imports to this checkout, and replaces two active package locks with one root
lock. The [development guide](../../development.md) records every dependency
reconciliation and the separate frozen requirements. A machine comparison of the
new lock to the documented migration seed found zero additional version changes
and zero unexpected registry packages. `uv lock --check` passed.

| Environment | Checks | Result |
| --- | --- | --- |
| macOS, Python 3.12.13, Poppler 26.06.0 | Image/PDF fixtures (`test_image_tools`, `test_pdf_reader_recovery`, `test_pdf_metadata_refresh`, `test_explicit_document_forms`) | 89 passed, 6.30 s |
| macOS, same runtime | All fourteen active experiment files | 241 passed, 4.71 s |
| macOS, same runtime | Final environment and meetings-workflow regression tests | 13 passed, 0.38 s |
| Debian Bookworm ARM64 container, Python 3.12.15, Poppler 22.12.0 | Image/PDF fixtures plus environment and workflow tests | 101 passed, 6.49 s |
| Linux, same runtime | All fourteen active experiment files | 241 passed, 12.88 s |
| Linux, same runtime | Final preflight tests after adding the missing-`ps` assertion | 10 passed, 0.17 s |

Both platforms used PyArrow 25.0.1, Pillow 12.3.0 and pypdf 6.19.0. Doctor and
inventory passed. The inventory assigned 314 test files at this validation point,
including fourteen explicitly enumerated experiment files; marker-selected lanes
may share production files. The historical baseline object and parser hash
matched the unchanged freeze. Regression fixtures do not assert the frozen
research runtime matches these environments.

The first minimal Linux image had Poppler but lacked `ps`. Its run preserved
97 passing checks and three PDF memory-measurement failures. Installing `procps`
and adding `ps` to doctor fixed that setup failure without changing the PDF
reader or its memory guard. The original log remains in
`output/environment/linux-focused.log`; the corrected results are in
`linux-focused-procps.log` and `linux-preflight.log` in the same directory.

The earlier Python 3.12.15 image is `congressional-process-python:local`, image ID
`sha256:1203f1822ae63fa6c2dda0b56cbd0a3902564fbc46aed617e0abfc5d6c567d21`.
The fixture run used `--network none --memory 1536m --cpus 2`, mounted this
worktree at `/workspace`, and used `/opt/venv/bin/python`. The historical Git
object store was mounted read-only. This was a Debian container check; Ubuntu
GitHub Actions remains unexecuted locally.

## Exact runtime and native checks

The maintained workspace now pins Python 3.12.13 in `.python-version`. CI and uv
read that file, the devcontainer selects the same patch, and doctor rejects a
different patch before tests. Publication preparation binds its exact runtime;
the pin lets an explicit restart recreate it. All dependency versions and the
root lock remain unchanged. The earlier Linux 3.12.15 results above remain
separate portability evidence.

The maintained macOS Rust transport built with cached dependencies using
`CARGO_BUILD_JOBS=2 cargo +1.89.0 build --locked --offline --release --manifest-path
packages/source-fetch/Cargo.toml --bin source-fetch`. The build took 1 minute
17 seconds. No Rust source changed and no source documents were acquired.

The first complete macOS native lane had 46 passes and one failure in 71.42 s,
with zero skips. Its test asserted a 512 MiB body-buffer bound while omitting
the option; production had already defaulted to 2 GiB at reviewed base `24137dd`.
The observed 579 MiB reservation was within that production budget. The test now
explicitly passes 512 MiB and names that intent; its existing concurrency,
saved-body, spool and cleanup assertions remain. Production limits are unchanged.
The corrected focused test passed in 0.93 s, then the full lane passed **47 tests,
zero skips, in 69.04 s**. All nine frozen source hashes still match, and this
native test is not among them.

An intermediate retry encountered the file-backed catalog change before its
mock-store migration finished. That failure and an interrupted run (17 passes)
remain separate from the final result. Logs are retained under
`output/environment/native/`; the initial failure is `macos-loopback.log` and
the final complete result is `macos-loopback-final.log`.

The Linux Python-only loopback subset passed 31 tests in 65.96 s on Python
3.12.15. It did not include the Rust transport, so the complete Linux native lane
remains unqualified. The validation workflow builds that binary before running
the complete lane. The frozen `capture-raw-sources.yml`, research requirements,
parser hashes and 3.1.0 catalog applicability rule were unchanged.

The final Python 3.12.13 verification image is
`congressional-process-python:3.12.13`, image ID
`sha256:c9d2d30b8afc862ec42f7879480624fc798473a54807b2610df471a4491d730c`.
It preserves the earlier image and uses the same network-disabled 1,536 MiB,
two-CPU focused-check boundary. Local setup tests passed 14 checks in 0.37 s;
doctor and the unchanged root lock also passed.

On that pinned Linux image, the combined image/PDF, setup/workflow and publication
matrix had 184 passes, two subtest passes and one runtime-identity refusal in
51.56 s. Another implementation commit changed `HEAD` during that test's two
publication calls, so accepted preparation correctly refused the changed code.
The same case passed against stable `HEAD` in 3.93 s. The original mixed-revision
log remains `output/environment/linux-focused-pinned.log`; the focused rerun is
`linux-publication-identity-pinned.log`. All fourteen active experiment files
then passed 241 checks in 11.75 s. Doctor and inventory passed on this image.

## Final integrated revision

After all A–F changes and test-adapter corrections, code revision
`5b128da7c432cde64893fce10c9a167d40a5d616` passed 8,838 offline tests plus 38
subtests, 241 active experiment tests and 49 macOS native tests, with zero skips
in every lane. The native lane now includes two real capacity cases that lacked
the `loopback` marker in the earlier 47-test run. The frozen capture workflow
remains unchanged; maintained CI lane coverage now checks all current marked
cases. The [completion receipt](IMPLEMENTATION-RECEIPT.md) records runtimes,
native executable hash, browser/type/build results and both preserved failed
integration attempts. Complete Linux native qualification remains outstanding.
