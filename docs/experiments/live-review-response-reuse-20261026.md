# Reuse raw review bytes during live publication verification

The live verifier now downloads `reviews.json` once per invocation and supplies
independent response bodies to the maintained review loader and the verifier's
raw-byte and document-identity checks. The raw snapshot belongs to that invocation
and exact review URL. The loader still parses and transforms its own rows; parsed
rows never become cached transport data. The bounded transport still controls the
network request, decoded byte limits, timeout, headers and observations.

Baseline: `7242f0419f589ffcf9e52f5f5068fb4edd5b6c44`.
Earlier fake-transport evidence is recorded in
`output/duplication-validation-20261026/workflow/report.md` and
`current-review.json` in the primary workspace. Both v5 and v6 made **two**
review requests there. The same probe against this change makes **one** per
successful invocation. Focused regression tests also assert one descriptor-sized
review body and one review observation, saving one request and one review body's
decoded bytes. This is an operation count, not a production latency measurement.

Only `apps/site/scripts/verify-live-publication.mjs` and its focused tests change
at runtime/test level. Explorer reader APIs and ordinary browsing are unchanged.
Review binding fetches and independent browser runtime checks remain separate.
Both consumers retain their length, digest, schema, placement, reference and
identity validation.

## Checks run

Node `22.22.2`; existing primary Node dependencies resolved read-only through the
previous probe's loader. No dependency install or synchronization was required.
From the isolated worktree:

```sh
/Users/mikewolfd/.nvm/versions/node/v22.22.2/bin/node \
  --experimental-loader /Users/mikewolfd/Work/congressional-tech/output/duplication-validation-20261026/workflow/dependencies-loader.mjs \
  --test apps/site/scripts/verify-live-publication.test.mjs \
  apps/site/src/components/explorer/reader/filenames/reviews.test.mjs
git diff --check
```

Before edits, the verifier suite passed **21/21**. After edits, the two focused
suites passed **38/38** (27 verifier tests and 11 reader tests). Coverage includes:

- One request in both v5 and v6, with both validators succeeding even though the
  v6 loader transforms positions and source references.
- A successful call followed by another call at the same URL with changed
  length, same-length changed bytes, or HTTP 503: each second call fetches anew
  and refuses the changed response under the original descriptor.
- Hash-matching but invalid review version, evidence link, document identity or
  status still refuses verification.
- Existing placement/withdrawal, stale native identity, binding, recovery,
  decoded gzip/CORS, declared byte budget, startup deadline and cancellation
  regression checks still pass.

The existing `review-probe.mjs` was also replayed with this worktree as `source`
and its exact checked-out commit as `sha`, using `dependencies-loader.mjs`.
Its successful cases return one review row and one review request for v5/v6;
its changed-length cases refuse after one request. Run it from the original
`workflow` output directory and choose fresh output names to preserve evidence.

No real network transport, deployed browser, full release build, publication,
push or deployment was run. Runtime browser execution remains `pending` in the
probe. Source review and focused synthetic checks establish this bounded reuse;
they do not establish production performance or release readiness.
