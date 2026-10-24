---
id: ct-qqk2
status: open
deps: [ct-syx8, ct-st8m]
links: [ct-2yl5, ct-o24q, ct-wxhg, ct-unv0, ct-1dsp, ct-1mbc, ct-atjy, ct-idhg, ct-hm4b, ct-v6ao, ct-30pw, ct-5jqd, ct-2ut4, ct-76n5, ct-bpyj, ct-h73z, ct-piku, ct-zkzt, ct-m59w, ct-zb9y]
created: 2026-10-24T18:15:54Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-98sm
---
# WS6: finish export-pins and delete the journal and resume route

Owner decision 3: `export-pins` becomes the only publication route. Today its pointer names a manifest that is never uploaded, release keys are a placeholder, a 412 counts as success, its writes bypass the key policy, its reader branch lacks five fields, and no workflow runs it.

First move, safe either way: delete the resume axis (`resume.py`, `prepare_workflow_resume.py`, `describe-attempt` and `--resume-descriptor`, the workflow's resume inputs and steps, and `test_workflow_resume.py`, red on main since `fb9ed402`).

Then: content-addressed release ids with a single `IfMatch` pointer flip; 412s go through WS2's verifier; all writes go through WS2's policy; reader parity; move the recovery index and mapping into the same flow once `accepted.json` is reconciled; one job triggered on capture completion and push, dropping the cron and the stdlib preflight. Under the engine-first rule, prefer the engine export path (`filename_exports.py:763-818`) when the two `export_viewer_pins` paths are timed on the real catalog.

## Acceptance Criteria

Contract tests ported from `test_viewer_publication_attempt.py` before it is deleted:
- The pointer advances only after every release object is uploaded and verified.
- A second concurrent publisher loses the pointer compare-and-swap, and the old pointer stays.
- Every writer refuses `bodies/`, `receipts/` and `indexes/raw.json`.
- A 412 on an immutable asset holding different bytes fails.
- A mapping `IfMatch` conflict is refused (keep `test_publish_corpus_recovery_mappings.py:186-270`).
- The fake-module assertion at `.github/tests/test_viewer_r2.py:46` is replaced with a behavioral check.
- End to end: the custom-domain `manifest.json` returns 200 and the site loads.
- R-check 1-3 pass.


## Notes

**2026-10-24T18:47:53Z**

Efficiency pass E6. (1) Upload exactly the pin set the engine returns, addressed by each file's own digest: today it omits document_occurrences.parquet and manifest.json (publication_cli.py:162,169) and uploads nothing in engine mode. (2) Send Content-MD5 and sha256 metadata; reuse the export's digests instead of re-hashing (client.py:327-342). (3) Advance the pointer with IfMatch, since today it is create-only and a second publish fails. (4) Derive the operation id from the source release plus the spec digest, replacing the placeholder exp-sources-v-export-01 (filename_exports.py:745,766). (5) Delete the local Python export path after a parity test, with no timing run (decision 6).
