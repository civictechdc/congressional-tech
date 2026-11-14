---
id: ct-5cdu
status: open
deps: []
links: [ct-4jms, ct-z4w5, ct-6v77]
created: 2026-11-14T15:56:14Z
type: bug
priority: 2
assignee: mikewolfd
tags: [source_quality, body_text, followup]
---
# Bound reviewed capture planning to relevant URL history

After the empty-journal workaround, the seven-target refetch planner exhausted the 512 MiB fair-pool share while joining the full 1,204,646-row published URL state. A maintained native URL-key prefilter retained six matching history rows, and the same planner then produced four reviewed targets in 1.7 seconds at 0.243 GiB peak RSS without raising limits.

## Design

Add a bounded reviewed-target history path inside the maintained planner, preserving canonical URL keys, candidate repairs, alias states, due/retained/scope decisions and every named cutoff. Do not use a target-only cache for an unconstrained whole-release plan. Evidence is repairs/source-refetch-20261114/scheduler-followup/{scoped-history.json,plan-result.json,post-refetch-accounting/cutoffs.json}.

## Acceptance Criteria

Compare full and scoped planning on overlapping aliases, different-key repair candidates, retained and failed states, requested seed context and missing history. Preserve all requested/candidate histories needed by address repairs. Demonstrate the seven-target real release under the same memory limits; retain measured resource evidence and no-request metadata-only proof.

