---
id: ct-yr9o
status: open
deps: []
links: [ct-717p]
created: 2026-11-02T18:20:46Z
type: bug
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [records, post-release]
---

# Record malformed House XML as unreadable

A corrupt House XML body should leave a failure that operators can find. Meeting, appearance and committee record builders currently turn XML parse failures into completed empty results. The retained v21 audit found zero affected bodies: all 6,179 House XML meeting rows held a meeting, and witness lists for `111420` and `105459` were valid empty lists. That historical result does not establish the current affected population.

## Smallest useful change

Defer this to a later intentional House record transition that explicitly supports changed failure dispositions. Let malformed XML reach the shared `unreadable_decision()` path. The newly merged document-reference backfill requires completed rows and unchanged values and refuses pending unreadable decisions, so its equivalence proof cannot qualify this change. The Rules intake gap remains with `ct-717p`.

## Acceptance Criteria

- All three House XML record builders surface malformed syntax to the shared decision writer. The existing strict expected failures in `test_record_producer_unreadable.py` become passing cases. Exercise those malformed inputs through the maintained staging path and its decision consumer, not only the builder.
- Preserve valid empty lists and well-formed wrong-root inputs as completed empty results. State blank-input behavior at admission and keep missing body bytes pending. Record one durable failure decision per affected body, parser and version; a rerun at the same selected version must not retry a settled failure.
- Before widening any replay, inspect selected XML/error candidates and name the affected scope. Record the intentional source-scoped pin change and accepted unreadable outcomes. Reuse qualified unchanged values and retain the historical valid-empty evidence.

[Final root-cause review](../docs/plans/production-mvp-root-causes-round4-20261105.md).


## Notes

**2026-11-05T20:56:46Z**

Final root-cause review: keep malformed-XML handling for a source-scoped transition that accepts unreadable decisions. The completed-only document-reference backfill does not qualify this change.
