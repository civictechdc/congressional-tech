---
id: cefr-wzxu
status: closed
deps: []
links: []
created: 2026-10-27T18:36:48Z
type: task
priority: 2
assignee: raw
---
# D3: produce versioned filename readings through native work lists

Owner reassigned D3 to raw. New producer uses house-naming unchanged and shares one SQL effective-name definition with E.

## Acceptance Criteria

Shared effective-filename SQL; distinct raw/provenance work anti-join; bound parser typed keys and stable errors; complete version digest; focused fixtures; native append binding and live backfill owner command.


## Notes

**2026-10-27T19:44:05Z**

Local native binding passes 132 producer/golden tests with engine-6fc6a94: nested Iceberg append, repeated-work no-op, plain JSONL unreadable rebuild exclusion, bounded-worker protocol injection and CLI authority guards. Production ParserWorker implementation remains engine-owned and pending; default import fails closed. Independent CODE and ARCH reviews requested before closure.

**2026-10-27T20:29:37Z**

Confirmed CODE findings fixed in 2916f16a/fba99d79 with real worker integration. ARCH source-ownership contract 2111e22d reproduces the D1 coupling; dedicated lake.filenames package retains import, callback and module CLI paths. Complete 141 focused producer/actual-worker/native-table/module-CLI/golden checks pass with engine-656e7b5. Generic versions helper remains shared for D2. Ticket remains open until bounded independent fix review closes the concern; live backfill/platform/E qualification remain separate gates.

**2026-10-27T20:50:50Z**

Bounded fix followup CODE APPROVE and ARCH APPROVE, no remaining concern (run2/d3-followup/review.md). Actual engine-1c2473b runner test_filename_readings.py:26 passed33.38s; full D3/golden group141 passed on preceding snapshot. Local producer, native append and version isolation complete. Live backfill, Linux runtime and full E profile qualification remain owner/engine gates with exact command in run2 report.

**2026-10-28T02:10:33Z**

Shared filename input/supervisor version correction: fixtures committed before source change. Expected-red approved486 project runner: 5 failed / 4 passed in1.25s, precisely missing canonical SQL load/refusal and canonical SQL/parser_worker/process_resources version coverage. Isolated version fixture copies complete producer package and every listed dependency. Engine parity extension requested via COORD/mailbox/engine/20261028T020904Z-raw-filename-input-parity.md; engine owns model tests and canonical SQL.

**2026-10-28T02:12:19Z**

Shared-input/version correction locally green after contract5400f1f3 (5 expected failures/4passes). D3 now binds filename_captures over captures and reads canonical filename-inputs.sql; duplicate9line SQL removed. Existing digest helper includes canonical SQL, parser_worker.py, process_resources.py; isolated fixture copies complete code unit and mutates/restores each dependency. Full D3 plus existing actual E2/D3 parity:38 passed7.69s on approved486runtime. Module357->354lines. B4 pending/durable-rebuild guards preserved. Engine owns requested-only/rejected-recovery parity extension (mailbox20261028T020904Z). Parent CODE/ARCH review remains pending; no live writes.

**2026-10-28T02:30:52Z**

B3 CODE and ARCH approved. Test-only seam completion uses actual archive_model.source_steps first alias/input/effective steps and real D3 work_list with identical captures and already-current recovery records. Full expected seven filename/source_url pairs cover header precedence, literal member path, requested-only fallback, accepted/rejected recovery, duplicate pair and same basename on distinct URLs; native EXCEPT ALL both directions returns zero. Approved486 project runner test_filename_readings.py:38 passed6.63s (run2/review-filename-input-plan/parity-focused.log). No production/engine-owned SQL/model-test changes. Engine informed by mailbox20261028T023003Z; earlier model-owned extension request may remain. Fixture-only completion needs no new production review round.

**2026-10-28T02:31:42Z**

Local D3 completion: independent CODE and ARCH approve5400f1f3/9218e303; stronger actual-model factory parity fixture passes with full seven pairs and native two-way zero differences (38 filename checks6.63s on486). README records B4 reviewed-pin/raw-only rebuild18129d19/72191130,85pass16.88s, and canonical unique admission72e08e98/eff53177,87pass16.95s, retaining exact earlier proof boundaries. Local producer/rebuild scope complete; first live unreadable import, live filename append, complete D1 and Linux qualification remain explicit owner gates in README.
