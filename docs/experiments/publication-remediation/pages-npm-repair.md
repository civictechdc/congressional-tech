# Preserve the running npm during Pages setup

Pages run `39169129664` failed before dependency installation. Node 22.22.2
bundles npm 10.9.7. Its Arborist rebuild code lazily loads `promise-retry` while
creating executable links. Installing npm 11.19.1 over that running npm tree
removes the old dependency before the old process finishes; npm 11.19.1 uses
`@gar/promise-retry` instead. The same `MODULE_NOT_FOUND: promise-retry` failure
was reproduced in an isolated copy of npm 10.9.7. The user's runtime was preserved.

The shared `setup-node-project` composite action now reads the exact Node version
from `.node-version` and exact npm version from the site's `packageManager`.
It installs npm into a newly created, owned `RUNNER_TEMP/site-npm.*` prefix,
verifies that executable's version, then adds its `bin` to `GITHUB_PATH` for
subsequent steps. The bootstrap npm tree remains intact. Failed installation,
unpinned declarations or mismatched versions never activate the new runtime.

Both Pages and PR validation use this one setup action and the same frozen
`npm ci --workspaces=false --engine-strict --no-audit --no-fund` installation.
Pages still runs its reader tests, build, built-page smoke test and size gate.
PR validation retains its existing checks. Their path filters cover changes to
the shared action, and PR validation now also covers `.node-version`. Dependency
versions, package manifests and lockfiles are unchanged. This removes the two
different Node/dependency setup routes and prevents the confirmed self-replacement
failure.

Local verification used the existing Node 22.22.2/npm 10.9.7 bootstrap and executed
the actual action shell. Installing npm 11.19.1 into the fresh prefix succeeded;
the activated Node/npm versions matched exactly, and frozen site installation
succeeded. A separate manifest copy pinned an older `@astrojs/check`; `npm ci`
refused it with EUSAGE, preserved both input files and created no dependency tree.
Before/after hashes of the bootstrap's package/Arborist files and the site's
manifest/lock match. The original npm still reports 10.9.7.

The focused workflow/action matrix passed **48 Python tests**, and the maintained
reader suite passed **152 Node tests** with zero skips. The first reader attempt
omitted the Python environment supplied by the existing CI setup; its missing
PyArrow/pytest prerequisite failures are retained. Repeating with the existing project Python venv
and this worktree's source paths passed all reader tests. No application fix was
needed for that local environment error.

`evidence/pages-npm-repair.json` records the runtime and preserved hashes.
Detailed command output and reproduction receipts remain under primary
`output/publication-remediation-20261018/rollout/pages-npm-repair/`.
This is local macOS evidence; the next hosted Linux setup/build remains pending.
No workflow retry/dispatch, push, deployment or active viewer-publication action
was performed.
