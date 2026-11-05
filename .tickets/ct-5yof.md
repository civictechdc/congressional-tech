---
id: ct-5yof
status: closed
deps: []
links: [ct-d8cf, ct-a1aa]
created: 2026-10-20T16:52:23Z
type: feature
priority: 2
assignee: mikewolfd
tags: [news-lake, analysis, export]
---

# Make persisted news labels usable by a maintained reader

Closed as deferred on November 5, not as delivered. No named News Lake reader currently needs these labels for a concrete user decision. The existing deterministic keyword producer remains available; a maintained selected-label reader and its persisted DocSpec round-trip remain unfinished. This optional feature is independent of backend retirement and congressional delivery.

## Reopening trigger

Reopen when a named reader and the decision supported by its topic or tone labels are defined. Reuse the existing producer and C8 run selector before considering a new classifier. Keep the method's limits and taxonomy visible.

## Deferred acceptance criteria

- The deterministic producer emits shape- and corpus-valid run and classification records with documented dimension, taxonomy version and typed value.
- Persist the run and labels through DocSpec, then read them through the maintained consumer in a fresh process from the requested published release. Use its processor/version/configuration selection and return only the winning run's typed labels.
- Cover competing matching runs, a newer nonmatching run, zero-output success replacing prior labels, and valid empty or pending results. Preserve method, run and release identity. Do not substitute the newest run globally for the selected run.
- Public disclosure remains subject to `ct-4nyy` rights and expiry. Runtime integration belongs to `ct-d8cf`. Neither closure as deferred nor future classifier adoption satisfies those separate obligations.

[Final root-cause review](../docs/plans/production-mvp-root-causes-round4-20261105.md).

## Notes

**2026-10-20T17:30:52Z**

Added deterministic keyword topic/tone classification producer and C5 export_release enforcing restricted/expired body omission, redistributable preservation, authorized bypass, and input immutability. Labels/export tests: 13 passed.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch kl2a1aa).
- Grades: proposal 83 → 83, work 75 → 75.
- Problem: C5 leak, reproduced with the project venv: expiry is computed only from `news.captures` rows present in the read (export.py:83-88; same in docspec/export.py:84-91).
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/kl2a1aa/kl2a1aa-verdicts.md:60
- Status: Reopened: revisit under engine-first rule. Its Python `export_release` C5 gate duplicates the engine policy and leaks on subset reads; WS8 (ct-d8cf) replaces it with the engine's export-rights policy. The keyword classifier still has no consumer, and its AC1 round-trip is untested.
- See docs/reviews/2026-10-24-ticket-audit/README.md

**2026-11-05T17:11:15Z**

Scope narrowed on 2026-11-05: retain the existing deterministic classification producer, a maintained consumer, and a persisted run/typed-label round-trip through DocSpec and selected-run semantics. Export rights and expiry acceptance moves to ct-4nyy; runtime integration is ct-d8cf. Replace the obsolete Iceberg-only round-trip expectation with the selected DocSpec backend while preserving corpus/shape and selection meanings. Standalone optional classifier adoption must not become a prerequisite for unrelated congressional delivery or backend retirement.

**2026-11-05T20:56:46Z**

Closed as deferred, not delivered. Reopen when a named reader and a concrete user decision require topic or tone labels. Preserve the existing producer, unfinished reader round-trip and deferred acceptance criteria. This feature does not gate backend or congressional delivery.
