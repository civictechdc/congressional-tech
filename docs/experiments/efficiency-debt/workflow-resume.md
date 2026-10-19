# One original-attempt record for workflow recovery

`ct-h73z` replaces five manually copied workflow fields with the JSON record
already produced by `describe-attempt`. A standard-library bootstrap validates
the record before workspace setup or selection of the original revision. The
workflow then restores that record's exact artifact and invokes the original
CLI with explicit resume authority. Both entry points use one maintained
validator. Publication inventory, artifact custody and readback checks remain.

The admission limit is 16 KiB. Duplicate JSON fields, malformed identities,
conflicting run/attempt names and a different repository fail before checkout
selection. Multiple artifact IDs cannot enter the descriptor; existing
read-only discovery still requires an explicit choice when several match.
The retained descriptor lives outside the checkout, so selecting the original
revision cannot erase it. Original attempts can use either test-file layout;
both paths resolve inside their selected checkout.

The scheduled unchanged route still skips full workspace setup, publication
tests, preparation and publication. Explicit recovery adds one checkout to
select the original revision after validation. This is a deliberate correctness
cost, not a speed improvement.

## Local evidence

Baseline: `3757f55ed33ea390895c20a2007cb08eb39ce519`.

- Workflow input count: **5 to 1**.
- Five interleaved local admission subprocess trials on the same valid record:
  median **12.15 ms before**, **19.73 ms after**. The earlier check only verified
  that all five fields were present; the new check validates their relationships,
  byte limit and repository. These measurements are not hosted-job timings.
- **117 focused tests passed**, including isolated Python without site packages,
  rejected input without selection output, retained-file protection, real shell
  test-path selection for both layouts, release identity inclusion, existing
  artifact custody checks and explicit CLI conflict checks. Independent review
  found that JSON re-encoding could expand a valid multibyte record beyond
  16 KiB. The bootstrap now retains the exact admitted UTF-8 bytes; both a
  multibyte record and a record exactly at the byte limit pass the round trip.
  The 41-test focused repair rerun passed.

The practical gain is fewer manual transcription steps and one shared validator.
No publication, source acquisition or workflow dispatch was used for this check.
Raw receipts and test logs are retained under
`output/efficiency-debt-20261019/workflow/` in the primary checkout.
