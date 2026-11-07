# Independent greybeard review: original row reader

Scope: the maintained `openArchive` raw-row API, original values and identity,
decoder limits, source coordinates and the smallest reusable owner boundary.
The reviewer started without parent conversation history, inspected source and
retained evidence, and ran small independent in-memory probes. No source edits,
native producer jobs, deployment or broad tests were performed by the reviewer.

The review closed these concrete findings:

- Browsing normalization and whole-list startup cannot supply original rows.
  Raw mode now returns before list decoding and uses the original file path.
- The pinned decoder changes logical-only dates/lists, decimals, maps, JSON and
  other unsupported annotations. The supported-schema guard refuses lossy forms,
  contradictory annotations and repeated scalar/struct shapes before decoding.
- Global positions cannot trust `row_range` alone because the existing release
  hash excludes that field. Shard ordering now derives from digest-bound names
  and row counts, and the declared ranges must agree.
- `__proto__` and dotted field names can disappear or collide inside the pinned
  decoder. They now produce explicit refusals, including the independently
  authored nested dotted-name regression.
- Publicly returned objects must not alter later identity or budget decisions.
  Descriptors and schemas are copied, binary values are detached, and internal
  allocation uses a private counter.
- Temporal values must remain distinct from identically shaped business structs.
  Private markers and exported type guards preserve that distinction in the
  direct API; the original schema remains required across structured cloning.

Final reviewer disposition: no remaining concrete defect in the reviewed boundary.
The reviewer inspected 18 passing focused cases and 125 passing Explorer cases.
The final follow-up adds first-page coverage for every materialized rich table;
its exact receipt is recorded in `status.json`.

Limits: the review establishes scoped local behavior, not production-scale
memory, worker transport, publication or full migration acceptance. The existing
32 TypeScript diagnostics remain; comparison found no added diagnostics.
