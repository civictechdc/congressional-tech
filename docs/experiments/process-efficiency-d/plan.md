# Source context comparison, 18 October 2026

Decision: keep a single pass over sorted source observations, and adopt a bounded
serialized result cache only if its complete comparison passes all gates.

Hypothesis: repeated source rows sharing exact URLs spend avoidable time decoding
the same observations. One-pass aggregation halves the observation reads for each
lookup; a finalized cache should remove repeated reads while preserving every
field, occurrence pairing, and list order. A slower complete run or higher peak
memory weakens the cache proposal.

Arms: reviewed baseline `24137dd08241c34f1632afcd78a80a6138e5779d`; one-pass sorted
aggregation and exact link predicate; the same candidate with a 1 MiB serialized
cache after all context mutations. Baseline source copies are retained under the
worktree's ignored `output/process-efficiency-d/baseline/`. Candidate source hashes
and the benchmark script hash are recorded for each run.

Cases: a constructed, frozen retained catalog with 32 shared URLs, 64 paired
observations per URL, and 16 distinct source rows per URL. Each occurrence retains
its parent URL, title, hash, label, and receipt. Extra legacy filters, repeated
URLs, reverse-arriving links, cycles, large records, mutation safety, and cache
eviction receive focused correctness checks. The constructed case measures this
mechanism; it does not qualify a full production catalog.

Held constant: the worktree's locked Python environment, frozen input bytes,
single filename worker, no body inspection or acquisition, the same host and
filesystem, warm uncontrolled operating-system cache, and the existing
`scripts/benchmark_core_rebuild.py` rebuild/comparison path. Run three alternating
pairs baseline/cached, cached/baseline, baseline/cached. Then run three alternating
pairs baseline/one-pass, one-pass/baseline, baseline/one-pass if the cache fails.
Stop at 12 timed rebuilds or 30 minutes of benchmark time. Retain every failed run
and any preflight separately; do not use preflight timings in the comparison.

Decision rule: all source/document values and required ordering must match the
baseline. Cached association-stage median must improve at least 20%; complete
rebuild median must regress no more than 5%; maximum measured process-tree RSS
must not exceed the baseline's maximum. Unavailable process-tree memory leaves
the cache unqualified. If any cache gate fails, retain only one-pass aggregation
and the narrow exact-value predicate and report their measured benefit. Report
counter totals, memory sampling method, timing spread, and scope limitations.

Before timing: the first constructed fixture omitted publisher type provenance.
The legacy restore path deliberately discards such unverified context. Retain
that untimed fixture and generate `fixture-v2` with explicit publisher type and
basis in every occurrence, so it actually exercises repeated occurrence reads.
This corrects the workload; the acceptance thresholds remain unchanged.

Linux measurement setup, recorded before timing: use the environment agent's
`congressional-process-python:local` image, pin its image ID in the run manifest,
and run each arm with two Docker CPUs, a 2 GiB memory limit, one filename worker,
and network disabled. Mount code and frozen inputs read-only, and mount only the
run output directory writable. The existing sampler reads Linux `/proc` every
250 ms. Wait for the environment checks to release this worker; C measurements
start after this D comparison. The baseline preflight's expanded output pair
becomes the exact reference; its expected mismatch against the unexpanded input
is retained in `reference-preflight/benchmark.json` and excluded from timings.
