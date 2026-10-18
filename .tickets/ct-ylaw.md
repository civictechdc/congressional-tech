---
id: ct-ylaw
status: closed
deps: []
links: [ct-o24q, ct-zkzt, ct-lu4i, ct-fw0m, ct-4r1c, ct-jl1m, ct-atjy, ct-1mbc, ct-m59w]
created: 2026-10-18T19:26:50Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Consolidate supported publication commands

The cloud attempt controller and local recovery dispatcher duplicate source preparation, continuation-aware clients and progress state. publisher.run() also retains migration and acceptance branches without current production callers.

Source: scripts/dispatch_corpus_recovery_publication.py:94-294; apps/site/scripts/publish-viewer-r2.py:223,368,433; scripts/viewer_publication_attempt.py:153.

## Acceptance Criteria

Document supported operator and library routes, then use one accepted-preparation and conditional-write API. Preserve local recovery admission, original conditions, retained evidence and restart behavior. Remove obsolete migration-only branches and duplicated adapters after caller checks. Show reduced code/state paths and unchanged failure assertions.

<!-- grade-followup:start -->
## Grade review follow-up

Inventory selected_filename_path migration, test-only verify_coverage, dynamic load/private rebuild defaults, nested Store/ContinuedClient phases and mapping receipt ownership. Keep SDK retry policy explicit.

- Use one maintained entry point and state owner; preserve local body admission, original write conditions and no-retry mutation clients. Distinguish candidate, accepted, selected and publicly verified states. Remove unsupported routes only after caller checks.

Supported controller/API consolidation plus read identity type, guard/client capabilities and early output feasibility checks.

- Document retained operator/library routes before removing accept_recoveries/bootstrap/version-2/archive branches. Use named protected identities and explicit check/shared_commit and conditional-write capabilities; wrong adapters and oversized single-PUT outputs fail before any publication write (and before artifact acceptance on preparation). Retain one SDK mutation attempt, original conditions, immutable-first selection, local dispatcher admission and fail-before-write acceptance tests.

[Function scope and checks: 35 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:640). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:44:14Z**

Consolidated cloud/local original-condition replay into ContinuedPublicationClient and shared conditional upload core; local dispatcher preserves admission/lock/checkpoints, original first-publication conditions across own selector advance, and accepted snapshot timestamp. Public caller-owned catalog workspace normalizes builder inputs. Removed test-only coverage wrapper and unused accept_recoveries/Pages bootstrap/archive/no-prepared run routes after caller inventory; check_selected_publication read-only. Named protected identity, explicit guard/client/retry checks, plain SDK conditional single-PUT+independent proof, oversized output refusal before artifact acceptance.132tests+7subtests expanded matrix, final38tests+5subtests,6Node verifier tests passed/enrolled CI. Product source1809->1777lines, function count unchanged; no unmeasured speed claim.
