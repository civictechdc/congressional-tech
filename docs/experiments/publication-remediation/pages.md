# Reproducible Pages build

Pages uses the shared `setup-python-project` action (`uv sync --locked`, Python
3.12.13), Node 22.22.2 from `.node-version`, and npm 11.19.1 from the site's
`packageManager`. The site has its own committed lockfile. Use
`npm ci --workspaces=false` inside `apps/site`; the root workspace has unrelated
applications and deliberately does not supply this deployment lock.

The job verifies the selected Explorer publication before copying or migrating
it, runs the maintained Explorer and filename-reader checks, verifies the pinned
review evidence during `npm run build`, then exercises the emitted filename page
under `/congressional-tech/`. The smoke test runs the actual bundled bootstrap
and UI with a deterministic worker; separate worker tests cover catalog reads.
It makes no network requests and checks the worker and review URLs retain the
Pages prefix. Node's VM module API requires the declared experimental flag.

The Explorer publication remains a prerequisite of this shared site. Removing
that prerequisite needs a product decision about separating the pages, rather
than bypassing verification when data is absent.

Verification on 2026-10-18:

- Two clean frozen npm installs produced the same lock bytes, SHA-256
  `ef5529088d88e2b34298a2136f801cecfff88e2f39e5261202c92b4cb740ef27`.
- Removing the locked jsdom entry caused `npm ci --offline` to refuse the stale
  lock without rewriting it.
- The locked Python environment installed successfully; six size/workflow checks
  passed. The original maintained JavaScript suite passed 113 tests.
- The locally retained review archive passed descriptor and evidence verification.
  `npm run build` produced 29 pages; the built bootstrap smoke passed, including
  the first merged worker-lifecycle changes.
- The local `pipeline-data` checkout has no Explorer `CURRENT.json`; its verifier
  correctly refused it. This is not evidence of a complete production Pages
  deployment. No remote workflow, publication or source collection was started.

The size checker now counts and sums files in one traversal, prunes `.git`
directories, and retains at most 20 diagnostic paths. Five boundary tests passed.
This bounds checker state; no timing improvement is claimed for this small change.

Final integration found that the locked jsdom 30.1.2 dependency requires Node
22.22.2 or newer in the Node 22 line. The pin now matches that supported runtime;
CI uses `npm ci --engine-strict` so future incompatible lock changes fail early.
Earlier successful tests under Node 26 or 22.21.1 do not establish this supported
runtime check; the final browser receipt records the explicit supported run.
