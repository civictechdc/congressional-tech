# Viewer publication commands

These commands publish and inspect the **filename viewer**: the public site that looks up congressional documents by filename. The built files live in Cloudflare R2 under `viewer-publications/`. They are derived from the raw archive. These commands do not capture new documents and do not rewrite archive bodies or `indexes/`.

The day-to-day publisher is `scripts/publication/publish-viewer-r2.py`. It imports `publication_cli.py` from this folder. Run it from the repository root after `uv sync --locked`.

## `publication_cli.py`

One interface for a viewer publish attempt. Run these commands through `scripts/publication/publish-viewer-r2.py`.

| Command | What it does |
| --- | --- |
| `prepare` | Builds a local attempt directory and writes a report. It does not upload. |
| `verify-prepared` | Checks that a prepared directory still matches the attempt you intend to publish. |
| `publish` | Uploads that prepared attempt. Resume requires the original attempt identity, so a second process cannot publish a different attempt under the same name. |
| `describe-attempt` | Reads an existing attempt and prints what it was. It does not change remote objects. |

A failed command replaces a stale success report before it opens a client that could write.

New preparation requires an explicitly adopted native catalog and a configured
DocSpec runtime. Pass `--native-config /absolute/path/runtime.json` to `prepare`
(or set `DOCSPEC_CONFIG`). The configuration names the approved executable,
workspace, remote catalog and finite resource limits; credentials stay in the
private file referenced by that configuration. Preparation records the executable
and nonsecret configuration hashes and refuses if those files change while it
builds the output. Uploading an accepted artifact does not need DocSpec.

The hosted workflow installs one approved private Linux AMD64 runtime through
`.github/scripts/setup-native-runtime.py` before new preparation. The repository
variable `DOCSPEC_RUNTIME_ARTIFACT` supplies JSON with `version: 1`,
`platform: "linux-amd64"`, the exact 40-character `source_revision`, private R2
`bucket`, immutable `key`, positive `bytes`, complete `sha256`, required
`build_features` (defaulting to `["remote"]`) and `required_capabilities`
(`["request-deadline", "owned-stdin-eof"]`). The key must be
`runtime/docspec/<source_revision>/linux-amd64/<sha256>/docspec`. Both setup and
`.github/scripts/check-native-runtime.py` bind `source_revision`, `platform`,
`build_features`, `binary_sha256` and `required_capabilities` into `runtime.json`
and fail fast before any source or catalog access if the binary is missing,
non-executable, wrong digest, wrong platform, or missing required features or
loopback protocol 1 capabilities.

The `DOCSPEC_ENGINE_CREDENTIALS` secret is a JSON object containing
`DOCSPEC_CATALOG_TOKEN`, `DOCSPEC_S3_ACCESS_KEY_ID` and
`DOCSPEC_S3_SECRET_ACCESS_KEY`. Its S3 key pair reads the private runtime object
and supplies the native engine; no additional artifact credential is needed. The
checked-in `.github/docspec-remote.json` retains the qualified catalog URI,
namespace generation and owned prefix.

Setup requires a fresh `$RUNNER_TEMP/docspec-runtime` directory, verifies exact
artifact size and SHA-256 before marking it executable, writes private runtime
and credential files with mode 0600, and invokes the maintained native preflight
check without starting DocSpec. It exports only `DOCSPEC_RUNTIME_CONFIG` and
`DOCSPEC_BINARY_SHA256` for later steps. Neither binary nor credentials enter
workflow artifacts. Missing distribution inputs or stale/partial installations
refuse. Read-only no-op checks, raw-source code validation and restoring accepted
artifacts skip installation. The native source and binary contents remain
private; selecting a descriptor does not publish them.

For local checks, the helper accepts explicit `--artifact-descriptor`,
`--credentials-file`, `--remote`, `--directory` and `--output` paths; the credential
input must already have private permissions. Installing does not execute the
native engine, create its workspace or mutate the remote catalog. The artifact
bucket and descriptor must be provisioned separately before hosted execution.

## Explicit renderer upgrades

A normal update refuses changed rendering rules. After qualifying new rules,
prepare a separate local upgrade from the current native catalog and prior v6
viewer release:

```bash
.venv/bin/python scripts/publication/publish-viewer-r2.py prepare \
  --directory output/renderer-upgrade --run-id upgrade-20261020 --run-attempt 1 \
  --native-config /absolute/path/runtime.json --renderer-upgrade
```

If preparation stops, repeat that command with `--resume-preparation`, the same
directory, run identity, code, configuration, source selection and prior release.
The existing preparation continuation checks those inputs. Its private sibling
`publication.renderer-upgrade/stages.sqlite` retains completed bounded rendering
tasks. Restart verifies every completed asset hash before reusing those tasks.
Missing or changed assets refuse; they are not accepted as completed work.

An upgrade intentionally renders all selected chunks under the new rules. It
keeps the exact native catalog pins, creates no replacement native datasets, and
makes no publication write during preparation. The selected viewer stays in place
until the ordinary accepted-artifact upload and conditional selection succeed.
Completed preparation retries reuse the accepted output. The staging database
is retained locally for diagnosis and restart; it is not a viewer upload asset.
Its disk use grows with selected metadata, while native reads and Arrow memory
remain bounded by the existing chunk limits. This does not make total process
memory constant: the accepted file inventory still grows with new assets.

The guarded local recovery dispatcher exposes the same `--renderer-upgrade`
option; its existing `--resume` continues that exact retained operation. It keeps
its original catalog, mapping and publication guards. Changing a source/grouping
rule requires the separate catalog upgrade path, not this rendering option.

## Resume through GitHub Actions

Run `describe-attempt` with the original run ID and save its JSON report. If that
run has several accepted artifacts, select its exact artifact ID. Paste the
report into the publication workflow's single `resume_descriptor` input.

The workflow checks the record before installing the workspace, then checks out
its exact original revision and restores its exact artifact. The CLI rechecks
the same record before opening a publication client. The input is limited to
16 KiB; duplicate fields, conflicting identities and another repository fail
before selection. Ordinary scheduled runs need no resume input.

## `pipeline_status.py`

Reads the status of a capture or publish **without changing it**. Give it a GitHub Actions run ID. It asks GitHub for that run and reads the public heartbeat object (`status/raw-source-sync.json`). It attributes heartbeat numbers to the run only when the run, attempt, and git revision match. It does not resume work, write status, or estimate a finish time.

```bash
.venv/bin/python scripts/publication/pipeline_status.py --run RUN_ID
.venv/bin/python scripts/publication/pipeline_status.py --run RUN_ID --json
```

Offline, pass saved GitHub and heartbeat JSON with `--github-json` and `--progress`. Details and the extra flags are in [`docs/pipeline-status.md`](../../docs/pipeline-status.md).

## What this folder does not contain

The guarded upload, the resume journal, and the read-back checks live in [`packages/viewer_publication`](../../packages/viewer_publication/README.md). The cheap "already published?" check that runs before dependencies are installed is `scripts/publication_preflight.py`.
