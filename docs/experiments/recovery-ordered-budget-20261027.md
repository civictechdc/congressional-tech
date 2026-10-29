# Recovery ordered-read budget and bounded production sample

The recovery caller now admits 96 MiB, matching the declared limit of every
retained selected pin: 106 filename pins (1,683,430 rows) and 74 document pins
(1,241,157 rows). The previous 64 MiB caller limit rejected those declarations.
The fix changes no native reader, sorting, row-count, membership, or order proof.
Code and regression tests: `564ea34b2d1cf2760765e765ec7213d8899aaa1a`.

Focused validation: 70 passed, one qualified-native test skipped. The tests
exercise the former declared-limit refusal, successful 96 MiB projection,
duplicate-order rejection, and the maintained preparation caller's cap.

A separate read-only container qualified one retained production filename pin:
`catalog-filenames-02f6501cfd45c7a2f038d82032abce4f48c64f671896de2d287ab8693634db75`.
The selected source was
`97e2ff1b675d11ba2dc6f4c9a9e25182474fa47060bc48b7913b358ffde841b8`.
The projected read returned 16,590 `source_url` rows (1,670,108 Arrow bytes),
matching exact captured native values and retained order. It used one native
stream: 55,132,377 Arrow bytes, 15.867 seconds. This is one-pin evidence, not a
full recovery or release qualification.

The same bounded diagnostic sampled two URLs, with no whole recovery run:

| URL sample | Operation | Rows | New native streams | Seconds |
|---|---|---:|---:|---:|
| A | targeting | 0 | 1 | 3.981 |
| A | first at_url | 1 | 3 | 49.638 |
| A | repeated at_url | 1 | 0 | 21.119 |
| B | targeting | 0 | 0 | 0.003 |
| B | first at_url | 1 | 3 | 47.087 |
| B | repeated at_url | 1 | 0 | 23.497 |

Total: 163.218 seconds and eight native streams, including the projection.
Repeated URL lookups returned identical values. Existing row caches avoided
new native streams on warm repeats, but substantial local work remained.
Source inspection shows `_lookup_sources` creates a new selected dependency
reader and SQL working set per call; membership lookup retains only two leaves.
These observations justify separate initial-recovery reuse work. This commit
does not change that path.

Evidence remains under
`output/release-finish-20261026/recovery-ordered-budget/`:

- `result.json`: SHA-256 `6efb6344f272afce76910b308d873187e270f10d7325942150f63503e2ae7099`.
- `probe.py`: SHA-256 `425c6faaa8ab72043763db1b8fc052b2e8248a0e4c3e7378a57c3f1bd2cdb2cd`.
- `probe.log` records stream and lookup timings.

The old preparation and existing metadata cache were mounted read-only. The
probe wrote only its separate diagnostic directory and native workspace. It
performed no R2 writes and changed no checkpoint or preparation binding.
