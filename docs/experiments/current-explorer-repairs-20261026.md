# Current explorer repairs — October 26, 2026

The existing explorer has been diagnosed against its deployed site and selected
data. Eight parallel `gpt-6.1-sol` tasks at high reasoning effort produced scoped
repairs. Their commits and subsequent user-requested simplifications are combined
from base `c466a45e09e27bde48ade12454f8b458c3643d21`. This report records source
changes and local verification; a source merge is separate from a successful
data publication or deployment.

## What is broken and the smallest repair

| Verified problem | Repair and remaining work |
| --- | --- |
| The deployed captured-files worker requires v6, but the public pointer selects v5 release `03fc4cfd93a74fdc9be16d41dc528207`. | Complete and select a verified v6 publication. A real-worker check now gates Pages before deployment and verifies the deployed result afterward. |
| The first v6 build performs a repeated full scan of component membership. | Add `views(component, name)`. The diagnostic lookup workload fell from 2.24 seconds to 0.0032 seconds, plus about 0.027 seconds to create the index. This does not establish whole-release runtime. |
| The canceled three-hour build retained no completed preparation or usable renderer state. | That old run cannot resume. New initial builds retain the existing SQLite stage state, verify its inputs and files, and skip completed work after an explicit resume. |
| A hard job timeout can prevent artifact preservation. | Stop preparation before the job deadline, require every process to stop, and retain a verified incomplete checkpoint. Resume uses the original code revision and fresh input checks. |
| Publication limits were below the catalog's minimum file/write counts. | Size file, state, write, and journal limits together; retain write intents while checkpointing derived state periodically. Test interruption and replay at catalog scale. |
| Preparation hid the stage consuming time. | Forward existing stage/task events into CLI output and retained timing/resource diagnostics. |
| Daily raw updates refused ordinary changes to discovery seeds or code. | Routine updates now process changed seeds automatically, refresh affected dependencies, and preserve retained documents when seeds disappear. Contribution-format changes still require migration. Full replay is reserved for deliberate historical reinterpretation. |
| Production qualification could compare selected output with a copy of itself. | Remove that shortcut and same-row-count cache admission; replay retained sources and compare actual values. |
| GPO's presumed manifest endpoint returned error content; malformed XML could terminate a batch or overwrite valid evidence. | Read the real package ZIP manifest through bounded HTTP ranges, validate its identity and checksum, retain rejected bytes, preserve valid history, keep failures pending, and save completed neighboring rows. |
| The `@NRDems` YouTube handle no longer resolves; other handles can change too. | All 119 configured channels now use verified stable IDs. New channels resolve once and retain the ID. Names, storage keys, and video history remain intact. Credentialed production refresh remains pending. |
| Successful uploads and preparation repeatedly reread or rewrite the same data. | Accept acknowledged conditional uploads, reconcile uncertain outcomes, and retain bounded public smoke checks. Render occurrence assets in one source traversal, reuse checked inventory facts, and write each journal payload once. |
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

## Earlier verification, before subsequent follow-ups

The initial integration at `acfb8953` passed **1,063 targeted tests**. These counts
precede the newer simplifications and are historical evidence, not validation of
those later changes:

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

That publication/workflow run took 95.17 seconds and includes the integrated
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

## Subsequent integration checks

The later integration adds routine seed updates, all 119 stable YouTube IDs,
GPO ZIP-manifest acquisition, acknowledged-upload handling, inventory reuse,
single-pass occurrence rendering, and local/cloud journal improvements.

- **235 data/collector checks passed** in 80.94 seconds after those changes.
- **202 publication capacity, local journal, preparation, workflow, status, and
  release-identity checks passed** in 39.96 seconds after the local/status port
  at `d36564b1`.
- **154 maintained JavaScript explorer checks passed** in 9.60 seconds.

These counts overlap earlier runs and must not be added together. The original
publication integration run also identified five outdated readback-test
expectations; their repair and the exact merged-main review are recorded in the
[merge and review record](explorer-main-review-20261026.md).

## Production completion boundary

The fastest restoration can publish v6 from the currently selected native
catalog using the repaired code, then verify the real worker. Keep that selected
input fixed through preparation and publication: changing it invalidates the
resume binding. The newer meeting seeds are a separate data update.

Ordinary scheduled raw updates now accept newer seeds and routine code changes;
the newer follow-up removes the former manual qualification requirement. The
existing writer lock, format/schema checks, retained evidence, and conditional
selection still apply. Collector reruns and an explorer refresh establish that
the upstream repairs are operational.

The remaining live work is collector execution and data publication, followed by
bounded live checks. A deployment gate prevents another incompatible site deployment;
it does not repair the already deployed v5/v6 mismatch by itself.

## Supporting evidence

- [Original controlled lookup and additional-index diagnostic](v6-preparation-20261026.md)
- [Lookup measurement and capacity diagnosis](v6-native-components-index-20261026.md)
- [Initial preparation resume and native fixture results](initial-v6-resume-repair-20261026.md)
- [Workflow checkpoint custody and real-worker gate](v6-workflow-custody-repair-20261026.md)
- [Catalog-scale continuation, journal, and checkpoint sizing](v6-continuation-capacity-20261026.md)
- [Raw seed identities, replay correctness, and automatic updates](raw-source-guard-20261026.md)
- [Stable IDs for all configured YouTube channels](youtube-channel-ids-20261026.md)
- [Inventory reuse](v6-inventory-reuse-20261026.md)
- [Single-pass occurrence rendering](v6-occurrence-passes-20261026.md)
- [Journal write reduction](v6-journal-simplification-20261026.md)

The primary checkout's diagnostic and proposed-design files were preserved.
Proposed redesigns were not used as evidence of current behavior or implemented.
