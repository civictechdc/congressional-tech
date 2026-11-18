# Corpus recovery commands

Some committee documents never landed in the raw archive, or landed only as an error page. **Corpus recovery** is the path that adds a checked copy of those documents later.

A recovered file is not imported because a script downloaded it. Each command writes a local folder whose inputs are named and hashed (a **sealed batch**). The next command refuses to run if those bytes changed. Import defaults to a check. They write to Cloudflare R2 only when you pass `--execute`.

Library code for assembly, transfer, and the write guards is in [`packages/corpus_recovery`](../../packages/corpus_recovery/README.md). Run these commands from the repository root with the locked environment.

## Known invalid sources

Before planning follow-up recovery, read the [current invalid-source inventory
manifest](../../docs/plans/ocr-source-recovery-inventory.json). It points to the
durable per-source worklist, evidence and latest fetch outcomes. Keep rows with
`recovery_open=true` in follow-up planning even when capture history says HTTP
200, `complete=true` or `outcome=stored`. Those fields describe the transfer;
they do not establish that the requested document was recovered.

Resolve missing URL/history mappings and review existing alternatives first.
Use the normal capture scope and resource checks for each new request, with
backoff for repeated failures. Close an invalid-source record only after a usable
replacement or explicitly accepted scoped coverage is linked to the intended
document/revision. Preserve the original and every failed attempt. This worklist
does not itself dispatch requests or change the automatic scheduler.

## Order of work

1. **`prepare_corpus_recovery_batch.py`** copies one recovery result into a new local batch. It checks body hashes and sizes, ZIP membership, and deferred URLs that must stay out. It does not upload. Use a new destination for each checkpoint. Do not overwrite a batch you already sealed.

   For a GovInfo recovery with `package_id`, `archive_member`, and `request_evidence`, it retains the downloaded ZIP, every extracted member (including metadata), and the exact acquisition receipt. It checks the receipt and local files against the ZIP once per acquisition, even when several recovery targets use the same package. An incomplete package fails preparation. Existing retained-body recoveries without a local package still work without another download. The selected PDF or XML keeps its original recovery mapping; sibling files do not inherit that mapping.

2. **`prepare_corpus_recovery_source_records.py`** adds source-record files to that sealed batch, using timestamps that were retained with the capture. It does not replace the manifest or files that are already there. If a previous run stopped halfway, copy the batch and start this step again. This command does not resume an interrupted pair.

3. **`coalesce_corpus_recovery_batches.py`** combines finished batches into one import unit. It changes the mapping baseline only for URL and body pairs that these batches newly recovered. It leaves the original batches in place and does not talk to the network.

4. **`reconcile_corpus_recovery_bodies.py`** compares the sealed batch with document objects already in storage. It only reads. The report says which bodies are already present, which are missing, and which disagree.

5. **`run_corpus_recovery.py`** is a local supervisor for one of the commands above. It records the child process, its logs, and the exit code it actually waited for. A missing process is not success. Resume is a separate, explicit command.

6. **`browser_session_capture.py`** bridges interactive browser-only origins (such as `webarchive.loc.gov` when an automated client hits an edge challenge) without changing pipeline custody or receipt rules. `emit-snippet` generates a same-origin DevTools snippet using `window.showDirectoryPicker` at 15-second pacing with hard stop on `429`/`403`/`cf-mitigated`; `ingest` verifies captured `<sha256>.pdf` bytes, writes standard `ReceiptWriter` receipts (`transport='browser_same_origin'`), enforces `acceptance.receipt_binding`, and qualifies every PDF locally before capture integration.

Accepted recovery labels now enter raw through provenance staging and the common
receipt writer (`corpus_recovery.reconcile`). The archive model and publisher
consume them; the old shared-index import and catalog/viewer publication
dispatchers are retired.

## What a sealed batch protects

Later steps trust the batch only when every named file still matches the manifest hash. That is what stops a retry from importing a different PDF than the one you reviewed. The commands do not delete the previous batch when you make a new one.

Local publication recovery uses the synced `events.jsonl`, including accepted phase
checkpoints. New attempts do not write a duplicate `continuation.json`. Resume and
status inspection read the event history; older derived checkpoints are ignored
when that history is present. Pass `events.jsonl` to `pipeline_status.py --continuation`
when inspecting a local attempt.
