---
id: ct-3lz2
status: closed
deps: []
links: []
created: 2026-10-20T16:51:12Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-a1aa
tags: [news-lake, identity, contract]
---
# Fix identity decision graph cycle detection and DAG root resolution

identity/decisions.py:31-75 (_Graph.merge) claims to track literal left->right arrows and reject any same_as that closes a directed cycle, but line 74 writes self.edges[root_left] = root_right (Union-Find root attachment). This causes both false negatives (missed cycles: d1=same_as(B,C), d2=same_as(A,B), d3=same_as(B,A) shortcuts A->C so reaches(A,B) is False and follow(B)==follow(A)==C, accepting the cycle A<->B as a benign confirmation) and false positives (spurious cycle errors on valid DAGs: d1=same_as(A,B), d2=same_as(A,C) mutates edges[B]=C, causing d3=same_as(C,B) to fail with decision_cycle on the acyclic DAG {A->B, A->C, C->B}). Furthermore, calling apply_decisions directly on a reflexive decision same_as(A,A) raises decision_cycle instead of reflexive_identity_decision.

## Design

Separate the literal directed decision graph (left -> right edges as recorded by active same_as decisions) from equivalence-class root resolution, or maintain literal adjacency lists for cycle reachability while resolving roots deterministically when a node or equivalence class has multiple consistent outgoing paths. Reject reflexive same_as/different_from decisions (left_id == right_id) with ContractError('reflexive_identity_decision') inside apply_decisions before cycle checks.

## Acceptance Criteria

- d1=same_as(B,C), d2=same_as(A,B), d3=same_as(B,A) raises ContractError('decision_cycle') on d3.
- d1=same_as(A,B), d2=same_as(A,C), d3=same_as(C,B) succeeds as a valid DAG with all three entities resolving to root B.
- Reflexive decisions passed directly to apply_decisions raise ContractError('reflexive_identity_decision').
- All existing retraction, contradiction, and authoritative-ID conflict tests continue to pass.


## Notes

**2026-10-20T17:18:34Z**

Implemented literal directed decision graph + separate Union-Find equivalence forest. Cycles, confirmations, reflexivity, retractions, and multi-branch DAG roots covered by tests. test_identity.py: 27 passed.

**2026-10-20T17:30:45Z**

Separated literal directed same_as arrows from the Union-Find equivalence forest; real DFS cycle checks; reflexive decisions rejected; multi-branch DAG roots resolve deterministically. Identity tests: 27 passed.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch kl2a1aa).
- Grades: proposal 94 → 94, work 87 → 87.
- Problem: Scaling: every cross-class merge invalidates `_roots` (decisions.py:126, 130).
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/kl2a1aa/kl2a1aa-verdicts.md:52
- Area owner: WS8 (ct-d8cf); not a named step.
- See docs/reviews/2026-10-24-ticket-audit/README.md
