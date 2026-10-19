# Exact-value browser and complete-export policy

Decision before the bounded experiment: retain exact values, ordinary lazy detail
and explicit complete JSON copy. Evaluate a complete JSON Blob download only as
an experiment; adopt it only if it reduces known simultaneous export value/clone/
format storage by at least 25%, preserves exact JSON values and order, and avoids
another stored format/parser. Unknown clipboard/OS allocation cannot count as a
measured saving. No implicit truncation or product byte threshold is introduced.

Ordinary detail defers observations; observation pages default to 20 and clamp to
100 items. Those are item limits, not byte guarantees: a selected value or its
logical block can be large. Technical scalar reads use eight columns at a time,
while physical Parquet chunks can still dominate active decode storage.

Explicit complete copy reads every original source field and observation, restores
field order and duplicates, clones the result from worker to main thread, then
formats complete JSON for the clipboard. The supported decision rule is exact
best-effort execution within that browser's available allocation/string limits;
there is no advertised fixed maximum complete-record byte count. The 16 MiB
logical counter is diagnostic only and does not reject values. Cache limits and
the 1 MiB decoder part limit do not bound active full-result memory. A caught
resource failure must reject the operation, display the complete-copy failure,
keep detail usable and leave original source Parquet download available. Fatal
browser/OS process termination cannot be guaranteed to deliver a JavaScript error.

The experiment will use one deterministic <=20 MiB serialized dictionary/reference
fixture, including a logical observation above the 16 MiB diagnostic counter,
split Unicode, null versus empty lists/objects, nested values, duplicate references
and explicit field order. It will separately report part bytes, logical text,
parsed values, restored result, worker-equivalent clone, pretty JSON and Blob
bytes. Run under pinned Node 22.22.2 with a 768 MiB heap flag, 1 GiB sampled RSS
ceiling and 30-second action deadline. These limits apply only to the experiment;
they do not become product rejection thresholds.

Reuse the saved 1,680,021-byte logical / 2,160,042-byte UTF-16 text /
4,320,132-byte formatted JSON accounting in
`docs/experiments/publication-remediation/browser.md`. No actual clipboard,
Parquet download, hosted/browser qualification or source acquisition is authorized
by this benchmark. Focused injected errors will check visible failure without
allocating until the machine fails.

## Result: keep the exact route and existing download recovery

The Blob candidate misses the target. The maintained decoder preserves the
16,800,163-byte serialized fixture exactly, including a 16,800,142-byte logical
block above the diagnostic threshold. All value, field-order, Unicode, nested,
null/empty and duplicate-reference checks pass. Both the ordinary observation
page and complete read succeed; the 16 MiB counter increments twice without
refusing either read. No product source change is justified by this experiment.

| Cost category | Observed count / estimate |
| --- | ---: |
| Largest decoded part | 65,537 bytes |
| Joined whole-block decoded bytes | 0 |
| Largest logical UTF-8 block | 16,800,142 bytes |
| Largest logical UTF-16 text | 21,600,274 bytes |
| Largest parsed-value estimate | 21,600,758 bytes |
| Active restored observation page | 21,600,976 bytes |
| Active complete result | 21,601,242 bytes |
| Worker-equivalent clone | 21,601,242 bytes |
| Pretty JSON UTF-16 string | 21,601,400 bytes |
| Pretty JSON UTF-8 / additional Blob bytes | 16,800,710 bytes |
| Retained decoded cache | 346 bytes under a 1 MiB budget |
| Process high-water RSS / total action time | 412,450,816 bytes / 1.225 seconds |

The explicit export model retains the result, clone and formatted string at
64,803,884 known bytes. Replacing clipboard output with an ordinary complete
JSON Blob retains those same values plus its 16,800,710-byte file representation:
81,604,594 known bytes, **25.9% more**, against a target of 25% less. Clipboard
internal allocation is unknown, so no saving from removing it can be claimed.
A Blob built from a complete JSON string is not an incremental exporter.

After explicit GC between stages, observed Node heap use is 5.4 MB after fixture
construction, 26.4 MB after the page, 48.0 MB after full reconstruction, 69.6 MB
after cloning and 112.8 MB after formatting; the Blob adds about 16.8 MB of
array-buffer storage. These numbers include the retained page, harness setup and
exact-value assertion/serialization copies. They do not reproduce a complete
browser UI or isolate one allocator. Categories can share strings/objects;
summing decoder estimates is not an RSS or hard-heap bound. The process peak
satisfies the experiment ceiling, without guaranteeing every browser can accept
this value or a larger one.

## User-visible rule and recovery

The current route remains supported for values the running browser can allocate
and represent exactly. It promises exact results or a reported operation failure,
not a fixed universal record-byte maximum. Ordinary lazy detail avoids the full
observation graph until requested, but neither a page-item limit nor cache budget
makes an individual logical value small. Complete copy is always explicit and
may hold worker values, a main-thread clone, full formatted text and clipboard
copies together.

The decoder translates caught allocation `RangeError` into an explicit browser
memory message with source-Parquet recovery. The worker/client delivers ordinary
operation errors; the UI catches reader, formatting and clipboard errors, shows
`Could not copy complete metadata: …`, re-enables Copy, and preserves the selected
detail. An uncaught worker failure reports reader failure/retry. JavaScript
cannot ensure visible diagnostics if the browser/OS kills the tab process.

The existing source Parquet download is the complete stored-source recovery route.
It requires an external Parquet reader and does not return one source's JSON
through the current clipboard action. Review/recovery updates remain separately
identified sidecars; downloading original Parquet does not merge those overlays.
A true incremental complete JSON exporter would require a measured implementation
that avoids whole-value parse/clone/format work while preserving these semantics.
This Blob experiment supplies no reason to add that format or change product limits.

## Verification and evidence

**75 focused checks passed** in 4.81 seconds. A new decoder test injects an
allocation failure, requires the Parquet recovery diagnostic, then retries and
checks all exact null/empty/duplicate/Unicode values without truncation. Three UI
regressions inject reader, JSON-format and clipboard allocation errors. Each
requires visible failure, the original detail and download link, a re-enabled
Copy button, and no partial clipboard write. Existing actual-worker checks prove
ordinary detail defers observations and complete export preserves full values.

The benchmark exercises the maintained observation decoder directly and uses
Node `structuredClone` and `Blob` as a bounded ownership experiment. It does not
invoke the actual clipboard or download anything. Run it with pinned Node 22.22.2:

```sh
node --expose-gc --max-old-space-size=768 docs/experiments/efficiency-debt/complete-export-benchmark.mjs NEW_RECEIPT
PYTHON="$PWD/output/efficiency-search-runtime/venv/bin/python" node --test apps/site/src/components/filename-complete-export.test.mjs apps/site/src/components/filename-viewer-ui.test.mjs apps/site/src/components/filename-worker.test.mjs apps/site/src/components/filename-catalog.test.mjs
```

[complete-export-evidence.json](complete-export-evidence.json) binds code hashes,
counts, stage memory, checks and the raw evidence at primary
`output/efficiency-debt-20261019/complete-export/`. The earlier small-value
accounting is reused from the committed browser report, not requalified here.
No source acquisition, hosted/full-catalog qualification, real clipboard write,
workflow mutation, publication or new product rejection threshold occurred.
