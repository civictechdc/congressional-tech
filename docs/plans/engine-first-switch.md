# Engine-first switch

The lead performs every live step. The first publication is a display-only conversion of the pinned v5 catalog; the raw rebuild replaces it only after its own acceptance checks. Keep old capture, update and every shared path they use through the seed publication. Retire only superseded congressional-tech code after the lead confirms deployment and the deletion checks pass. Phase-2 meeting, witness and entity migrations remain separate.

## First publication: v5 seed

1. Accept the seed produced by `model/jobs/seed-v5.json` from the four approved, SHA-256-pinned inputs: documents, filenames, old-index captures and accepted recoveries. Require real DM identities, required-field checks, listed plus reasoned exclusions equal to all input documents, and fifty source comparisons of filename, format, source page and meeting. Missing recovery import dates remain null. The input record, status and canary must identify `seed: v5 catalog 596f08fa`; receipts, provenance and lake selectors remain empty because this is a seed.
2. The lead records workflow and Pages states, pauses Pages and every old publisher, and drains their queued, in-progress and waiting runs before the main change. Identify and drain local v6 publishers using the PID-only check below and owned-run records. Pause and drain old capture and update during blocks A through B without canceling jobs that may hold acquired data; preserve their workflows and raw data for resumption after the seed. Every R2 writer shares `raw-source-mirror` with `queue: max`.
3. Use release's ordered window to install the approved Linux runtime, merge the prepared landing, and set its runtime variable and public account variable. The gate is the local full `production-offline` run on the final frozen landing, with both `DOCSPEC_BINARY` and `DOCSPEC_JOB_CONFIG` explicitly selecting `885e8c3`. Compare failures against integration in that same environment: zero landing-only failures. The historical 36-identity baseline, taken without the optional native tests enabled, is not an allowance for this environment. Retain both comparisons and the actual remaining failures; do not skip or weaken checks. Hosted validation is informational and its runtime-budget fixes are CI follow-up work. Keep Pages paused through acceptance. Staying on 885 requires core's plan-level audit to find no silent DISTINCT/USING trigger in the seed and the paths it uses; otherwise stop and qualify the corrected runtime before proceeding.
4. Measure the actual seed built from the final merged definitions with the existing Chromium harness: five Moto G Power-class phone runs at 4× page CPU slowdown and slow 4G, and five desktop runs without throttling. Record that the worker CPU is unthrottled. Set each ceiling to the rounded-up median times 1.5; retain `basis: "emulated"`, profiles, harness commit and raw runs with `status: "provisional-emulated"`. Both publisher and canary accept these targets only for a display-only `seed_v5` origin. The raw rebuild requires real-device `owner-approved` targets. The lead runs the existing controller locally: `.venv/bin/python -I -m viewer_publication.archive_publish_job --spec "$WINDOW/accepted-publish-spec.json" --execute`. Do not dispatch a hosted seed publication. The pinned spec, measured targets and accepted manifest identify the same candidate; current definition custody remains part of its input record. The local reader gate precedes upload; the HTTPS canary precedes the conditional pointer write. Retain the landed application revision, spec and manifest hashes, local command result, controller work directory, outgoing pointer and ETag, complete seed input record, empty canonical receipt list and status. Qualify desktop, phone and 404 behavior on that exact release.
5. The lead restores Pages and deploys the explorer after the accepted seed pointer flip. Verify the live reader and canary, preserve the old pointer for the paired rollback, and keep old capture and update running. New capture must refuse seed metadata before reading scheduler inputs. Leave automatic archive publication and new capture disabled until the rebuild switch. After the lead confirms deployment, reviewed F5 groups may remove superseded congressional-tech paths with named live replacements. For G06 the replacement is `viewer_publication.archive_publish_job`; for G12 it is the labeled raw recovery records read by the model and publisher; for G13 it is the archive release files. Rollback restores the previous application from git history. Preserve the namespace firewall, shared constants, raw continuation and journal code, local guards and admission, raw writers, binding APIs and parked consumers. Test-only callers do not keep a retired path alive.

## Second publication: accepted raw rebuild

