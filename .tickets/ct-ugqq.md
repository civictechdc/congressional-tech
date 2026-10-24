---
id: ct-ugqq
status: closed
deps: [ct-egpe]
links: [ct-oxg6, ct-snzi, ct-tw3r]
created: 2026-10-20T22:15:53Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, application-adoption, efficiency]
---
# Distribute the qualified DocSpec runtime to capture and publication callers

Existing setup-native-runtime.py installs a revision/digest-bound Linux artifact, but a consolidated source checkout does not prove that local and hosted callers execute that runtime. Wire the qualified release into the existing application distribution path.

## Acceptance Criteria

- Bind source commit, platform, build features, binary hash and required capabilities in the maintained runtime descriptor; use immutable artifacts and private credentials.
- Exercise installer and capture/publisher invocations locally with a Linux-compatible runtime or equivalent supported local harness; reject stale, missing, wrong-platform and wrong-digest artifacts before source access.
- Preserve namespace/workspace and retained operation identities during upgrade; document old/new runtime compatibility and an explicit recovery route. No silent namespace reset or producer cleanup.
- Update maintained dependency/setup docs and record installed versus deployed status separately. This ticket does not require CI dispatch, source acquisition or a production migration retry.


## Notes

**2026-10-20T22:15:54Z**

2026-10-20 adoption review: .github/scripts/setup-native-runtime.py. Evidence: output/docspec-reuse-20261020/adoption-review/application-gaps.md. Plan assumes required upstream upgrades become available; verify actual capabilities before use. This ticket changes congressional-tech only; local tests and exact-value preservation are required, no CI dispatch.

## Audit 2026-10-24

- Verdict: PARTIAL (batch mi03b).
- Grades: proposal 87 → 91, work 67 → 62.
- Problem: `setup`/`check` compare the artifact only with its own descriptor (`artifact['source_revision']`, `:126`), never with `QUALIFIED_DOCSPEC_RUNTIME`.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/mi03b/mi03b-verdicts.md:32
- Status: Closed as superseded by the simplification plan (P2, done in `54a68ac7`, ct-snzi): hosted setup now refuses any engine revision other than `QUALIFIED_DOCSPEC_RUNTIME`. The README notes in AC3/AC4 are not carried.
- See docs/reviews/2026-10-24-ticket-audit/README.md
