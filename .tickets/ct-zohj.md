---
id: ct-zohj
status: closed
deps: []
links: []
created: 2026-11-18T17:57:22Z
type: task
priority: 2
assignee: mikewolfd
tags: [recovery, capture]
---
# Start recovery when a fetched file fails to open, and stop refetching identical bytes

Found 2026-11-18 on ct-z4w5. The 49 damaged PDFs were served with HTTP 200, so the ladder treated each fetch as a success and never started archive discovery; 47 refetches then returned byte-identical damaged files. The architecture table (docs/recovery/holistic-recovery-architecture-20261031.md) now has the row '200 with a body that fails qualification: preserve it, go to archive discovery, do not fetch the same address again unless its validators change', marked not yet enforced (pull request 205).

What enforcing it takes (read from the code by the agent that built pull request 205; verify before relying on line numbers):
- capture_scheduler.py (about lines 935-954) fetches, writes the receipt and branches only on the storage outcome; 'stored' / 'unchanged' (body_store.py:103) means bytes were stored, not that they read.
- Rescheduling reads capture_disposition from URL state (capture_scheduler.py about 412-413 and 575-577); URL state sets it only from accepted recoveries and scope exclusions (archive_url_state.py about 181-187). No qualification fact exists there.
- The fetcher sends no conditional headers; receipts already keep ETag, Last-Modified and Content-Length (receipt_writer.py 22 and 117).
So three pieces: a qualification fact per body (a parse and render per PDF at capture or model time: measure that cost first), URL state marking the address done for refetch, and a due-time rule that refetches only when a validator changes.

Owner decisions needed: where the readability check runs and what it may cost per night; which validator changes count as 'the publisher replaced the file'.

## Acceptance Criteria

A body that fails qualification is routed to discovery without a person noticing it; an address that returned identical bytes is not fetched again until a validator changes; the per-night cost is measured and recorded.


## Notes

**2026-11-19T00:01:25Z**

Implemented and verified (`2026-11-18`, branch `ct-zohj-qualification-20261118`, artifacts under `.cache/archive-release/ct-zohj-20261118/`):

1. **Measured Per-Body & Per-Night Qualification Cost (`nightly-qualification-cost.{json,md}`):**
   - Benchmarked `corpus_recovery.qualification.qualify` (`recovery-qualification-v1`, Poppler `26.10.0` `pdfinfo`/`pdftoppm` at `18 DPI` + `pypdf` strict/lenient) under `scripts/archive_watchdog.py` across `84` local retained bodies (`12` `1–5pp` PDFs, `12` `10–50pp` PDFs, `10` `100+pp` PDFs, `38` damaged/truncated/encrypted/Poppler-error PDFs, `12` HTML bodies): peak watchdog RSS `194.6 MiB` (`0.19 GiB`, physical `162.8 MiB`) in `90.8 s`.
   - Per-body cold wall mean: `0.503 s` (`1–5pp`), `0.910 s` (`10–50pp`), `3.566 s` (`100+pp`, max tree RSS `101.5 MiB`), `0.746 s` (`damaged/unqualified` fast-fail), `0.125 s` (`HTML`); corpus-weighted PDF mean (`<= 16 MiB`) = `0.953 s` wall / `0.630 s` CPU; warm on-disk `qualification-cache` hit = `~41.7 ms`, in-memory `qualifications.jsonl` index = `< 0.1 ms`.
   - From published release `2ec7ae83a852` (`detail.parquet`, `sources.parquet`, `url_state.parquet`) and consecutive release diffs, steady-state Nov 2026 capture nights add `66.2` mean (`109` peak) new distinct PDFs/night -> **`63.1 s` (`1.05 min`) mean / `103.9 s` (`1.73 min`) peak 1-worker wall time per night** (`238.3 s` / `3.97 min` at the `250`-PDF unattended nightly addition cap), well inside the `120 min` `capture-archive.yml` window.

2. **Enforced `holistic-recovery-architecture-20261031.md:174` Without Touching Byte-Hashed Parsers or `qualification.py`:**
   - Added `congress_api.retention.qualification_facts` owning verified `QualificationRecord` digests, URL-bound qualification facts, validator extraction (`ETag`, `Last-Modified`, `Content-Length`), conditional request headers (`If-None-Match`, `If-Modified-Since`), `validators_unchanged`, local store validator recovery, and native `body_qualifications` model input.
   - `capture_scheduler.py` preserves HTTP-200 bodies and receipts as-is in `BodyStore`, qualifies captured PDF bodies into `work/qualifications.jsonl` + `qualification-cache`, attaches conditional headers on unqualified URL rechecks, and aborts before streaming body bytes (`wire_bytes=0`) on `304 Not Modified` or `200` with unchanged validators (writing a body-less `outcome='unchanged'` receipt that advances `next_attempt_at` without losing `body_not_qualified` or breaking `release_gate.py` `url_state_proof`). Any change in `ETag`, `Last-Modified`, or `Content-Length` downloads and re-qualifies the new body.
   - `archive_url_state.py` (`include_qualifications=True`), `archive_model.py`, `archive_model_job.py`, `archive_model_profile.py`, `inventory.py`, `campaign.py`, and `pipeline.py` consume verified qualifications so unqualified HTTP-200 bodies remain `eligible` (`capture_reason='body_not_qualified'`, `usable_direct=False`) and route directly to archive discovery and candidate scheduling while healthy HTTP-200 PDFs remain `usable_direct=True` (`qualified_direct_body` under `historical_only`, ordinary refresh under `refresh_live`).

3. **Archive-It Timemap Probe (`archive-it-timemap-probe.{json,md}`, `LOC-HANDOFF.md:88`):**
   - Politely probed `https://wayback.archive-it.org/all/timemap/link/<url>` (`>= 2.15 s` spacing, `timeout=20 s`, `0` `429`/`403` responses) across all `18` House Oversight `2011` gaps (`36` legacy + post-`2012` URLs: `0/18` hits) and a `30`-URL stratified open non-Akamai `invalid-sources.jsonl` sample (`11` House, `11` Senate, `8` Gov: `7/30` hits, all `7` already covered with `>= 5` HTTP-200 captures in IA Wayback -> **`0/48` unique yield beyond IA Wayback + NARA Web Harvest**). Confirmed omitting Archive-It from default automated pipeline rungs.
