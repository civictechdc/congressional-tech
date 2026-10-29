# Corpus recovery commands

Some committee documents never landed in the raw archive, or landed only as an error page. **Corpus recovery** is the path that adds a checked copy of those documents later.

A recovered file is not imported because a script downloaded it. Each command writes a local folder whose inputs are named and hashed (a **sealed batch**). The next command refuses to run if those bytes changed. Import defaults to a check. They write to Cloudflare R2 only when you pass `--execute`.

Library code for assembly, transfer, and the write guards is in [`packages/corpus_recovery`](../../packages/corpus_recovery/README.md). Run these commands from the repository root with the locked environment.

## Order of work

1. **`prepare_corpus_recovery_batch.py`** copies one recovery result into a new local batch. It checks body hashes and sizes, ZIP membership, and deferred URLs that must stay out. It does not upload. Use a new destination for each checkpoint. Do not overwrite a batch you already sealed.

   For a GovInfo recovery with `package_id`, `archive_member`, and `request_evidence`, it retains the downloaded ZIP, every extracted member (including metadata), and the exact acquisition receipt. It checks the receipt and local files against the ZIP once per acquisition, even when several recovery targets use the same package. An incomplete package fails preparation. Existing retained-body recoveries without a local package still work without another download. The selected PDF or XML keeps its original recovery mapping; sibling files do not inherit that mapping.

2. **`prepare_corpus_recovery_source_records.py`** adds source-record files to that sealed batch, using timestamps that were retained with the capture. It does not replace the manifest or files that are already there. If a previous run stopped halfway, copy the batch and start this step again. This command does not resume an interrupted pair.

3. **`coalesce_corpus_recovery_batches.py`** combines finished batches into one import unit. It changes the mapping baseline only for URL and body pairs that these batches newly recovered. It leaves the original batches in place and does not talk to the network.

4. **`reconcile_corpus_recovery_bodies.py`** compares the sealed batch with document objects already in storage. It only reads. The report says which bodies are already present, which are missing, and which disagree.

5. **`dispatch_corpus_recovery_import.py`** checks the sealed inputs, the reconciliation report, and that no other cloud writer holds the archive. With `--execute`, it stores the new document bytes and updates the raw indexes under a conditional write. Without `--execute`, it stops after the checks. Do not reuse a destination after a failed import; start a new one.

6. **`run_corpus_recovery.py`** is a local supervisor for one of the commands above. It records the child process, its logs, and the exit code it actually waited for. A missing process is not success. Resume is a separate, explicit command. The supervisor does not decide whether a remote write landed; the import command does that.

Accepted recovery labels now enter raw as records in `recoveries/accepted.json`.
The archive model and publisher consume them. The old catalog/viewer publication
dispatcher is retired.

## What a sealed batch protects

Later steps trust the batch only when every named file still matches the manifest hash. That is what stops a retry from importing a different PDF than the one you reviewed. The commands do not delete the previous batch when you make a new one.

Local publication recovery uses the synced `events.jsonl`, including accepted phase
checkpoints. New attempts do not write a duplicate `continuation.json`. Resume and
status inspection read the event history; older derived checkpoints are ignored
when that history is present. Pass `events.jsonl` to `pipeline_status.py --continuation`
when inspecting a local attempt.
