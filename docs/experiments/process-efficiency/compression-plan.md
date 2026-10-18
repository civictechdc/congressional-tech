# Complete viewer compression comparison

Current decision: the user authorized the maintained default to change to Zstandard
9, with publisher version 10, based on the completed bounded research. This local
change has not been deployed; deployed production remains unchanged. Complete
Linux performance and remote delivery remain unqualified.

The following preregistration records the original proposed adoption hold, which
the user's later instruction superseded. Its complete-trial criteria remain in
the benchmark harness for future qualification.

Original decision: qualify an explicit compression policy for the maintained viewer
builder and retain Zstandard 19 until every adoption gate passes.
Hypothesis: levels 9/3 reduce complete preparation by at least 25% while output
size grows at most 15% and fixed browser reads regress by at most 10% at p95.
Arms: actual publish() using levels 19, 9 and 3; batch/row groups remain 8192.
Cases: a small matrix preserves nested values, nulls, empty lists, duplicates,
metadata and multiple row groups; complete catalog 76758ea73fa94075bda46ce79e569fd3
is verified from its original selected manifest before use. Exact builder equality
checks and all derived output hashes remain required, including reviews and IDs.
Held constant: Python 3.12.13, Arrow 25.0.1, one Arrow CPU/I/O worker, input and
review identity bytes, same local filesystem, fresh process per run, warm cache.
Order: 19/9/3, 3/9/19, 19/9/3, preserving every failed trial and its outputs.
Bounds: 90 minutes per complete trial; process-tree RSS 3 GiB; 12 GiB free scratch
floor. Shared local Linux VM has 2 CPUs and 8.3 GB total; unrelated services remain
untouched. No parallel full runs. Stop the attempt on its first failed bound.
Decision rule: three complete Linux measurements per arm, exact equality, <=15%
byte growth, >=25% complete preparation reduction, and <=10% browser p95 regression
are jointly required. Choose the smaller passing candidate. Missing Linux capacity
or browser proof leaves level 19 unchanged. Failed attempts are retained and are
not omitted from the result. No live-delivery claim follows from local measurements.

## Recorded capacity result and user decision

The first Linux attempt could not resolve the worktree Git metadata. The corrected
attempt verified the complete source sizes/digests, then its baseline level-19
worker was killed after 10.053 seconds before producing a publication file. Docker
recorded an OOM event for the 3,584 MiB container. Sampled process-tree RSS peaked at
2,391,310,336 bytes; that is a sampled lower bound, not the kernel peak. The existing
shared 8.3 GB daemon was not resized and unrelated services were not changed.
Actual image runtime was Python 3.12.15 / PyArrow 25.0.1; the local macOS runtime was
3.12.13. The failed attempts remain in output/process-efficiency.

The worker's original final-only timings did not survive SIGKILL. The last durable
completed operation was the supervisor's full input verification; a finer worker
stage cannot be established from that attempt. The maintained harness now flushes
stage-start/completion events during preparation. No capacity retry was run for
this instrumentation change.

After this failure, the user explicitly instructed: "lower the compression, you
already did the research". This overrides the proposed adoption hold. The maintained
default is now Zstandard level 9, with publisher version 10 so an existing same-
catalog release cannot suppress the change. Level 9 uses the smaller output tradeoff
in the completed research versus level 3. Exact value checks remain mandatory.
This is user-authorized adoption based on bounded research; complete-catalog Linux
performance and remote delivery remain unqualified. The proposed full-catalog
thresholds remain available in the harness as future qualification criteria.

## Integrated harness check

The maintained driver completed all three levels on the seven-source/six-document
fixture, then ran real Chromium for five repetitions of 12 fixed loader cases per
level. All Parquet values, derived files, ID shards, review bindings and browser
result hashes matched exactly across arms. The driver compares each case's p95
only after runtime, loader bundle, review, recovery and case identities agree.
These 180 browser samples are a harness/fixture check, not complete-catalog
performance qualification. Output and every stage event are retained under
`output/process-efficiency/compression-integrated-fixture/`.

The browser uses Playwright 1.62.1, Chromium 148.0.7778.96 and esbuild 0.25.12.
The earlier unavailable-browser and HTML-content-type attempts remain under
`output/browser-fixture/chromium-attempt-{1,2}/`; the corrected standalone browser
fixture remains attempt 3. See browser-benchmark.md for the exact local tooling.

The focused builder, browser server and benchmark identity checks passed 26 tests
in 0.62 seconds. Compact fixture and failed Linux receipts are retained in
`evidence/compression-fixture.json`, `evidence/compression-linux-failure.json` and
`evidence/compression-linux-oom.jsonl`. The file-backed core catalog work does not
establish a fix for the viewer worker's unlocalized out-of-memory failure.
