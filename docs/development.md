# Python development and validation

Use the root `uv.lock` for the maintained Python members. Each checkout gets
its own `.venv`; editable imports must point into that checkout. Python 3.12.13 is
pinned in `.python-version` and checked by doctor. The exact patch matters because
accepted publication receipts bind the runtime; explicit resume must recreate it.
CI and `uv sync --locked` read that pin. A future runtime update is deliberate and
old accepted attempts require their original revision and runtime. The workspace is not a distributable package.

```bash
# Poppler must be exactly the release test-suites.toml pins ([environment.poppler]).
# macOS: Homebrew poppler at that release, held with `brew pin poppler`.
# Ubuntu: build it (dependencies: see .github/actions/setup-python-project):
# .github/scripts/install-poppler.sh ~/.local/poppler && export PATH=~/.local/poppler/bin:$PATH
uv sync --locked
source .venv/bin/activate
python scripts/dev.py doctor
python scripts/dev.py prepare-baseline
python scripts/dev.py inventory
# Names the engine model/docspec-runtime-pin.json pins, from the shared store
# <main checkout>/.cache/docspec-runtime; prints the export line. The first use of
# a new engine adds it with --binary /path/to/docspec (refused unless pinned).
python scripts/dev.py write-local-runtime \
  --limits .github/docspec-local-limits.json --out .cache/local-runtime/runtime.json
export DOCSPEC_JOB_CONFIG=$PWD/.cache/local-runtime/runtime.json
python scripts/dev.py test production-offline
python scripts/dev.py test active-experiment-regression
```

`doctor` checks Python, that the interpreter is this checkout's `.venv`, every
maintained import location, the locked PyArrow version and
the Poppler commands (`pdfinfo`, `pdftotext`, `pdftoppm`) and the `ps` command used by
the PDF memory guard. Each Poppler command's `-v` first line must name the pinned
release: the sniff parser_version hashes those lines, so another release (apt's
24.02, a `brew upgrade`) makes every stored sniff reading look stale. Import and command probes have
bounded timeouts. Missing native commands fail before pytest starts.
The `production-offline` lane also requires `DOCSPEC_JOB_CONFIG`: an explicit
local DocSpec runtime configuration with executable SHA-256, source revision,
platform, build features and a limits file, for the engine this checkout's
`model/docspec-runtime-pin.json` names; the config's own digest is not trusted.
Doctor reuses the client's runtime verifier before starting pytest, and the root
`conftest.py` repeats the checkout and engine checks for direct pytest runs. Missing or invalid setup gives one actionable
error; native checks never silently become skipped. This lane refuses remote or
credential-file configuration before loading it. It neither searches for an
executable nor starts the engine during preflight. CI must supply its approved
runtime; a missing platform artifact remains a setup gate.
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
A test lives next to the package, app, or command it checks. `tests/` keeps the
shared capture, catalog, and meeting-inventory suite, plus the fixtures those
tests read.

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

Hosted validation splits the complete offline lane into six parallel jobs.
Reproduce one with `python scripts/dev.py test production-offline --shard 1/6`.
The index starts at one; all six partitions together cover the full lane once.
Each keeps the same offline wrapper, marker, native prerequisites and failures.
An empty partition fails before pytest, and `--shard` cannot combine with `--path`.
Omit `--shard` to run the full lane. CI installs the locked Node workspace before
the Python reader tests and requires every partition before `validate` can pass.

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

## Reading version changes

The lake keys reading rows by body digest, parser, and the declared version in
`congress_api.lake.reading_versions`. The combined unreadable-decision version
also depends on the four leaf versions and the combined worker limits.
`html_metadata` has its own version and runs separately.

`doctor` and the shared CI setup compare source, locked package, tool, and
worker policy evidence with `model/reading-version-diagnostics.json`.
A warning reports the result of a fixed fixture and leaves saved rows eligible.
The import check follows static imports,
including function-local imports, and may conservatively include shared code.
Dynamic imports and externally supplied inputs need separate review.

On drift, inspect the change and run the relevant bounded reading fixtures. For
an original-backed comparison, fix the body keys and local copies in advance.
Use `compatible_proof.recompute` for the combined producer or the derived
readings pass for HTML metadata, then compare the selected rows with
`compatible_proof.prove_unchanged`.
Inspect both changed values and missing rows. An unchanged sample covers only
its chosen bodies. Record the maintainer's equivalence or version bump decision
in the change review, with the sample and any limitations. Then use
`.venv/bin/python -m congress_api.lake.reading_version_diagnostics --snapshot`
to print updated evidence for review and commit it with the decision.

For a deliberate semantic bump, update the affected declaration and the model's
leaf pin in `model/jobs/publish-model.json` when applicable. Refresh the model
specification hash and size in `model/jobs/publish.json`. Qualify compatible
rows outside an exact recompute set and reconcile the selected reading and
unreadable inputs with the release owner before publication. Keep the existing
sniff compatibility entry and predicate entries until retained-table
comparisons establish that their selected rows, refusals, and pending work
are preserved.

The historical `--old-lock` attestation reconstructs a byte-derived version.
Run it from the pre-declaration source revision that owns that proof. The
committed compatibility entries retain their evidence and selection behavior.

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
