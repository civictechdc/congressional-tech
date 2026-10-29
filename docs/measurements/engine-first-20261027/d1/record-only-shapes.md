# Full-receipt record-only census and fresh owner runs

The read-only census verified all 2,292 pinned receipts by compressed-byte SHA-256 and exact source-row counts: 2,598,311 lines. Among 1,277,888 rows without a primary reference or without list-item coverage, 47,695 retain acquisition facts and 1,230,193 are record-only. It found these 23,747 previously unregistered items:

| Shape | Items | Explicit result |
|---|---:|---|
| Document URL/digest pair | 16,441 | `reference`; keep URL, never copy digest into body custody |
| Local-path/digest pair | 7,084 | `saved-record`; inline metadata |
| YouTube caption identifiers | 84 | `saved-record`, one per item |
| YouTube API identifiers | 104 | `saved-record`, one per item |
| Senate page identifiers | 21 | `saved-record`, one per item |
| Empty pending/error collections | 5 | One `saved-record` row per collection |
| Eight literal malformed document addresses | 8 | `reference`, without address repair |

The immutable packet `shared/capture-record-shapes-09e9ec6a` contains counts, keys, example locators, classifications, per-item pair validation and `malformed-document-urls.json`, the complete eight-row data-quality list. Enumeration took 283.494 seconds and peaked at 533,612,080 sampled physical bytes under a 2 GiB ceiling. These are local macOS measurements.

Mapping `52120d49aa771c10105d87af6440b3d2a0b0c297aca08a0dac1c654205464d4b` retains explicit acquisition facts and unknown-shape refusal. The focused production-offline lane passed 115 tests, without failures, errors or skips. One code review approved the source and owner controls after correcting the aggregate status filename. A separate private test invocation was refused before collection because its path was outside lane roots; it contributes no test result. Read-only metadata preflight confirms the corrected status path, pins and source coverage.

## Lead-only proof-v3 and full commands

```sh
cd /Users/mikewolfd/Work/wt/ct-engine-first-raw
D1_SHAPE_RUN=/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/codex-raw/run2/d1-record-shapes-52120d49
memory_pressure
.venv/bin/python -I "$D1_SHAPE_RUN/cxb_d1_record_shapes_v3.py" proof launch
```

The detached driver runs six detached cohorts serially, with START/END mail and fresh admission for each. Five large variant receipts stand alone; the remaining 200 receipts total 979,363,163 logical bytes. Together they cover all six registry kinds and all 48 currently populated registry cases. Each cohort has a 2 GiB logical cap, except the singleton YouTube captions receipt, whose exact size is 2,147,676,643 bytes. Assembly limits remain 20 GiB native / 24 GiB physical; standard limits remain 10 / 16 GiB. Both use two CPUs, a 5 GiB owned-storage ceiling and a 25 GiB free-disk floor. The driver waits until sampled free, inactive and speculative pages meet its physical requirement. Any cohort failure stops the chain without retry.

Only after all six cohorts are `equivalent`:

```sh
.venv/bin/python -I "$D1_SHAPE_RUN/cxb_d1_record_shapes_v3.py" full launch
```

The full command independently checks every cohort, then writes 118 groups into fresh local table `d1_record_shapes_52120d49.captures`, expecting 4,147,132 rows from all 2,292 receipts. Its comparison and downstream acceptance remain separate gates. Original failed runs and their controls remain intact; these commands reuse none of their work or table locations. No corpus proof or full job was launched during preparation.
