# Browser qualification for viewer candidates

`scripts/benchmark_viewer_browser.mjs` runs Chromium against the maintained
`createFilenameCatalog`, `loadReviews`, `loadRecoveries`, navigation, detail,
origin and bounded observation readers. Its Python helper verifies local
publication files, serves exact byte ranges, and exposes the CORS headers required
by the browser. The HTML page uses `localhost`; data uses `127.0.0.1`, so the
browser enforces cross-origin access. Inputs stay read-only and all outputs remain
under the selected benchmark output directory.

Install the isolated tooling once with:

```sh
npm install --prefix output/viewer-browser-tools --no-save --package-lock=false \
  esbuild@0.25.12 playwright@1.62.1 hyparquet@1.31.2 hyparquet-compressors@1.1.2
output/viewer-browser-tools/node_modules/.bin/playwright install chromium
```

Use `VIEWER_BENCHMARK_MODULES` to name that absolute `node_modules` directory.
Multiple directories use the operating system's path delimiter. A bundled runtime
can provide Playwright; the receipt records its actual version and Chromium
version. `--browser-executable` can select a known installed Chromium binary.
The receipt also hashes the compiled module bundle, so its exact dependency code
is identified even when a different local package source supplies it.

```sh
node scripts/benchmark_viewer_browser.mjs \
  --publication /absolute/path/to/trial/publication \
  --output /absolute/path/to/trial/browser \
  --review-data /absolute/path/to/verified/reviews.json \
  --accepted /absolute/path/to/accepted.json \
  --repeats 5
```

The default review descriptor and stable review identities come from the worktree.
Override them with `--review-descriptor` and `--review-identities` when the trial
explicitly pins different review inputs. Review bytes must match the descriptor.
Without `--accepted`, the recovery reader still verifies the catalog-derived
aliases. The harness never downloads missing review assets or source documents.

The first run selects the first, middle and last source, the source with the most
observations, and the source with the largest sum of compact observation JSON
bytes. Selection examines all published observation and reference blocks, with
bounded reads; one existing logical observation can itself exceed a block's size.
It resolves their stable source IDs through the 256 shards. Save and reuse the
emitted `cases.json` through `--cases` for every other candidate. A selected bound
review and recovered source are included when present. An empty binding still
exercises the real review loader and checks that withdrawn reviews stay unapplied.

Each repetition gets a fresh browser context. Each case gets a fresh catalog
reader, with fetch caching disabled. Detail timing includes navigation and detail
reads; initialization timing includes review and recovery loading. Result hashes
normalize only local HTTP origins and synthetic release paths, allowing exact
cross-candidate comparisons. Every case reports its individual samples and p95;
the driver must compare matching case IDs, inputs and result digests before using
the latency gate. This is a local browser-read measurement, not remote delivery
or a public-site performance claim.

Verification on macOS arm64: seven server verification/range tests pass. A real
Chromium fixture run completed two repetitions, with the real review loader
retaining 86 withdrawn reviews and applying none, and with a locally supplied
recovery mapping verified through the real recovery-link path. The first two
attempts are retained: unavailable default Chromium executable, then a wrong HTML
content type in the server (repaired). This fixture run does not qualify the full
catalog or the Linux performance gate. Evidence lives under
`output/browser-fixture/chromium-attempt-{1,2,3}/`.

A level-9 fixture subsequently completed five repetitions (60 measurements).
All twelve case result hashes matched the level-19 fixture exactly. See
`output/browser-fixture/browser-equality.json` and `level9-browser/`. The unequal
repetition counts and tiny fixture support functional equality, not a meaningful
full-catalog latency comparison.
