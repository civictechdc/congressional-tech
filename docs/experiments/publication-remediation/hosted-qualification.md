# Publication qualification

The reviewed implementation is merged at `744edd6078cbe56a86b997a40badfc9d197b0e85`
([PR 115](https://github.com/civictechdc/congressional-tech/pull/115)).
Full CI and Pages deployment passed. Hosted catalog preparation and the ordinary
scheduled unchanged-run observation remain pending; tickets `ct-hnxb`, `ct-x7vx`
and parent `ct-d8z3` remain open until their evidence passes.

## Verified results

- [Final branch CI](https://github.com/civictechdc/congressional-tech/actions/runs/39176588962)
  passed at reviewed head `0eedd6065ba2e661c2b51ca7c146c7acfabdf6da`.
- [Pages build and deployment](https://github.com/civictechdc/congressional-tech/actions/runs/39176607496)
  passed at merged head `744edd6`. The deployed browser still requires the final
  live review/recovery check after the new catalog is selected.
- The [complete local preparation](current-catalog-qualification-20261018.md)
  preserved all 1,683,430 filename rows, 1,241,157 document rows and 7,246,240
  observation occurrences. All 270 output files passed SHA256/size checks.
  Source files stayed unchanged. This macOS run took 3,155.71 seconds and reached
  7,310,491,648 bytes of RSS under its local 7 GiB ceiling; it does not establish
  hosted Linux memory use or an overall speed improvement.
- The [controlled browser comparison](browser-metadata-reuse.md) reduced repeated
  metadata parses from 45 to one per technical read. Cold/warm reads changed from
  19.09/17.44 seconds to 0.596/0.459 seconds with identical returned values.
  Source-URL search completed in 27.52 seconds instead of reaching the old
  120-second deadline. Cache limits stayed unchanged.

The full local output is 1,290,775,040 bytes. Exact document-source copying and
bounded filename staging add 210,386,731 bytes to those two files compared with
the earlier selected release. The other eleven declared payload hashes and sizes
match. This is a memory and correctness tradeoff, not an aggregate payload saving.

## Hosted publication and live checks

[Normal publisher run 39176607378](https://github.com/civictechdc/congressional-tech/actions/runs/39176607378)
is preparing the catalog. No manual retry, dispatch or production resource change
was requested. The original rebuild `39137101154` and its category comparison
were already verified separately; they are not repeated here.

After successful selection, the maintained publication, recovery and review
loaders will verify catalog `469ef1ebf6864739a2c8a4c096defcc0`, publisher version 10,
`house-naming` 3.2.7, row counts, review-binding digest and review pin. The reviewed
local harness also requires every explicit review placement, 86 bound and zero
withdrawn reviews, 81 applied groups plus five annotations in the actual Node
loader, and 81 applied groups in a fresh browser running the deployed worker.
Its eight offline tests include an all-withdrawn negative case. This harness is
ready but has not yet run against the new selection.

## Ordinary unchanged-run cost

[Scheduled run 39179688133](https://github.com/civictechdc/congressional-tech/actions/runs/39179688133)
is naturally queued behind the publisher at the same code revision. Closure
requires its actual unchanged preflight, zero table reads/writes, skipped full
workspace setup and preparation, and retained job-time/received-byte receipts.

The two retained older scheduled jobs took 76 and 69 seconds on `ubuntu-24.04`.
Both reported `recovery_updated`, reused catalog payloads and selected the same
recovery bytes; neither was a true no-op. Their catalog was the older `90001c4c…`
and their host download counters are unavailable. The new measurement must retain
these differences; no download percentage can be calculated from missing data.
Its job-step timer excludes runner allocation, post-job cleanup and artifact
upload, and its host received-byte counter includes managed background traffic.

The earlier [matched small-fixture comparison](combined-verification.md) measured
unchanged polls 52.6% faster and explicit resume 38.4% faster, while fresh
publication became 7.5% slower. Those figures describe separate operations and
cannot be added or applied to this complete catalog. Overall benefit depends on
how often each operation occurs.

## Evidence and closure

Raw logs, failed attempts and receipts remain in the primary checkout under
`output/publication-remediation-20261018/rollout/`; the live harness and its reviews
are under `output/playwright/publication-rollout/`. Final hosted/live receipts and
ticket closure will be added after their checks finish. Historical experiment
reports retain the claims and limits of their recorded revisions; this report
will record the final deployment outcome without rewriting those experiments.
