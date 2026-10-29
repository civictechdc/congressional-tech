# Current-generation downstream owner commands

These controls bind D1 mapping `52120d49aa771c10105d87af6440b3d2a0b0c297aca08a0dac1c654205464d4b` and the fresh `d1_record_shapes_52120d49.captures` generation. `owned-pins.json` and `owned-continuation-pins.json` bind the current launchers. Earlier manifests, controllers and failures remain historical evidence. Every launch refuses existing work, runs detached and sends START/END mail; none starts the next job automatically.

Initialize in the raw worktree:

```sh
cd /Users/mikewolfd/Work/wt/ct-engine-first-raw
RAW_RUN=/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/codex-raw/run2
D1_RUN="$RAW_RUN/d1-record-shapes-52120d49"
```

The multiset comparisons for cohorts 01–03 passed on preserved immutable generations. Cohort 04 and D2 then stopped because their monitors charged the entire shared `codex-raw/` directory against one job's quota. Current launchers count only the job's own directory. They leave all existing evidence in place and retain the 25 GiB free-disk floor.

The current proof continuation keeps cohorts 01–03 accepted under the unchanged comparison definition and builds 04–06 serially in fresh directories below `$D1_RUN/proof-owned-v1/`. It uses the same profiles and fresh memory admission, and stops on the first failure:

```sh
.venv/bin/python -I "$D1_RUN/cxb_d1_owned_v1.py" proof launch
```

The comparison groups every public column once over a tagged union. Each side's count preserves duplicates; excess occurrences become `left_only` or `right_only`. Both sides are read once. Native grouping handles memory and spilling; no wide anti hash join remains. The shared grouping builder also serves the old-index comparison. Every resumed generation must retain its original guarded mapping, runtime and source identities. All six accepted reports must bind the same current proof definition. The proof's own source hash now includes that shared grouping implementation.

Each cohort owns a 5 GiB quota derived from the measured completed proof directories, their table sizes, the 608,182,272-byte partial cohort-04 output, the 3 GiB native spill bound and headroom. Full D1 owns 9 GiB: its plan projects the previous 212,848,640-byte table to 4,147,132 rows, allows four retained table equivalents, two copies of the largest 2,147,676,643-byte receipt, 3 GiB spill and 256 MiB metadata. The exact measurements and formulas are `owned-scratch-budgets.json`. New tables live inside their respective job directories; shared catalog metadata has a separate explicit authority and does not count as job scratch.

After `proof-owned-v1-status.json` is `equivalent` for all six cohorts, the lead launches the full run. Its work and new table are below `$D1_RUN/full-owned-v1/`; the canonical acceptance report stays `$D1_RUN/full-status.json`:

```sh
.venv/bin/python -I "$D1_RUN/cxb_d1_owned_v1.py" full launch
```

The D2 continuation uses the frozen fast worktree interpreter and an approved R2 credential environment. Its fresh work is `$RAW_RUN/d2-fast-production32-owned-v1/`, with an independent 5 GiB quota; its observed prior job used 1,121,230,848 allocated bytes. Pool 32, 2,048-body commits, 64 GET workers, backoff, and 20 GiB native / 24 GiB physical limits stay unchanged. The native preflight confirmed 1,165,282 committed reading rows and 895,089 bodies. Its fresh production anti-join found 141,369 remaining bodies, with zero custody conflicts or missing pins. The failed small-budget preflights remain evidence; their unlaunched larger prefix is superseded. No additional preflight runs alongside production.

The lead launched D2 as PID 9600 using the following command from its credential-bearing environment. Do not repeat it. The producer resolves the current table and runs the maintained anti-join before reading bodies; no local journal settles work:

```sh
/Users/mikewolfd/Work/wt/ct-engine-first-raw-fast/.venv/bin/python -I \
  "$RAW_RUN/d2-fast-production32-owned-v1/cxb_owner_production.py" launch
```

Its terminal status/report paths are `d2-fast-production32-owned-v1/status.json` and `report.json`. Every downstream authority binds these new paths; the failed status is never overwritten. The launchers verify the loaded package path before effects, so changing the current directory cannot silently select another worktree's editable packages.

