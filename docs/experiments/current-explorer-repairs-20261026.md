# Current explorer repairs — October 26, 2026

The existing explorer has been diagnosed against its deployed site and selected
data. Eight parallel `gpt-6.1-sol` tasks at high reasoning effort produced scoped
repairs. Their commits are combined on `codex/current-explorer-repair`, based on
`c466a45e09e27bde48ade12454f8b458c3643d21`. These are local changes. No production
publication, source adoption, workflow dispatch, or deployment has occurred.

## What is broken and the smallest repair

| Verified problem | Repair and remaining work |
| --- | --- |
| The deployed captured-files worker requires v6, but the public pointer selects v5 release `03fc4cfd93a74fdc9be16d41dc528207`. | Complete and select a verified v6 publication. A real-worker check now gates Pages before deployment and verifies the deployed result afterward. |
| The first v6 build performs a repeated full scan of component membership. | Add `views(component, name)`. The diagnostic lookup workload fell from 2.24 seconds to 0.0032 seconds, plus about 0.027 seconds to create the index. This does not establish whole-release runtime. |
| The canceled three-hour build retained no completed preparation or usable renderer state. | That old run cannot resume. New initial builds retain the existing SQLite stage state, verify its inputs and files, and skip completed work after an explicit resume. |
| A hard job timeout can prevent artifact preservation. | Stop preparation before the job deadline, require every process to stop, and retain a verified incomplete checkpoint. Resume uses the original code revision and fresh input checks. |
| Publication limits were below the catalog's minimum file/write counts. | Size file, state, write, and journal limits together; retain write intents while checkpointing derived state periodically. Test interruption and replay at catalog scale. |
| Preparation hid the stage consuming time. | Forward existing stage/task events into CLI output and retained timing/resource diagnostics. |
| Daily raw updates used seeds different from those approved by the selected catalog. | Keep the guard and show exact mismatching fields. Qualify final code against retained old seeds, then explicitly adopt the desired new seeds. This operational adoption remains pending. |
| Production qualification could compare selected output with a copy of itself. | Remove that shortcut and same-row-count cache admission; replay retained sources and compare actual values. |
| Malformed GPO XML could terminate a batch or overwrite valid evidence. | Retain rejected bytes and errors, preserve valid history, keep failed packages pending, and save completed neighboring rows even when the job fails. |
| The `@NRDems` YouTube handle no longer resolves. | Pin its verified stable channel ID while preserving its existing handle and video history. Credentialed production refresh remains pending. |
| Bare `conftest` imports broke combined collector test collection. | Move shared test fixtures into an explicitly named support module. |
| Importing release identity through the package first could leave its script import empty. | Repair the shared import path and include the maintained identity implementation in the source fingerprint. |

The committee explorer is a separate publication. The deployed release
`6d06773fecf00f62f02293d3` contains 18,453 meetings, 3,432 committee terms,
378,033 materials, and 66,570 witnesses. Sampled meeting, material, detail, and
source-evidence queries worked. Its successful publication did not prove that
all upstream collectors had succeeded.

No additional index was justified by the measured query plans. The tested
`member_ids(id, source_id)` index improved reads but made the combined insert and
read workloads 2–21% slower.

## Verification

The integrated repairs passed **1,063 targeted tests**:

- **489 publication/workflow Python checks**, including native initial adoption,
  interrupted resume, input drift, complete-artifact identity, scale limits,
  journal replay, release imports, preflight, and native runtime setup.
- **420 collector/data Python checks**, covering raw qualification, GPO error
  handling, news-lake behavior, and YouTube identity/history.
- **154 maintained JavaScript explorer checks**, including real worker fixture
  execution and the new live-publication verifier checks.

The full offline suite also collected **11,326 tests**, with 50 loopback tests
deselected by that lane. This was a collection check, not an 11,326-test execution.
`git diff --check` and the new shell helper's syntax check passed.

The final publication/workflow run took 95.17 seconds and includes the integrated
capacity, completion-boundary, and release-identity fixes. Its runtime source
revision is `341c3b57`; the only later edits are this report and the corrected
native-runtime workflow assertion exercised in that run. Collector and JavaScript
checks took 281.80 and 13.30 seconds respectively; their affected implementation
files did not change afterward. These are local checks, not hosted CI results.

Python checks used the locked Python 3.12.13 workspace and the existing qualified
native executable with private fixture workspaces. JavaScript checks used Node
22.22.2 and locked site dependencies. Integration logs are retained at
`/tmp/ct-integration-final-20261026.log`,
`/tmp/ct-integration-js-20261026.log`, and
`/tmp/ct-integration-collection-20261026.log`.

Tests cover local fixtures, real native fixture execution, and simulated remote
writes. They do not establish a completed full-catalog release or hosted runner
performance. A live read-only browser check reproduced
`Unsupported filename catalog version.` A fresh public-pointer and manifest
read at **2026-10-26 18:53 UTC** still selected filename version 5 and the same
committee explorer release listed above.

## Production completion boundary

The fastest restoration can publish v6 from the currently selected native
catalog using the repaired code, then verify the real worker. Keep that selected
input fixed through preparation and publication: changing it invalidates the
resume binding. The newer meeting seeds are a separate data update.

For that update, qualify the final source fingerprints after the combined code
is accepted. Preserve the selected catalog and old seeds; verify current
selectors under the maintained writer lock; qualify existing values; then
explicitly adopt the desired newer seeds. Review resulting data changes before
refreshing the viewer. Collector reruns and an explorer refresh establish that
the upstream repairs are operational.

The minimum remaining work is operational adoption and publication, followed by
live readback. A deployment gate prevents another incompatible site deployment;
it does not repair the already deployed v5/v6 mismatch by itself.

## Supporting evidence

- [Lookup measurement and capacity diagnosis](v6-native-components-index-20261026.md)
- [Initial preparation resume and native fixture results](initial-v6-resume-repair-20261026.md)
- [Workflow checkpoint custody and real-worker gate](v6-workflow-custody-repair-20261026.md)
- [Catalog-scale continuation, journal, and checkpoint sizing](v6-continuation-capacity-20261026.md)
- [Raw seed identities, replay repair, and prepared adoption commands](raw-source-guard-20261026.md)
- [Stable YouTube channel verification](natural-resources-youtube-20261026.md)

The primary checkout's diagnostic and proposed-design files were preserved.
Proposed redesigns were not used as evidence of current behavior or implemented.
