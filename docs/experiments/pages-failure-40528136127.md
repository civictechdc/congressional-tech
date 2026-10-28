# Pages run 40528136127: selected data remains v5

The failure is the expected v6 deployment gate. No site, test, workflow or producer
code change is needed. Finish publishing the native v6 data, then rerun the Pages
build. The current built interface requires v6, while the public pointer still
selects a v5 manifest.

## Verified evidence

[Run40528136127](https://github.com/civictechdc/congressional-tech/actions/runs/40528136127)
was a push run for `3a8b9376d68215922230e447c93b2176892aa09e`. Its build job passed
published-browser staging, site dependency setup, review/static reader tests,
Astro build, and built-page smoke testing. It failed only at
`Require the built filename worker against the real selected native catalog`.
Deploy and Pages artifact upload were skipped.

The retained [failure receipt](pages-failure-40528136127/filename-worker-built.json)
records `page.evaluate: Error: Unsupported filename catalog version.` The server
log shows successful HTTP200 responses for the dashboard and built modules. The
initial curl connection refusal occurred while the background server started;
the script retried successfully. It was not the terminating error.

A bounded read-only public control check confirmed:

- Pointer: `https://congressional-data.spicygov.ai/viewer-publications/manifest.json`.
- Selected manifest: `releases/03fc4cfd93a74fdc9be16d41dc528207/manifest.json`.
- Selected manifest version: **5**.
- Catalog: `469ef1ebf6864739a2c8a4c096defcc0`.
- Manifest SHA256: `b4a41dcc26935c3b07da5d276ea52f4d29ef7cb0020c38f40c9972c2f7ef8b0a`,
  matching the pointer's recorded viewer-manifest digest.

[Diagnosis snapshot](pages-failure-40528136127/diagnosis.json) retains the selected
version and artifact error. Raw run metadata, failed logs, the1033-byte artifact,
server log, pointer and selected manifest are retained locally under
`output/pages-failure-40528136127/` in the primary checkout.

## Why the gate is correct

`apps/site/src/components/explorer/reader/filenames/catalog.ts` explicitly rejects
non-v6 manifests before creating the maintained stable catalog reader. Its
`createFilenameCatalog rejects non-v6 catalog manifests` test covers versions1,2,5.
The v5 retirement was intentional in `3089e771`; the Pages real-worker gate was
added in `2404376c`.

`.github/scripts/verify-built-filename-worker.sh` executes the built browser worker
against the actual selected public pointer. The workflow passes
`--require-native-worker true` before upload/deploy and requires the same pointer
again after deployment. `requireNativeWorker` independently refuses non-v6 data,
unexecuted/failed workers and a pointer changed since built-site verification.
This prevents deploying an interface incompatible with the selected data.

## Focused check and next action

Both existing tests passed under exact Node22.22.2 using already installed
hyparquet1.31.2 dependencies. No dependency installation or lock change was made:

```sh
/Users/mikewolfd/.nvm/versions/node/v22.22.2/bin/node --test \
  --test-name-pattern='createFilenameCatalog rejects non-v6|deployment gate requires native' \
  apps/site/src/components/explorer/reader/filenames/catalog.test.mjs \
  apps/site/scripts/verify-live-publication.test.mjs
```

The first local attempt used an escalated shell's Node26 and an incomplete primary
node_modules tree: the gate test passed, but loading catalog.ts lacked hyparquet.
The final run explicitly selected the pinned Node22 binary and reused the existing
v6-release-repair worktree's installed matching dependency tree. Those setup
failures are separate from the passing final two-test result.

Once parent confirms native v6 has been published and selected, the minimal
operational retry is:

```sh
gh run rerun 40528136127 --failed
```

That command was not executed. It reruns the failed build job, including its full
existing checks, and permits deployment only if they pass. A retry before v6
selection is expected to refuse again. No active runtime, coordinator database,
source receipt, producer implementation or remote publication was changed during
this diagnosis. This is a report-only commit for review.
