---
id: ct-zohj
status: in_progress
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

**2026-11-19T00:29:54Z**

Review 7 (`review-m7-ct-zohj.md`, REQUEST CHANGES on `254f608c`) corrections. **This supersedes the 2026-11-19T00:01Z note where they disagree.** The acceptance criteria are not yet met in production, so the ticket stays open.

Fixed in code:
- **Only a full HTTP 200 can be validator-suppressed.** The direct adapter alone makes the pre-stream decision. 206, `Content-Range` and 202 responses keep their own receipts. The writer emits `unchanged` only for 304 or a complete body-less 200.
- **Verified facts only.** Every fact must carry its full `QualificationRecord`, and the record must pass `corpus_recovery.qualification.verify_qualification_record` under the current `VERSION` and `QualificationConfig`. A record from another version or config counts as stale: it is ignored, and the body is qualified again. URL format fitness is computed only from verified fields plus the captured Content-Type and URLs. A stored `url_qualified` may lower that result but never raise it. Capture calls `qualify()` for every PDF body; its own cache keys on body, implementation and config. Retryable checker failures never install suppression validators.
- **Validators bind to the resource that answered.** A body-less 304 or `unchanged` recheck keeps the earlier validators and verdict. Matching `Content-Length` alone never suppresses a response; `ETag` or `Last-Modified` is required.
- **Restart.** Each operation's atomic `committed.json` is folded back into the indexes on startup, and a torn last line in `qualifications.jsonl` is skipped. Journal replay checks each hop's own binding, so a hop sealed before validators existed resumes without a second call.
- **One rule across inventory and URL state.** In inventory, the newest body-bearing row decides: an older healthy 200 cannot keep `usable_direct` after a newer failed body. URL-state SQL expects a PDF from the requested or final URL spelling or the captured media type, which is the same rule capture applies.
- **Readability never settles identity.** URL state no longer marks a readable body `satisfied`/`qualified_direct_body`. Only a failed body changes the reason, to `body_not_qualified`; a healthy target keeps its ordinary reason under both refresh policies. `campaign.py` drops the `qualified_direct_body` branch.
- **`good-fetches.sql`** excludes body-less `unchanged` rows (`outcome='unchanged' AND sha256 IS NULL`). Such a recheck advances `next_attempt_at` but not `last_good_at`. The release gate's `url_state_proof` reads the same model step, so the two stay consistent. On the 2026-11-12 lake captures head (4,180,710 rows), this excludes 0 existing rows: no published value moves.
- **Empty-input parity is tested.** With no qualification facts, URL-state output equals the step without qualifications, so production releases are unchanged until a ledger is pinned.

Remaining before closing `ct-zohj` (owner decisions & workflow enablement):
1. **Durable ledger, publication handoff, release gate & discovery consumer are now wired in code (`2026-11-19T13:38:00Z`):**
   - `qualification_facts.py` (`import_qualifications`, `load_store_qualifications`, `retry_retained_qualifications`), `capture_scheduler.py` (`qualification_store`), and `cli/capture_schedule.py` persist verified receipt-bound qualification records create-only under `provenance/qualifications/<timestamp>-<sha256>.jsonl` in `BodyStore` (both `LocalAdapter` and `R2Adapter`, listing only `provenance/qualifications/`) so qualifications survive ephemeral `$RUNNER_TEMP` runners across nights, and retry transient (`retryable=True`) checker failures directly against retained store bytes before network rechecks (`qualification_metrics.{elapsed_seconds,cache_hits,retried,provenance_key}`).
   - `archive_model_job.PROVENANCE` adds `'qualification_files': 'qualifications'`, so `produce_daily_inputs` (`archive_publish_job.py`) automatically discovers, MD5/SHA-256-verifies, and binds `provenance/qualifications/*.jsonl` from R2 into daily candidate builds without manual `publish-model.json` edits; `archive_model_profile.py` and `archive_model.py` keep physical qualification selectors in `snapshots` outside semantic `profile_sha256` (`data_only_night.SAME_INPUTS` profile equality preserved).
   - `release_gate.py` (`URL_STATE_COLUMNS`, `capture_job`, `url_state_proof`, `_url_state_rules`), `archive_controller.py`, and `archive_publish.py` verify qualification-driven `capture_reason` transitions (`no_satisfying_recovery <-> body_not_qualified` on `eligible` rows) against the candidate's captures and verified `qualification_files`, refusing unproven or forged transitions (`qualified_recovery`, `capture_disposition` changes, or missing qualification proof).
   - `corpus_recovery/inventory.py` and `corpus_recovery/pipeline.py` (`run_recovery_campaign`) automatically load `provenance/qualifications/*.jsonl` from `store`/`source_or_store` and derive `body_not_qualified` targets from `url_state.parquet` / durable store qualifications when `targets=None`.
   - End-to-end boundary test (`test_two_fresh_work_dirs_across_publication_boundary_and_discovery` in `test_normalized_pipeline.py` + `test_durable_store_qualifications_survive_fresh_work_dirs_and_retry_transient_failures` in `test_capture_qualification_routing.py` + `test_release_gate_url_state_proof_admits_verified_qualification_reason_and_refuses_unproven` in `test_recovery_eligibility.py`) exercises fresh capture work directories across the publication and discovery boundaries: broken HTTP-200 capture -> durable `provenance/qualifications/` -> `url_state` `eligible/body_not_qualified` -> automatic discovery consumer (`1` Wayback lookup) -> fresh-work-dir `304 Not Modified` advancing only `attempts`/`last_attempt`/`next_attempt_at` (preserving `last_good_at`) -> changed-`ETag` readable replacement PDF qualified (`elapsed_seconds` & `cache_hits` recorded) while leaving the `historical_exact` requirement open (`eligible/no_satisfying_recovery`).
2. **Owner sign-off & scheduled discovery job (`ct-zohj.md:22`):** Ticket remains `in_progress` pending owner sign-off on the two policy questions above (where readability checks run / nightly cost ceiling and validator replacement policy, plus adopting the new `provenance/qualifications/` R2 family in live runs) and adding a scheduled `run_recovery_campaign` workflow step so discovery runs unattended in GitHub Actions without manual invocation.
