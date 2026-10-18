---
id: ct-hnxb
status: in_progress
deps: [ct-sv16]
links: [ct-gubr, ct-gesp, ct-zika]
created: 2026-10-18T19:21:16Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-d8z3
tags: [publication, audit-20261018, grade-followup]
---
# Bound decoded memory during viewer preparation

Row-count limits of 8192 or 128 do not bound nested Arrow/JSON record size. Large observations can expand beyond compressed-part limits, while global catalog indexes also remain resident. This is a scaling risk; it is not proof of the earlier OOM stage.

Source: repack_and_verify, publish_details, publish_observations, and observation block assembly.

## Acceptance Criteria

Use measured stage evidence to define a decoded-byte budget and explicit handling for records larger than that budget. Preserve every value, null, duplicate, and order. Exercise worst-record fixtures with a memory ceiling and clear failure evidence; do not silently truncate or drop records.

<!-- grade-followup:start -->
## Grade review follow-up

Explicitly cover observation count handoff, duplicate serialization, dedup-index memory, logical-block reconstruction, detail encode copies, and repack batch memory. Treat full value verification as a constraint.

- Use an explicit decoded-byte budget and oversize-row policy; stream/count handoffs and spill options preserve every value, null, duplicate, order and current semantic fixture.
- Do not reread reference sidecars solely to derive counts; reject count/source mismatch.
- Keep full source-versus-output value checks and timestamp/Unicode canonical cases; each part is decoded once per observation verifier. Row/part limits alone are not acceptance.

[Function scope and checks: 11 entries](/Users/mikewolfd/Work/congressional-tech/output/publication-exam-20261018/BELOW-B-PLUS.md:410). Grades remain unchanged until implementation is verified.
<!-- grade-followup:end -->

## Notes

**2026-10-18T20:31:06Z**

Returned to open while finishing shared reader/resource/export batch; prerequisite ct-sv16 is merged, implementation not yet started.

**2026-10-18T20:56:53Z**

Implemented shared 128-row native cap plus physical/Arrow/Python/JSON admission; explicit source-bound integrity-checked observation counts; SQLite identity spill; one-pass part parsing; row-streamed exact detail checks; adaptive full Arrow repack comparison and bounded coalescing. Focused Python 235 tests, 100 browser tests, 29-page build, and both emitted bootstrap tests passed. Final memory receipt and independent review pending; native single-row decoder allocation remains an explicit limitation.

**2026-10-18T20:58:07Z**

Final local evidence: docs/experiments/publication-remediation/decoded-memory.md and evidence/decoded-memory{,-verification}.json. Native decode capped at 128; actual returned Arrow bytes and nested-container Python estimate checked before conversion; dictionary expansion refuses before Python. Per-object get_total_buffer_size metrics distinguish retained slices from logical nbytes. Both accepted/refused workers passed 512 MiB sampled+high-water ceiling; every source hash preserved. 235 focused Python, 100 browser, 29 built pages, 2 actual bootstrap smoke; earlier 60 custody/CLI checks also passed. Raw source/failure outputs retained output/decoded-memory-final6-20261018; awaiting independent exact-commit review before closure.

**2026-10-18T21:01:18Z**

Final integration correction: shared ArrowStager coalesces detail/repack output under logical staging/row targets with native reads128; stricter custom row limit tested. Same fixture detail layout changed101 groups/237429bytes to2groups/21688bytes, all ordered Arrow values equal; separate retained-buffer metrics preserved. Follow-up80 Python and100 browser checks passed. Final raw artifacts now output/decoded-memory-final8-20261018 (includes baseline detail file); root must transfer before archive.

**2026-10-18T21:01:54Z**

Independent static review approved implementation a80ec34 and staging fix868e52a (preparation lane); no remaining blockers. Final receipts9ca9c7d: accepted RSS342327296B and refused205357056B under536870912B watchdog/high-water ceiling, source unchanged; full exact checks maintained. Detail coalescing resolves intermediate small-rowgroup regression (101groups237429B ->2groups21688B on same fixture, ordered Arrow equality); native128 and separate retained-buffer metrics preserved. Local acceptance complete; production/offline combined integration remains root-owned. Raw evidence output/decoded-memory-final8-20261018 must be transferred before archive.

**2026-10-18T21:27:51Z**

Release preflight found a real-input regression before merge: rebuilt documents row group 389 declares 163,912,431 uncompressed bytes, so the current whole-row-group 64 MiB check rejects it before bounded streaming. Small fixtures missed this. Repair admission without raising resource limits or weakening exact-value checks; verify the retained real footer and meaningful oversized-input refusals before closing.

**2026-10-18T21:42:46Z**

Corrected aggregate admission in reviewed commit 2829e2e: physical group bytes now plan native rows (retained group 389 -> 26); actual Arrow/Python/JSON record limits and exact equality remain. Reuses owned Catalog readers, removing six input footer opens. Passed 91+142 overlapping focused Python checks, 17 browser-reader checks and edge cases. One unchanged 512 MiB fixture watchdog passed: accepted 264257536 B, refused 188448768 B; source preserved. Independent exact-commit review approved. Real full-catalog memory/row acceptance remains unqualified until normal publication; the stopped zero-row probe was not retried.

**2026-10-18T21:50:25Z**

Reopened after hosted viewer preparation 39169129734 failed in repack before accepting or publishing output: single-row Python/JSON estimate 167939288 B exceeded 134217728 B. Repack writes and compares Arrow values without converting them to Python, so stage admission currently charges an unused conversion. Preserve true Arrow limits and Python/JSON checks where conversion occurs. Failure ZIP12151991789 and logs preserved locally; no workflow retry or resource change. Also retain the memory failure receipt in the always-uploaded diagnostic artifact.

**2026-10-18T22:16:26Z**

Complete local retained-catalog trial at runtime c8dda5d passed exact document bytes and all 1,683,430 filename values, then refused aggregate observation-list Python estimate 376238952 > 134217728 bytes. Peak RSS 3788423168 bytes; sources unchanged, no manifest accepted. Filename layout regressed to 2673 groups / 777356470 bytes / 135166663-byte footer. PR115 held. Parallel fixes under this same ticket: convert one observation at a time with unchanged per-conversion limits; separate measured retained writer staging from decode batching. Evidence: primary output/publication-remediation-20261018/rollout/local-current-catalog/trial-c8dda5d/qualification-receipt.json.
