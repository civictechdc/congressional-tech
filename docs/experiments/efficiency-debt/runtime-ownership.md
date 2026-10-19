# Selected recovery runtime ownership (ct-piku)

The dispatcher now selects one project source tree before execute-mode import
admission. It refuses foreign or ownerless cached project/helper modules and
missing or escaping required package sources. It preserves read-only preflight,
original publication conditions, and refusal to resume changed source pins.
Unsupported layouts require a complete selected checkout and a fresh process;
the dispatcher never deletes or rebinds cached modules.

One early path selection replaces the late package-path mutations. Both real
publication modules load once before the shared lock and client boundary. Their
explicit-file child modules receive the same origin checks as cached imports.
An eager import failure therefore leaves no shared lock behind, even while its
exception traceback remains alive. At guarded writes, cached module object,
origin and package-path observations avoid filesystem resolution when unchanged;
new objects or changed paths receive a full ownership check. Existing source
digest guards continue to check file changes.

The bounded experiment compares exact baseline `b879ba642f4e8b2abdb21640dcf22c5442b186fc`
with the candidate driver hash in [the receipt](runtime-ownership-evidence.json).
All 319 selected source files (3,559,245 bytes) match that baseline. The same
fixture runs serially before and after; two damaged copies bring total fixture
source to 10,581,435 bytes, below the declared 16 MiB ceiling. Each fresh-process
case has a 30-second deadline. A sentinel replaces client construction, and the
cloud-writer probe is disabled. No real client, remote operation or source
acquisition occurs.

| Observation | Baseline | Candidate |
| --- | ---: | ---: |
| Unsafe cases reaching client boundary | 8 / 8 | 0 / 8 |
| Unsafe cases running import admission | 8 / 8 | 0 / 8 |
| Clean real project modules / explicit-file modules observed | 71 / 0 | 77 / 7 |
| Pinned files / bytes | 279 / 3,293,779 | 337 / 3,623,880 |
| Unchanged warm ownership checks / path resolutions | unavailable | 25 / 0 |

The eight unsafe cases cover real ambient API, filename and control modules,
unknown origin, extended package search paths, missing selected recovery source,
and escaping source symlinks. The candidate clean case loads the real builder,
publisher and their children from the selected tree. Warm ownership checks took
0.453 ms median and 0.623 ms maximum in this local sample. More complete source
pins add 58 files and 330,101 bytes to the initial pin/hash set. Later guard
boundaries compare file custody metadata and reuse unchanged hashes; they do not
rehash all of those bytes per payload. Runtime ownership checks also reuse
unchanged module observations. This is a correctness cost, not an efficiency gain. Fresh-process elapsed samples
were 0.701 s before and 0.632 s after, with host filesystem caches uncontrolled.
These single samples establish no speed improvement or cold-I/O result.

Focused admission/dispatcher checks passed **38 tests and 5 subtests**. The
affected recovery/publication suites passed **246 tests and 7 subtests**. Tests
also retain lazy preflight, accepted-phase reuse, explicit source-change refusal,
original selector conditions, and guarded write/readback outcomes. Existing phase
fixtures stub publication functions; only the subprocess tests prove actual
alternate-runtime import ownership. This is local verification, not a live or
full-catalog qualification; third-party dependencies remain supplied by the
isolated interpreter environment.

Commands, exact source/helper hashes and raw receipt hashes are in the committed
receipt. Raw evidence is retained at
`output/efficiency-debt-20261019/runtime-ownership/` in the primary checkout.
Only `before.json` and `after.json` are accepted measurements; earlier draft
receipts include a shared-lock contention attempt and are superseded. The
reproducible source-only probe is [runtime-ownership-probe.py](runtime-ownership-probe.py).
