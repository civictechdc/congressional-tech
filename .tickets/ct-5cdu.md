---
id: ct-5cdu
status: closed
deps: []
links: [ct-4jms, ct-z4w5, ct-6v77]
created: 2026-11-14T15:56:14Z
type: bug
priority: 2
assignee: mikewolfd
tags: [source_quality, body_text, followup]
---
# Bound reviewed capture planning to relevant URL history

PR #170 merged at e6a91fdb2338db13216bba6aea2567b182a6ac22 after both CI workflows passed. Reviewed-only planning separates request roots from related history while preserving alias, cooldown, attempted and retained-state behavior. The seven-target release replay and independent A/B/C native probe pass. Full URL-state metadata preparation remains explicit.

## Design

Add a bounded reviewed-target history path inside the maintained planner, preserving canonical URL keys, candidate repairs, alias states, due/retained/scope decisions and every named cutoff. Do not use a target-only cache for an unconstrained whole-release plan. Evidence is repairs/source-refetch-20261114/scheduler-followup/{scoped-history.json,plan-result.json,post-refetch-accounting/cutoffs.json}.

## Acceptance Criteria

Compare full and scoped planning on overlapping aliases, different-key repair candidates, retained and failed states, requested seed context and missing history. Preserve all requested/candidate histories needed by address repairs. Demonstrate the seven-target real release under the same memory limits; retain measured resource evidence and no-request metadata-only proof.


## Notes

**2026-11-14T17:16:28Z**

Final scheduler source c82d0e57 is integrated byte-identically at 4189d523. Root independently reran the A/B/C native probe: full mode keeps all three logical rows, reviewed mode queues A alone. The exact seven-target replay preserved four queue rows and seven cutoff records over the full 1,204,646-row release metadata at 1.539 GiB RSS, without target-only caches or higher limits. Root integration probe used 0.25 GiB RSS. Eight-round history expansion refuses rather than silently truncating. Metadata preparation still reads the full state; later planning state is bounded. Proof: source-refetch-20261114/scheduler-followup/maintained-planner-fix/root-integration-review/review.md.

**2026-11-14T18:47:48Z**

Closed at merged PR #170. The real 1,204,646-row release replay preserved four requests and seven cutoff records at 1.539 GiB RSS. The native A/B/C control keeps three logical rows in full mode and queues only A in reviewed mode. This bounds later planning state; it does not claim to skip the initial full metadata read.
