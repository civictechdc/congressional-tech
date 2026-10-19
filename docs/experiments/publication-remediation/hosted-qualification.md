# Publication qualification

The reviewed implementation is merged at `744edd6078cbe56a86b997a40badfc9d197b0e85`
([PR 115](https://github.com/civictechdc/congressional-tech/pull/115)).
Full CI, Pages deployment, hosted publication, maintained live loaders and a fresh
deployed browser passed. The ordinary scheduled unchanged run also passed. These
results satisfy the remaining qualification for `ct-hnxb`, `ct-x7vx` and parent
`ct-d8z3`; this evidence change records their closure.

## Verified results

- [Final branch CI](https://github.com/civictechdc/congressional-tech/actions/runs/39176588962)
  passed at reviewed head `0eedd6065ba2e661c2b51ca7c146c7acfabdf6da`.
- [Pages build and deployment](https://github.com/civictechdc/congressional-tech/actions/runs/39176607496)
  passed at merged head `744edd6`. The final live review/recovery check also passed
  in a fresh Chromium browser executing the deployed Pages bootstrap and worker.
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
completed successfully at `744edd6` on 2026-10-19 at 02:09:54 UTC. Preparation,
accepted-artifact storage, complete inventory verification and publication all
passed. The hosted verifier accepted 271 inventory files: 269 publication
payloads, the manifest and a recovery-preparation file. The publication receipt
counts only those 269 payloads (1,290,761,110 bytes); the local 270-file total also
includes its own manifest. These counts describe different file sets.
The job took 9,732 seconds (2 h 42 m 12 s): preparation took 8,924 seconds
and publication took 657 seconds. The cost receipt measured 9,722.87 seconds and
5,765,616,175 host received bytes within its narrower observation interval.
No matched full-catalog hosted baseline or hosted peak-RSS measurement is
available, so this establishes successful execution, not a speed or memory gain.

The selected release is `4502c555d3c848c6a64c1a0376b2ed61`, with catalog
`469ef1ebf6864739a2c8a4c096defcc0`, publisher version 10 and `house-naming` 3.2.7.
It retains 1,683,430 filename rows and 1,241,157 document-table rows. The source
selector SHA256 is
`94a327cf82a32dd119bca84395578569cc3b9261fb5b3d7f911c9838a508d5d9`.

The independently reviewed live harness ran once at 02:20:31 UTC. It used the
maintained publication, recovery and `loadReviews` code, then a fresh deployed
browser. All eleven checks passed: 86 explicit bound reviews, zero withdrawn,
81 applied groups plus five annotations in the Node loader, and 81 applied groups
in the browser. No reviews were reinstated or withdrawn. The review-binding file
is 5,632 bytes with SHA256
`f70fbd4b64eded6cf143fca33fdf15663a271262388263ba1b65cc7e99f6551e`;
the review pin is
`fc5d361e4f2c01db8e8be90267f18cf072cc6db02bc1cd57ef5621b8aac1354c`.
The live manifest SHA256 is
`761294c412f4439e158c1857e449bad0031e55ff0459b39a79e6282d47734aa3`.
This live check covers bootstrap, review and recovery loading; the separate local
browser comparison covers technical reads and source-URL search.

Diagnostic artifact `12159305821` is 3,210,123 bytes; its saved ZIP hash matches
GitHub's SHA256
`a691e9ada38ba686a6c08f487d887beeafe9ee5d5dd851d7838f0ad22e44623a`.
Bounded inspection extracted seven small receipts. It retained but did not
decompress the 12,388,821-byte continuation or 9,684,627-byte preparation member,
both above the existing 8 MiB member limit. Preparation identity and complete
inventory acceptance come from the successful hosted verifier, its retained log
and the small result receipts. The 1,325,335,704-byte accepted preparation archive
was not downloaded. This is hosted verification evidence, not an independent
local rehash of every hosted payload.

No manual retry, dispatch or production resource change occurred. The original
rebuild `39137101154` and its category comparison were verified separately and
were not repeated.

## Ordinary unchanged-run cost

[Scheduled run 39179688133](https://github.com/civictechdc/congressional-tech/actions/runs/39179688133)
ran naturally after the publisher at the same revision and passed. Its preflight
reported `unchanged`, zero table reads, zero publication writes and
`write_authority: false`. Full workspace setup, tests, preparation, accepted
artifact handling, inventory verification and publication were all skipped.

| Observed quantity | Result |
| --- | ---: |
| Entire scheduled job | 20.00 s |
| First cost step through cost receipt | 14.34 s |
| Read-only preflight | 4.54 s |
| Preflight requests | 10 |
| Preflight response bytes | 44,422,480 |
| Host received bytes during observation | 350,881,760 |

The no-op still downloads Python, checkout and control/readback data. The cost
step timer excludes runner allocation, post-job cleanup and artifact upload;
the host received-byte counter includes managed background traffic. The saved
926-byte diagnostic ZIP matches GitHub's digest and run/revision metadata.
The approved offline validator accepted the real receipts without rerunning its
synthetic examples or the expensive local qualification.

The two retained older scheduled jobs took 76 and 69 seconds on `ubuntu-24.04`.
Both reported `recovery_updated`, reused catalog payloads and selected the same
recovery bytes; neither was a true no-op. Their catalog was the older `90001c4c…`
and their host download counters are unavailable. The new run also used
`ubuntu-24.04`, but its work and setup path differ. These observations do not
support a matched savings percentage or a historical download comparison.

The earlier [matched small-fixture comparison](combined-verification.md) measured
unchanged polls 52.6% faster and explicit resume 38.4% faster, while fresh
publication became 7.5% slower. Those figures describe separate operations and
cannot be added or applied to this complete catalog. Overall benefit depends on
how often each operation occurs.

## Evidence and closure

Raw logs, failed attempts and receipts remain in the primary checkout under
`output/publication-remediation-20261018/rollout/`; the live harness and its reviews
are under `output/playwright/publication-rollout/`. The [evidence index](evidence/hosted-qualification.json) pins the completed
hosted, live and scheduled receipts and their measurement limits. Historical
experiment reports retain the claims and limits of their recorded revisions.
The final merge and cleanup receipt is saved locally after this evidence PR merges.
