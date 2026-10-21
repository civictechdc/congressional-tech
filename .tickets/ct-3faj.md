---
id: ct-3faj
status: closed
deps: [ct-copj]
links: [ct-q968, ct-egpe, ct-bt1q, ct-m9td, ct-qdkd, ct-nc7l, ct-a70m]
created: 2026-10-20T18:50:27Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, recovery]
---
# Retain producer inputs after an indeterminate native request

An HTTP timeout or abnormal worker failure can return while the native owner is still admitting producer Parquet or holding background blocking/SQLite effects. Deleting the temporary file at caller exit can break that admitted work. Retain unknown-outcome inputs and expose their location and byte cost until native state proves safe release.

## Acceptance Criteria

- In `packages/congress_api/src/congress_api/retention/docspec.py:232-251` (`NativeDatasets.run_table`) and `docspec-rs/src/engine/http.rs:442-454`, do not treat HTTP 422 `"worker"` (or quarantined-custody) responses as proof that the producer file is unreferenced. Only deterministic pre-execution/validation refusals where native custody remains intact may unlink `request-*/source.parquet`.
- Tests in `tests/test_docspec_input_custody.py` cover timeout before and after admission, `"worker"` / quarantined error responses, retained source after host exit, exact retry identity (`request.json` + `source.parquet`), and cleanup after definitive refusal or successful completion.
- No automatic retry, success cache, guessed admission, secret logging, or automatic deletion of unknown inputs.

## Notes

**2026-10-20T19:58:41Z**

Transport author source-review finding for independent acceptance: c44bf044 run_table treats every native HTTP status except504 as definitive cleanup-safe refusal. Native Error maps JoinError to code worker; HttpError defaults worker to422. Engine worker Custody::drop explicitly quarantines the host after abnormal task loss because blocking/SQLite effects may still be alive. Therefore HTTP422 alone does not prove producer independence. Review conservative retention or explicit native refusal/admission proof before accepting ct-3faj. This is a source-traced risk, not a reproduced producer-loss test. No producer cleanup change made in ct-bt1q, per its narrow scope.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit confirmed this P2 custody hole at `docspec.py:233-235` and `docspec-rs/src/engine/http.rs:442-454`. Map native `"worker"` / quarantine errors to a non-cleanup-safe status (e.g. 500/503 or explicit error-code check in `run_table`) and add a custody regression test before closing `ct-3faj` and `ct-q968`.
