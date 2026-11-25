---
id: ct-69ly
status: closed
deps: []
links: [ct-2cig, ct-bwyj]
created: 2026-11-18T22:04:57Z
type: task
priority: 3
assignee: mikewolfd
tags: [docmeta, work-addr, gold]
---
# DocMeta gold leaves work_addr blank where the text prints it, so precision against gold misleads

Gold often has no work_addr for a person whose office is printed under their name. Measured 2026-11-17 with R8 added: of 16 distinct addresses R8 added on val48 and valid_sweep, 12 are on people gold leaves blank, and all 16 are right against the text. Precision against gold therefore fell (valid_sweep 73.9 to 60.0, val48 66.7 to 56.2) while recall rose (val48 54.5 to 81.8, valid_sweep 60.7 to 64.3) and agreement stayed 100 percent. On the 2,894 training documents with gold people, R8 attaches 178 addresses: 108 agree with gold, 7 differ (4 of those are gold city-only), 63 are on gold-blank people (11 of 12 sampled were right). The copied reader finds 277 of 309 gold street addresses complete; the 32 misses are not classified.

## Design

Owner decision needed before any gold edit (labels feed training): either fill gold work_addr from the text where R8's block rule finds it and a reader confirms a sample, or leave gold alone and report only recall and agreement for this field, as eval_blind.py already does outside the headline. Do not change the training loss on the precision number. Evidence: fast-gemma4 artifacts/eval/v64_ep1_r8_before.json and v64_ep1_r8_after.json, artifacts/work-addr-20261117/, and docs/measurements/docmeta-v64-lora-20261117.md (Work addresses section).

## Acceptance Criteria

The owner's choice is recorded here. If gold is filled: the count of filled people, a read sample, and work_addr precision on val48 and valid_sweep re-measured with the same model. The 32 missed gold street addresses are classified by cause.


## Notes

**2026-11-22T18:40:56Z**

2026-11-22 ticket backlog audit: Closing under Option B — eval_blind.py already excludes work_addr from headline_mean and reports recall and agreement separately, so gold does not need backfilling purely for a precision metric.
