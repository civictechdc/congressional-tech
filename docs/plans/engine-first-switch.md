# Engine-first switch

The lead performs every live step. The first publication is a display-only conversion of the pinned v5 catalog; the raw rebuild replaces it only after its own acceptance checks. Keep old capture, update and imported code through the seed publication. Phase-2 meeting, witness and entity migrations remain separate.

## First publication: v5 seed

1. Accept the seed produced by `model/jobs/seed-v5.json` from the four approved, SHA-256-pinned inputs: documents, filenames, old-index captures and accepted recoveries. Require real DM identities, required-field checks, listed plus reasoned exclusions equal to all input documents, and fifty source comparisons of filename, format, source page and meeting. Missing recovery import dates remain null. The input record, status and canary must identify `seed: v5 catalog 596f08fa`; receipts, provenance and lake selectors remain empty because this is a seed.
2. The lead records workflow and Pages states, pauses Pages and every old publisher, and drains their queued, in-progress and waiting runs before the main change. Identify and drain local v6 publishers using the PID-only check below and owned-run records. Preserve old capture and update workflows; their acquired raw data remains the rebuild's input. Every R2 writer shares `raw-source-mirror` with `queue: max`.
3. Use release's ordered window to install the approved Linux runtime, merge the prepared landing, and set its runtime variable and public account variable. All six hosted shards must finish within budget, and the retained failure identities must equal the pinned 36-identity baseline in both directions with zero new failures. Report this as **red on the 36 pre-existing baseline failures, no new failures**. Do not skip, allowlist or weaken tests. Keep Pages paused while this evidence is collected.
4. With the reviewed seed spec bound to the existing publish job, the lead runs `.venv/bin/python -I .github/scripts/run-archive-job.py publish`. The local reader gate precedes upload; the HTTPS canary precedes the conditional pointer write. Retain the outgoing pointer and ETag, complete seed input record, empty canonical receipt list and status. Qualify desktop, phone and 404 behavior on that exact release.
5. The lead restores Pages and deploys the explorer after the accepted seed pointer flip. Verify the live reader and canary, preserve the old pointer for the paired rollback, and keep old capture and update running. New capture must refuse seed metadata before reading scheduler inputs. Leave automatic archive publication and new capture disabled until the rebuild switch. No F5 deletion occurs at this stage.

## Second publication: accepted raw rebuild

1. Finish raw safety in the order recorded by `release/m1-smoke`'s `owner-raw-safety.md`: rescue import and weekly raw token; disposable-bucket lock probe; bodies and provenance locks; patched old writers drained; B0 rewrite and five checks; receipts lock; dedicated Basin smoke. Managed Basin maintenance stays off.
2. Accept the full narrow D1 comparison and E4 comparison against the pinned old catalogs. The owner must decide each fact present only in derived tables. Complete current-version D2 and D3 backfills, the maintained-lake versus clean-rebuild byte comparison, and C6's full graph and join measurements within the 4-CPU/16-GB runner. A partial slice does not meet these gates.
3. At the rebuild switch, the lead records the enabled states of Pages, `publish-explorer` and the old publish, update and capture workflows, then pauses them and waits until no relevant queued, in-progress or waiting runs remain. Disabling a workflow does not drain its existing runs; never automatically cancel a job that may hold acquired data. A main push changing `apps/site` and `congress_shared` otherwise triggers Pages before publication. Keep Pages paused through runtime CI and the pointer flip. Leave the weekly meeting inventory job enabled until B14.

   Confirm that no local v6 publish is running, using the lead's owned-run records and a PID-only check of its known entry points:

   ```sh
   pgrep -f 'publish-filename-viewer[.]py|viewer_publication[.]publish_filename_viewer'
   ```

   Any matching PID must be identified and drained before the switch. Preserve acquired data and preparation checkpoints; never automatically kill an unknown or acquiring process. Workflow pauses do not stop a local publisher. Every R2-writing workflow must use the shared `raw-source-mirror` lock with `queue: max`.

   Install the approved Linux runtime artifact and role-specific secrets through the existing environment bindings. Bind the public `CLOUDFLARE_ACCOUNT_ID` repository variable to `174055408ff1560e60601c4d12c561c4` before remote archive jobs; `archive-jobs.yml` reads this variable. Run the site speed harness on real devices and commit the approved targets. Install active publish, backfill and maintenance specs only after their dry runs pass. Pending specs deliberately refuse:

   ```sh
   .venv/bin/python -I .github/scripts/run-archive-job.py publish --check-binding
   .venv/bin/python -I .github/scripts/run-archive-job.py backfill --check-binding
   .venv/bin/python -I .github/scripts/run-archive-job.py maintenance --check-binding
   ```

4. The lead confirms the paused old writers remain drained and preserves their final receipt inventory. Run the final ingest and publish through the one controller:

   ```sh
   .venv/bin/python -I .github/scripts/run-archive-job.py publish
   ```

   Its local reader test precedes release upload, its HTTPS canary precedes the conditional pointer write, and a failed canary or pointer race preserves the outgoing pointer. Record the old pointer and ETag, the accepted new release, input record, receipt-key list and status result. An equal content ID records its new input identity without a flip.
5. Run the new capture once against the new live `url_state`, capture scope and URL profile, with the approved request, byte and spool budgets. Use the command already bound by `.github/workflows/capture-archive.yml`. Verify every creating line's suffix and stored MD5 against its acknowledged ETag. Confirm that each cut-off URL has a complete copy or a recorded reason, and that capture performs no old-index read.
6. After the qualified model, E4 comparison, canary and pointer flip pass, the lead restores Pages to its recorded state and deploys the explorer. Re-run the reader, canary and browser test on that release. Confirm the live and previous releases both exist and their complete input records retain all receipt lists. Restore other workflows selectively according to the new job bindings; leave replaced writers paused. Rollback uses the same conditional pointer writer with the observed current ETag; never overwrite a pointer unconditionally or rewrite release assets. Resume old capture only by an explicit owner decision, preserving every new receipt.
7. Regenerate F5's committed-source inventory after final integration. Resolve its manual ranges, branch splits and external consumers before preparing each deletion commit. Keep the reader, raw writer and parked consumers identified by BIND §6. Prepare one commit per group with measured `wc -l` before and after; apply them only after the switch evidence above passes:

   ```sh
   .venv/bin/python -I scripts/measure/cxb_switch_deletions.py --ct "$PWD" --ds /Users/mikewolfd/Work/wt/ds-engine-first --out "$RAW_SCRATCH/cxb_switch_deletions.final.json"
   .venv/bin/python -I scripts/measure/cxb_switch_deletions.py --ct "$PWD" --ds /Users/mikewolfd/Work/wt/ds-engine-first --verify "$RAW_SCRATCH/cxb_switch_deletions.final.json"
   ```

   The inventory is preparation evidence, not proof that a shared function is unused. Run the surviving focused tests and the full regression after each applied deletion group. Do not remove the old explorer or weekly meeting tables before their phase-2 consumers move.

No workflow was disabled, live job run, pointer flipped or imported source deleted while preparing this checklist.
