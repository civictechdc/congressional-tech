---
id: ct-5fkx
status: closed
deps: [ct-egpe, ct-xq1y]
links: [ct-nloa, ct-jo8n, ct-qkvr, ct-xq1y, ct-oxg6]
created: 2026-10-20T23:32:02Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, news-lake, generations, update, application-adoption]
---
# Preserve or advance coupled producer relationships across native Update polls

DocSpecLake._commit_append and _commit_upsert (packages/news_lake/src/news_lake/storage/docspec_backend.py:924-925,1054-1061,1078-1085) pass relationship={'kind': 'coupled', 'family': family, 'generation': generation} into update_table, which writes spec['relationship'] on UpdateSpec. However, docspec-rs UpdateSpec (src/model.rs:875-883) has no relationship field (serde silently drops it) and inputs::relationship (src/engine/inputs.rs:515-528) inherits base.relationship (keeping generation='g1'). Meanwhile, Engine::seal_generation_admitted (src/engine/inputs.rs:48-74,99-118) requires every member in seal.members to match the fixed family-members set and carry SourceRelationship::Coupled with the new generation. Consequently, sealing a second poll ('g2') after any Update or partial-table batch fails with invalid_relationship.

## Acceptance Criteria

- Establish and implement one coherent multi-poll relationship contract between news_lake and docspec-rs: either (a) extend docspec-rs UpdateSpec (src/model.rs:875-883, src/engine/inputs.rs:515-528) to accept an explicit relationship override and define partial-poll family sealing, or (b) keep polled news_* datasets SourceRelationship::Independent and bind multi-table news releases through the application release record plus capture_inputs (src/engine/inputs.rs:163-254), removing the ignored spec['relationship'] field from update_table (docspec_backend.py:924-925).
- Add a regression test in packages/news_lake/tests/test_docspec_backend.py that commits Poll 1 (g1) and Poll 2 (g2, touching both append and upsert tables while leaving at least one table untouched) and verifies that generation sealing / release input capture succeeds and preserves exact old and new release pins.

## Notes

**2026-10-20T23:32:30Z**

Created from evolutionary-refactoring audit of `docs/plans/docspec-application-adoption-20261020.md` against `main` (`8221566d` / `33ce7877`) and `docspec-rs` (`22a804e1`). Evidence: `packages/news_lake/src/news_lake/storage/docspec_backend.py:924-925,1054-1061,1078-1085,1087-1098` vs `docspec-rs/src/model.rs:875-883` and `docspec-rs/src/engine/inputs.rs:48-74,515-528`.


**2026-10-20T23:53:21Z**

CS 300 Grade at 8221566d — Spec: A | Impl: F (Open P1 Bug). docspec_backend.py:924-925 writes spec['relationship'] on UpdateSpec, which docspec-rs (src/model.rs:875-883, src/engine/inputs.rs:515-528) silently ignores, causing lake.seal('g2') on Poll 2 to fail with invalid_relationship (:72-73). Sequenced behind ct-xq1y.

**2026-10-21T00:31:34Z**

Implemented in docspec-rs: UpdateSpec now has #[serde(default)] relationship: Option<SourceRelationship>; inputs::relationship reads it; fingerprint includes it; backfill verification accepts inputs::relationship(spec, Some(base)) for Update. New tests/update_relationship.rs proves Poll 2 can advance g1 -> g2, seal g2, capture inputs, and retain the declaration after reopen; omission retains the base. All UpdateSpec constructors updated. Requires a rebuilt/qualified binary before application verification.

**2026-10-21T00:58:53Z**

CS 300 Post-Review Fix -> Grade: A. Added DocSpecLake._advance_relationship (packages/news_lake/src/news_lake/storage/docspec_backend.py:619-634) so family tables that have zero incoming records or idempotent replays in Poll 2 advance their coupled relationship via a 0-row UpdateSpec (reusing 100% of existing data files without rewrite). Added test_multi_poll_coupled_generation_sealing_with_partial_tables in packages/news_lake/tests/test_docspec_backend.py:939-990. Verified: 13 passed in test_docspec_backend.py.
