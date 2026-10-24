---
id: ct-syx8
status: open
deps: [ct-snzi]
links: [ct-te1p, ct-a70m, ct-dmca, ct-ec91, ct-aia9, ct-8v02, ct-4t6s, ct-1dsp, ct-fw0m, ct-1l1h, ct-snzi]
created: 2026-10-24T18:15:53Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-98sm
---
# WS2: one owner for raw write rules

Raw write rules are scattered: five write entry points each take an `immutable` flag, a 412 counts as success without a byte check, collision checks are copied three times and missing for PDFs, ingest flags are probed in 7 files, and verification reads can come from a local cache (audit hotspot 2; raw risks 1, 4 and 5).

First move (P1 is done in `54a68ac7`): add a parametrized test over {`put`, `put_file`, `put_pdf_body`, `AsyncBodies.put`, `LocalStore.put`, `GuardedPublicationClient.put_object`} x {`bodies/`, `receipts/`, `quarantine/`, `indexes/raw.json`}. It asserts that a write that is not create-only is refused before any I/O and that no unconditional `put_object` is sent. It characterizes today's behavior.

Then the plan's steps: one namespace-policy function; one verifier for existing objects; ingest policy set once at store construction; verification reads skip the local cache; fold `migrate_pdf_bodies_to_uncompressed` into `backfill_uncompressed_pdfs`; read-time fill for raw-state fields; `VerifiedFile` hashes or refuses; hand-written body writers call `physical_body_object_key`/`put_body`.

Owner decisions applied: delete the exclusion-list hook entirely (`raw_storage.py:75-236`, 162 lines). Under the engine-first rule, step 6 deletes the whole Python retention planner (`plan_protected_retention` and the retention-plan CLI mode) and relies on engine retention, rather than only its reclaim branch (ct-a70m). Still open: whether `.pdf` siblings are written always or never (plan open question 5).

## Acceptance Criteria

- The refusal matrix lands first and passes.
- A test that a PDF collision with different bytes fails lands before the verifier, in its own PR, with `test_r2_archive_store.py:84-105`, `test_r2_body_files.py:50-63` and `test_async_capture_native.py:261` updated deliberately.
- A guard test that no Python path calls `/retention/removal/execute` or deletes under raw prefixes lands before the planner is deleted (it passes today).
- `VerifiedFile(p, wrong_sha, size).require(p)` raises.
- A one-time read-only check for `.pdf` keys in the raw-bodies routing index written between Oct 22 20:16 and Oct 23 18:44 is recorded.
- R-check 1-4 pass, plus the refusal matrix.


## Notes

**2026-10-24T18:47:53Z**

Efficiency pass children: ct-klql (verify each raw upload once), ct-allr (body existence by key), ct-i5g2 (small cleanups). Owner answer: delete the exclusion-list hook entirely (no list will exist).
