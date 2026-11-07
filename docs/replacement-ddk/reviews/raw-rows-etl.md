# Independent ETL review: original row reader

Scope: complete file verification, selective row decoding, live allocation,
cache ownership, cancellation and returned-value lifetimes. A separate reviewer
read the ETL workflow skill, inspected the maintained decoder and reader, and
used small read-only metadata and allocation probes. No native computation,
source changes or heavy test runs were performed by the reviewer.

The review closed these concrete findings:

- A row limit does not bound decoded work. Admission now accounts for every
  intersecting row group, compressed copies, uncompressed bytes, physical value
  counts and nested containers before decoding.
- Nested allocations grow with physical values and path depth, including
  temporal objects and returned copies. The estimate now includes that factor;
  exact serialized path arrays avoid collisions in its lookup.
- A small binary cell can retain an entire decoded page. Returned binary values
  now own exact-size buffers.
- Small binary statistics can retain a complete footer slice. Metadata binary
  views are detached before cache accounting.
- Canceling a shared waiter does not stop its underlying verification. The
  resource reservation remains until verification settles; another caller may
  still use its result. Decoder cancellation remains cooperative.

The reviewer confirmed that the existing bounded cache owns verified buffers
and metadata; persistent table closures do not defeat eviction. Documentation
states the default 1 MiB compressed-file cap, conservative allocation estimates,
caller-owned returned pages and the distinction from measured process memory.

Final reviewer disposition: no remaining resource or lifecycle blocker in this
scope. The reviewer inspected the 18-case focused result. Final table-coverage
and source-custody evidence is recorded in `status.json`. Production-scale file
acceptance and full migration acceptance remain separate.