After D2's actual terminal END, take a fresh read-only snapshot. This does not depend on D1 or the comparator:

```sh
.venv/bin/python -I "$D1_RUN/cxb_collect_d3_unreadables_owned_v1.py" launch \
  --work "$RAW_RUN/d3-unreadables-after-d2-owned-v1"
```

It lists the complete `provenance/` prefix once and qualifies every unreadable JSONL object through the maintained inventory reader. Existing limits stay 32 MiB per selected object, 256 MiB total cache, 2 GiB physical, 5 GiB owned storage and 25 GiB free disk. Its quota counts only the snapshot's own work directory. It performs LIST/GET only. The authority binds the exact terminal D2 report/status, inventory, complete listing and each checked file's byte qualification and custody. The old 15:27Z empty inventory is ineligible: the lead confirmed that unreadable objects already exist, even if the latest D2 run reports zero new ones.

After D1's full report is `public_guard_passed`, launch the comparator:

```sh
.venv/bin/python -I "$D1_RUN/cxb_compare_record_shapes_owned_v1.py" launch
```

This reads only the new generation's retained private evidence and the pinned 3,909,134-row oracle (`db03317389db7453270a15056209c7498b0750caaec4d7053aa5b0b945dde70d`). It verifies all 2,292 new receipt keys and 4,147,132 rows; comparison scope is the original 2,289 keys, with the three additions reported separately. Every old-only or unexplained occurrence remains an owner gate. The approved comparison limits remain 20 GiB native, 24 GiB physical, 12 GiB native scratch, 17 GiB owned storage and 25 GiB free disk. Its quota covers only `$D1_RUN/comparison-owned-v1/`; the canonical summary remains `$D1_RUN/comparison-report.json`, with complete retained differences below the owned directory.

After D1 full acceptance and the fresh snapshot's `qualified` END, launch D3. It can compute independently of the comparator, as approved by the lead:

```sh
.venv/bin/python -I "$D1_RUN/cxb_d3_record_shapes_owned_v1.py" launch \
  --work "$RAW_RUN/d3-record-shapes-52120d49" \
  --unreadable-inventory "$RAW_RUN/d3-unreadables-after-d2-owned-v1/data/inventory.json" \
  --unreadable-authority "$RAW_RUN/d3-unreadables-after-d2-owned-v1/data/authority.json"
```

D3 uses the current filename version `333b2bab7bca7a55add39afdb1f7669c63ca73ea608d6e267c057d05a6964cbb`, both qualified recovery files and the exact new capture pin. Its new table is `d3_record_shapes_52120d49_333b2bab.filename_readings`, physically inside its own work directory. The report is `$RAW_RUN/d3-record-shapes-52120d49/report.json`: consume its native `pin` only with `status = appended_local`, `appended = true`, the expected `catalog_version` and matching D1 `source_pin`. It includes `mapping_digest`, the exact terminal `source_d2_report` pin, `recovery_inputs` and unreadable authority/inventory. New filename unreadables leave `pending_unreadable` and prevent append. D3 retains its standard 10 GiB native / 16 GiB physical limits, 5 GiB for its own directory and 25 GiB free disk.

D3 reports `comparison_status = pending`, null `source_comparison` and null `source_comparison_owner_gate`, plus the canonical comparison report path. `qualified_for_downstream` remains false. The engine must bind the completed comparison to the same capture pin for model and release acceptance; D3 computation does not accept migration differences. A later incremental filename run uses a fresh work directory and `--existing` only after this new filename table exists.

The snapshot report also exposes the complete current provenance listing for the engine's publication binder. The lead applied both recovery provenance objects; the correction readback matches SHA-256 `e515d52e5a45a590f458dbbfce2dc7e80ad9a4e326dda80049ef8af522c3294b`. No blanket 12,432-reference import is required merely to compute the model; actual unmatched associations remain model/E4 evidence for owner disposition. No such import ran during this preparation.
