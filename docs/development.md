# Python development and validation

Use the root `uv.lock` for the six maintained Python members. Each checkout gets
its own `.venv`; editable imports must point into that checkout. Python 3.12.13 is
pinned in `.python-version` and checked by doctor. The exact patch matters because
accepted publication receipts bind the runtime; explicit resume must recreate it.
CI and `uv sync --locked` read that pin. A future runtime update is deliberate and
old accepted attempts require their original revision and runtime. The workspace is not a distributable package.

```bash
# macOS prerequisite; doctor reports this remedy without installing it.
brew install poppler
# Ubuntu prerequisite:
# sudo apt-get install poppler-utils procps
uv sync --locked
source .venv/bin/activate
python scripts/dev.py doctor
python scripts/dev.py prepare-baseline
python scripts/dev.py inventory
python scripts/dev.py test production-offline
python scripts/dev.py test active-experiment-regression
```

`doctor` checks Python, all six import locations, the locked PyArrow version and
both Poppler commands (`pdfinfo`, `pdftotext`) and the `ps` command used by
the PDF memory guard. Import and command probes have
bounded timeouts. Missing native commands fail before pytest starts.
`prepare-baseline` may fetch exactly commit
`38f75574d217d3e4908e3f37e0c0906b1090990a` from `origin` when it is absent. It checks
that identity against `content_rule_freeze.json` and verifies the historical
parser SHA256. Test preflight only checks the local object; it never fetches or
substitutes today's parser. The active worker fixture uses development PDFs,
not the held-out sample.

`test-suites.toml` is the maintained lane declaration. `inventory` checks tracked
and untracked nonignored `test_*.py` files throughout the checkout and fails for
unassigned files or missing declared roots. Shared directory roots intentionally
cover new production tests; each experiment test file must be assigned explicitly.

| Lane | Checks | Boundary |
| --- | --- | --- |
| `production-offline` | Production, package and workflow regressions, excluding `loopback` tests | The Python socket wrapper is an in-process tripwire. Fresh subprocesses are not network-isolated. |
| `native-loopback` | Tests marked `loopback`, including real local servers, spawned workers and Rust transport | Requires an executable `SOURCE_FETCH_BINARY`; skips are reported and do not establish qualification. |
| `active-experiment-regression` | All fourteen experiment test files, including the historical/current PDF worker fixture | Fixtures and mocked evidence; this does not reproduce or qualify the frozen research run. |
| `frozen-reproduction` | Reserved for deliberate historical reproduction | Separate frozen requirements and reviewed experiment protocol; no tests are silently retained-only. The command refuses to run it in the shared environment. |

Run a focused file or node with repeatable `--path`. Pass additional pytest
options after `--`:

```bash
python scripts/dev.py test production-offline --path tests/test_image_tools.py
python scripts/dev.py test active-experiment-regression --path docs/experiments/filename-patterns-20261015/test_pilot_evaluate.py -- -x
```

The native lane uses the same source-fetch toolchain as the capture workflow:

```bash
rustup toolchain install 1.89.0 --profile minimal
cargo +1.89.0 build --locked --release --manifest-path packages/source-fetch/Cargo.toml --bin source-fetch
export SOURCE_FETCH_BINARY="$PWD/packages/source-fetch/target/release/source-fetch"
python scripts/dev.py test native-loopback
```

The validation workflow runs all three active lanes. The meetings job runs the
production and active experiment lanes before acquiring any source. Both use
`.github/actions/setup-python-project/action.yml`, which installs Poppler,
syncs the lock, prepares the historical object and runs doctor/inventory. The
devcontainer uses the same sync and checks. Native lane success still requires
reviewing pytest's reported skips.

## Lock migration and preserved research

The root lock replaces `packages/congress_api/uv.lock` and
`packages/youtube_api/uv.lock`. Internal dependencies use workspace sources;
member-level `uv sync` now uses the root workspace. Pip-based legacy callers do
not consume those locks or uv source mappings and still install every local
package explicitly.

The migration retains every registry version in the prior congress-api lock and
all nonconflicting versions in the prior youtube-api lock. Two shared entries
resolve to the already-used congress-api versions: `google-auth` 2.43.0 → 2.58.1
and `pyasn1` 0.6.1 → 0.6.4. Previously unlocked `PyYAML` 6.0.3, `setuptools` 84.0.0,
`surt` 0.3.1, `tldextract` 5.4.0, `requests-file` 3.0.1 and `filelock` 4.2.0 use the
existing development environment's versions. No package requirement range was
widened. PyArrow stays at 25.0.1, Pillow at 12.3.0 and pypdf at 6.19.0.

The historical experiment's `requirements.lock` remains separate, including its
original versions and local source reference. Reproduction requires its original
protocol and an isolated runtime; the shared workspace is not a replacement.
The frozen capture workflow, parser hashes and 3.1.0 catalog-applicability rule
remain intact. The capture workflow's old package-lock path filter is preserved
as part of that freeze; it still installs with pip. Moving capture to this shared
setup requires a deliberate future freeze decision.

See uv's [workspace documentation](https://docs.astral.sh/uv/concepts/projects/workspaces/)
for member selection and the shared lock behavior.
