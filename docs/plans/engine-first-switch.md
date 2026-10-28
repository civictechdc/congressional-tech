# Engine-first switch

The switch is **blocked: owner**. This checklist prepares the change; it does not authorize a live run. Keep the old capture and its imported code until the final ingest and first publication succeed. Phase-2 meeting, witness and entity migrations remain separate.

1. Finish raw safety in the order recorded by `release/m1-smoke`'s `owner-raw-safety.md`: rescue import and weekly raw token; disposable-bucket lock probe; bodies and provenance locks; patched old writers drained; B0 rewrite and five checks; receipts lock; dedicated Basin smoke. Managed Basin maintenance stays off.
2. Accept the full narrow D1 comparison and E4 comparison against the pinned old catalogs. The owner must decide each fact present only in derived tables. Complete current-version D2 and D3 backfills, the maintained-lake versus clean-rebuild byte comparison, and C6's full graph and join measurements within the 4-CPU/16-GB runner. A partial slice does not meet these gates.
3. Install the approved Linux runtime artifact and role-specific secrets through the existing environment bindings. Run the site speed harness on real devices and commit the approved targets. Install active publish, backfill and maintenance specs only after their dry runs pass. Pending specs deliberately refuse:

   ```sh
   .venv/bin/python -I .github/scripts/run-archive-job.py publish --check-binding
   .venv/bin/python -I .github/scripts/run-archive-job.py backfill --check-binding
   .venv/bin/python -I .github/scripts/run-archive-job.py maintenance --check-binding
   ```

4. The owner disables the old capture workflows, waits for in-flight writers to drain and preserves their final receipt inventory. Leave the weekly meeting inventory job enabled until B14. Run the final ingest and publish through the one controller:

   ```sh
   .venv/bin/python -I .github/scripts/run-archive-job.py publish
   ```

   Its local reader test precedes release upload, its HTTPS canary precedes the conditional pointer write, and a failed canary or pointer race preserves the outgoing pointer. Record the old pointer and ETag, the accepted new release, input record, receipt-key list and status result. An equal content ID records its new input identity without a flip.
5. Run the new capture once against the new live `url_state`, capture scope and URL profile, with the approved request, byte and spool budgets. Use the command already bound by `.github/workflows/capture-archive.yml`. Verify every creating line's suffix and stored MD5 against its acknowledged ETag. Confirm that each cut-off URL has a complete copy or a recorded reason, and that capture performs no old-index read.
6. Re-run the reader, canary and browser test on that release. Confirm the live and previous releases both exist and their complete input records retain all receipt lists. Rollback uses the same conditional pointer writer with the observed current ETag; never overwrite a pointer unconditionally or rewrite release assets. Resume old capture only by an explicit owner decision, preserving every new receipt.
7. Regenerate F5's committed-source inventory after final integration. Resolve its manual ranges, branch splits and external consumers before preparing each deletion commit. Keep the reader, raw writer and parked consumers identified by BIND §6. Prepare one commit per group with measured `wc -l` before and after; apply them only after the switch evidence above passes:

   ```sh
   .venv/bin/python -I scripts/measure/cxb_switch_deletions.py --ct "$PWD" --ds /Users/mikewolfd/Work/wt/ds-engine-first --out "$RAW_SCRATCH/cxb_switch_deletions.final.json"
   .venv/bin/python -I scripts/measure/cxb_switch_deletions.py --ct "$PWD" --ds /Users/mikewolfd/Work/wt/ds-engine-first --verify "$RAW_SCRATCH/cxb_switch_deletions.final.json"
   ```

   The inventory is preparation evidence, not proof that a shared function is unused. Run the surviving focused tests and the full regression after each applied deletion group. Do not remove the old explorer or weekly meeting tables before their phase-2 consumers move.

No workflow was disabled, live job run, pointer flipped or imported source deleted while preparing this checklist.
