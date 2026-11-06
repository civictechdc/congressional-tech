# Archive disk admission and recovery artifacts

Archive wrappers require an explicit measured disk budget before launching setup,
publication or backfill. Missing budgets, a different Git revision, missing writing
roots or insufficient free space refuse the operation. The publisher's binding
check remains a separate read-only check.

The default budget file is `.cache/archive-release/disk-budgets.json`. The Mac
wrapper uses the main checkout's file; `ARCHIVE_DISK_BUDGETS` can name another
operator-qualified file. Budget records stay outside Git with their measurements.
Operation names are `setup`, `publish-fresh`, `publish-resume` and `backfill`.
An active maintenance binding would also require `maintenance`.

Each record names the exact selected Git revision, durable measurement evidence,
qualified input population and work limits, and peak **additional** allocation
per writing filesystem. Include the whole command: dependency installation and
site preparation for setup; daily inputs, model preparation, exports, comparison,
uploads and probes for publication; all producer phases for backfill. Qualify a
compatible retry separately. Existing retained artifacts already consume space;
the additional allowance is what the command can still need beside them.

This intentionally incomplete template refuses until its measurements are filled:

```json
{
  "version": 1,
  "operations": {
    "publish-fresh": {
      "revision": "<full selected Git revision>",
      "measurement": "<durable report location and identity>",
      "workload": "<qualified input identities, bounds, runtime and cache conditions>",
      "filesystems": [{
        "roots": ["<every writing-root name on this filesystem>"],
        "peak_additional_bytes": null,
        "headroom_bytes": null
      }]
    }
  }
}
```

Group every root on the same filesystem in one entry. A group spanning devices,
duplicate device entries, unknown roots or uncovered roots refuses. Headroom must
be at least 15 GiB, matching the existing emergency disk floor. Admission checks
free bytes against additional peak plus headroom. It does not allocate those bytes
or exclude unrelated writers; the runtime watchdog remains necessary.

Inspect publication admission without launching a producer or creating work:

```sh
.venv/bin/python -I .github/scripts/run-archive-job.py publish --check-disk \
  --nightly-work /absolute/main/.cache/archive-release/nightly/candidate
```

The JSON reports the required roots even when the budget is missing. Execution
keeps `*-disk-admission.json` beside the watchdog reports. Setup records its cache,
browser, temporary, checkout and pinned SpicyRegs input roots before installation.
Publication also covers startup work, model output/scratch, daily work, configured
runtime workspaces and the shared text index when enabled. Requalify the budget
when the revision, workload bounds, runtime, layout or cache conditions change.
Do not convert a sampled shared-volume drawdown into an isolated allocation claim.

After a publish/backfill process group exits, the Mac wrapper retains its nightly
lock while retiring only `native` children explicitly declared as job scratch.
It reads bounded job/checkpoint metadata, follows model-attempt stages and refuses
aliases, escapes, unknown layouts or overlap with retained inputs and outputs.
It preserves model intent/checkpoints, pinned results, manifests, prepared inputs,
daily work and unregistered directories. A live or uncertain process group retains
its spill. Failures in cleanup produce a diagnostic rather than deleting more.

Inspect stranded native spill through the existing cleanup command:

```sh
.venv/bin/python scripts/dev.py clean --nightly-spill
```

It defaults to a dry run and acquires the same nightly lock; a surviving child
prevents inspection/deletion. `--execute` applies the identical scoped plan after
the owner has reviewed it. This command considers only the main checkout's active
nightly candidate. It does not discover arbitrary cache or recovery directories.

Before a fresh backfill, the wrapper moves prior backfill work into the durable
run's `previous-backfill` directory instead of deleting ignored output. This
preserves bytes and diagnostics, including work beyond the small-JSON allowance.
It does not add a backfill resume capability or rewrite absolute pins. A cross-device
move refuses without copying or deleting the source. Candidate selection and
completed-model reuse continue through the maintained publisher.

Current operational acceptance still requires isolated whole-operation measurements
for setup, fresh publication, compatible retry and backfill on the final integrated
runtime. The earlier model-only measurement and failed nightly timelines do not
supply those budgets. No operational cleanup or release is authorized by this guide.