1. Finish raw safety in the order recorded by `release/m1-smoke`'s `owner-raw-safety.md`: rescue import and weekly raw token; disposable-bucket lock probe; bodies and provenance locks; patched old writers drained; B0 rewrite and five checks; receipts lock; dedicated Basin smoke. Managed Basin maintenance stays off.
2. Accept the full narrow D1 comparison and E4 comparison against the pinned old catalogs. The owner must decide each fact present only in derived tables. Complete current-version D2 and D3 backfills, the maintained-lake versus clean-rebuild byte comparison, and C6's full graph and join measurements within the 4-CPU/16-GB runner. A partial slice does not meet these gates.
3. At the rebuild switch, the lead records the enabled states of Pages, `publish-explorer` and the old publish, update and capture workflows, then pauses them and waits until no relevant queued, in-progress or waiting runs remain. Disabling a workflow does not drain its existing runs; never automatically cancel a job that may hold acquired data. A main push changing `apps/site` and `congress_shared` otherwise triggers Pages before publication. Keep Pages paused through runtime CI and the pointer flip. Leave the weekly meeting inventory job enabled until B14.

   Confirm that no local v6 publish is running, using the lead's owned-run records and a PID-only check of its known entry points:

   ```sh
   pgrep -f 'publish-filename-viewer[.]py|viewer_publication[.]publish_filename_viewer'
   ```

   Any matching PID must be identified and drained before the switch. Preserve acquired data and preparation checkpoints; never automatically kill an unknown or acquiring process. Workflow pauses do not stop a local publisher. Every R2-writing workflow must use the shared `raw-source-mirror` lock with `queue: max`.

   Qualify and install the corrected runtime (`729eb8d`, including the DISTINCT/USING fix and measured-allocation JSON reader, or its accepted successor) for both the application and Linux artifact before the raw release and before enabling any daily or new-capture job. Local rebuild jobs use its qualified Darwin snapshot. Install role-specific secrets through the existing environment bindings. Bind the public `CLOUDFLARE_ACCOUNT_ID` repository variable to `174055408ff1560e60601c4d12c561c4` before remote archive jobs; `archive-jobs.yml` reads this variable. Run the site speed harness on real devices and commit the approved targets. Install active publish, backfill and maintenance specs only after their dry runs pass. Pending specs deliberately refuse:

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
7. Regenerate F5's committed-source inventory after final integration. Its scope is the 18 congressional-tech groups that duplicate or are superseded by a named live replacement; docspec-rs deletion is outside this switch. Resolve manual ranges, branch splits and actual production imports, workflows and external consumers before each deletion commit. Tests, old-only fixtures and measurement tools do not count as production users; migrate any kept production caller first. Keep the reader, raw writer and parked consumers identified by BIND §6, including news, committee and weekly meeting consumers and every client API they call. Prepare one commit per group with measured `wc -l` before and after. Apply the independently accepted seed-deployment groups under the gate above; apply remaining groups only after their replacement's switch evidence passes:

   ```sh
   .venv/bin/python -I scripts/measure/cxb_switch_deletions.py --ct "$PWD" --ds /Users/mikewolfd/Work/wt/ds-engine-first --out "$RAW_SCRATCH/cxb_switch_deletions.final.json"
   .venv/bin/python -I scripts/measure/cxb_switch_deletions.py --ct "$PWD" --ds /Users/mikewolfd/Work/wt/ds-engine-first --verify "$RAW_SCRATCH/cxb_switch_deletions.final.json"
   ```

   The inventory is preparation evidence, not proof that a shared function is unused. Run focused checks per group, prove no production imports or workflows refer to removed paths, and run one full regression on the combined strip branch before merging. The lead must confirm deployment before any strip merge. Do not remove the old explorer or weekly meeting tables before their phase-2 consumers move. This is temporary retention, not permission to keep a second publication indefinitely.

## Remaining phase-2 Explorer switch — 2026-10-30

The archive deletion work already recorded in `ct-5kto` remains valid historical
evidence. It does not close the following remaining sequence:

1. `ct-gi01`: complete the field inventory and mappings in
   [PHASE-2 §4.6](phase-2-annex-20261028.md#46-explorer-migration-and-data-coverage),
   preserve legacy-only evidence, and produce the shared native release from
   pinned lake/reference inputs through the actual production job configuration.
2. `ct-t915`: make `/archive/` and `/dashboard/` use that release. Redirect or
   replace the dashboard, or retain only Coverage/Gaps backed by the same release.
3. `ct-m104`: verify producer-to-site/MCP parity and real release discovery/query
   results. `ct-082q` and its children supply their selected HTML metadata; do not
   introduce a second publisher or MCP-owned data model.
4. `cef-96wc`: record the production release, workflow bindings, successful live
   reads and rollback references under the existing operational gates.
5. `ct-5kto`: retire the old Explorer publishing route, old pointer consumption
   and `pipeline-data/committee-explorer/public` staging in both workflows.
   Preserve raw inputs and evidence; verify the replacement after retirement.

Close `ct-77zb`, `ct-98sm` and `ct-8kl2` only when their remaining criteria and
children are satisfied. Closed superseded mirror/engine tickets are historical
context, not evidence that these steps ran. This reconciliation changes planning
and ticket state; it does not execute a publication or enable a scheduled job.

No workflow was disabled, live job run, pointer flipped or imported source deleted while preparing this checklist.
