# Independent static acceptance and scope review

Current disposition, November 6, 2026: **approve the corrected preparation
increment**. The follow-up below resolves the specific F1-F4 documentation issues.
The original findings and original request-changes verdict remain intact as the
review record. Full-scope preparation and replacement acceptance remain
incomplete; broad census and authentic execution obligations stay open.

The intended result is a complete replacement preparation package for baseline
`a06eb64bf3caa4a44e12a89bdd08939323de3092`. The reviewed changes describe future
ownership and acceptance; no replacement implementation or acceptance execution
exists in these changes. No suites, native jobs, downloads, corpus scans or
shared-repository mutations were performed for this review.

## Original findings — November 6, 2026

Locations and inventory counts in the original findings refer to the initially
reviewed preparation snapshot. Their current disposition appears at the end.

### F1 — P1: Bind maintained acquisition commands to explicit acceptance obligations

Location: `acquisition-capabilities.json:A01,A05,A20,A30`,
`acquisition-lifecycle.md:15-30,91-99`, and
`consumer-capabilities.json:C54` / `model-consumers.md:949,959-975`.

The archive capture allowlist and saved-snapshot flow do not account for several
maintained acquisition lifecycles. C54 names the console commands, assigns a
generic ownership split and leaves their detailed census to the source inventory;
the source inventory does not supply it. This is an explicit open handoff, not a
silently removed command. However, the catchall does not yet bind the following
observable branches to decisive acceptance procedures:

| Maintained behavior | Owning source and caller | Observable acceptance that needs a row |
| --- | --- | --- |
| Congress-scoped committee list, detail and history refresh | `.github/workflows/update-data.yml:159-170` → `cli/committees.py:9-20` → `acquisition/committees.py:32-103` | Refresh missing/recent Congresses, retain historical list facts separately from current detail, reject repeated/empty/invalid pages, preserve prior snapshot and rejected response on failure. |
| All-history House website discovery, targeted retry and offline reparse | `cli/house_sites.py:19-39` → `acquisition/house_sites.py:296-363,383-438,447-476,499-538` | Resume pending queues, preserve literal captured pages and failed checks, retain discovery-gap states, bind the same targeted retry manifest, reparse without new observations, and preserve timestamps and unrelated work. |
| House XML/witness/page fallback acquisition | `cli/house.py:22-37` → `acquisition/house.py:40-44,47-107` | Preserve confirmed absence versus request/XML failure, source-based selection, refresh limits, raw bodies, fallback evidence and explicit incomplete work. Generic capture of an already-known URL does not exercise this decision path. |
| Senate live/archive subtitle acquisition and protected output | `cli/senate_captions.py:25-44` → `transcripts/senate.py:57-155,158-208` | Preserve master/playlist/segment scope and fallback responses, zero-duration cues, complete versus incomplete tracks, staged gzip/text publication, last successful evidence and index continuation. A20 currently cites the YouTube caption path and observation interpretation. |

Paths shortened to `cli/`, `acquisition/` and `transcripts/` in this table are
under `packages/congress_api/src/congress_api/`.

These are existing behaviors, not speculative additions. Read assertions include
`test_committee_metadata.py:26-49,52-81`, `test_house_sites.py:46-75`, and
`test_senate_caption_recovery.py:15-22,31-46,68-97`. They assert distinct historical,
pending, failure and raw-evidence guarantees. Saving their files into a pipeline
snapshot after work does not prove that their replacement acquisition path
preserves those guarantees.

Responsible owner: congressional acquisition/domain owner; DocSpec owns the
replacement durable execution and DDK owns reusable definitions/evidence.
Recommended correction: reconcile maintained console scripts and scheduled
commands to explicit capability rows. Give each relevant branch a planned
independent procedure, authentic-input obligation and status. Keep undiscovered
upstream populations separately unverified. Do not close source completeness by
adding names alone.

### F2 — P2: The news reference coordinator is not an independent semantic oracle

Location: `acquisition-capabilities.json:900` and
`acquisition-lifecycle.md:74`.

A33 proposes the existing reference coordinator as an independent comparison for
news merging, validation and recovery. It is useful for differential storage and
transport checks, but part of its semantics is shared with the production path:

1. `storage/docspec/schema.py:17` imports coordinator `_merge_upsert`.
2. `merge_upsert_batch` calls that exact function at
   `storage/docspec/schema.py:212-218`.
3. The native implementation imports and calls the helper at
   `storage/docspec/lake.py:35,449`.
4. Both release paths use the same `check_corpus` implementation:
   `storage/docspec/lake.py:20,721` and `storage/releases.py:25,249`.
5. The maintained backend test itself documents this relationship and constructs
   expected merged values through these helpers:
   `tests/test_docspec_backend.py:1-8,386-396`.

The paths in this chain are under `packages/news_lake/src/news_lake/`, except the
test under `packages/news_lake/`. A shared merge or validation defect can pass the
proposed coordinator comparison. Calling it independent overstates the proof,
even though A33 correctly remains unverified.

Responsible owner: application acceptance author. Label the coordinator result
as differential parity. Add separate source/time/evidence expectations that do
not invoke the shared merge or corpus validator, including a newer poll followed
by an older poll, null scalar versus supplied scalar, repeated evidence and empty
collections. Poison a plausible merged value or omitted evidence member and
require the independent check to reject it. Keep raw semantic checking separate
from native-state/recovery parity.

### F3 — P2: State the actual assertion scope of incumbent test references

Location: `acquisition-capabilities.json:A21,A28`.

The linked tests are real, but some do not exercise the lifecycle or selection
behavior next to which they are listed. A28 lists
`test_source_observation_interpretation.py:12-34`, which checks official event
admission and dated/no-broadcast labels, and
`test_daily_producers.py:548-636`, which checks one inline saved record,
anti-join reuse, unreadable decisions and version shape. Neither cited range
checks ordered snapshot removal, true empty versus absent/unrecognized replacement
or source-context freshness.

The relevant existing selection example is
`test_phase2_meeting_appearance_lake.py:1545-1565`: its stated and asserted behavior
distinguishes unrecognized witnesses from empty and then builds a multi-context
freshness case. Its full native portion requires runtime configuration and is not
an executed result of this review. A test name or a retained report mentioning
that case cannot supply replacement acceptance.

A21's weekly-retention link has a narrower real assertion:
`test_weekly_retention_tables.py:276-293` retains a fake response and checks its
model identity. The implementation's expensive window path is
`transport/gemini.py:92-141` → `transcripts/generate.py:136-171` →
`cli/transcribe.py:72-100`. The linked retention assertion does not establish
fresh-process reuse of completed windows or atomic paired final output. A21
already proposes those new proofs; the distinction should remain explicit next
to its incumbent-test links.

Responsible owner: capability inventory/acceptance author. Add assertion-level
scope for each test link or split links into evidence categories such as
retention-only, selection, recovery and unimplemented replacement proof. Cite
the maintained cases that actually assert the advertised branch, and preserve
uncovered cases as gaps. This prevents implementation work from later counting
an adjacent regression as acceptance of the whole capability.

The same precision should apply to source citations. Three recipe rows in
`model-consumers.md:856-858` cite relationship definitions with the same names:
`recording_tracks:2808`, `document_editions:2358` and
`meeting_recordings:2421`. They are real passages, but they do not define those
recipes' SQL, parameters or result grain. Point those rows to their entries
inside `release-schema.json.recipes`, rather than the first same-name occurrence.

### F4 — P2: Do not treat retired JSON export as a supported baseline format

Location: `consumer-capabilities.json:C45` and
`model-consumers.md:949,1035`.

C45 says the compatibility exporter supports JSON and Parquet and proposes
accepting both formats. The owning callable explicitly refuses every format
other than Parquet at
`apps/committee_youtube/src/committee_explorer/export.py:380-381`. Its maintained
CLI exposes only `choices=("parquet",)` at `export.py:1111`, and
`apps/committee_youtube/tests/test_explorer_reuse.py:134-138` expressly asserts
that JSON export is rejected.

This is a source contradiction in the proposed baseline, not an unexecuted
replacement feature. Requiring a successful current JSON export would fail the
incumbent or cause the replacement to restore a deliberately retired route.
Historical JSON input, retained JSON readback and internal JSON control artifacts
are separate behaviors and may remain required where a maintained reader owns
them. Name and qualify those readers directly; preserve the explicit unsupported
new-export behavior unless the user requests a deliberate addition. Update C45's
format case and source evidence accordingly.

## Function and data trace inspected

No behavior-changing function was added or modified by this preparation patch.
The following owning functions were read to test the proposed capability map.

| Function or operation | Inputs → output | Verified static behavior and implication |
| --- | --- | --- |
| `acquisition.committees.collect`, `committees.py:32-103` | Retained meeting/GPO scope plus prior snapshot → committee rows/detail/history | Refreshes missing/latest two Congresses; validates list/detail identity and writes at the end. Its separate current-detail observation must not rewrite historical list status. |
| `acquisition.house_sites.collect`, `house_sites.py:296-438` | Directory, retained queues, retry selection and limits → checkpointed source/page/error state | Keeps admitted requests pending until application; distinct discovered/pending/failed/gap states survive. A generic known-URL capture loop is insufficient. |
| `acquisition.house_sites.reparse_pages`, `house_sites.py:447-476` | Retained original page bytes → corrected readings | Preserves source observations and timestamps; can restore a misclassified listing without acquisition. |
| `transcripts.senate.fetch_one/main`, `senate.py:57-208` | Player URLs, master/playlists/segments, prior index → scoped receipt, retained track, text/index | Keeps fallback responses; stages compressed capture before publication; failures retain error receipt and prior successful evidence. |
| `acquisition.capture_scheduler.run_capture` through durable tests, `test_capture_durable.py:32-83` | Fixed release/request identity, local adapter, immutable store → one durable occurrence | Actual subprocess tests kill five phases and assert no repeat adapter calls on resume. These are real incumbent assertions, read here and not run. |
| `lake._record_producer._current_inline_lines`, `_record_producer.py:552-587` | Candidate receipt locators → current line per source URL | Ranks by update date then witness count. Raw comparison must separately establish intended shrinking/removal semantics rather than copy this rank as the expectation. |
| `news storage merge helper`, `docspec/schema.py:212-220` | Existing/incoming records → merged validated rows | Calls the coordinator's merge function, limiting the independence of coordinator parity. |
| `news DocSpecLake.publish_release`, `docspec/lake.py:639-769` | Fixed cycle/pins/checkpoints → validated manifest, availability, cursor activation | Journals and resumes state; native pins and reader availability are separate from validation and cursor activation. |
| `lake.tables.append_rows`, `tables.py:180-221` | Exact source/schema/key definition → guarded native append | Native table operation recomputes pending keys on conflict. This cannot pass unchanged through DDK's currently refused catalog-operation profile. |
| DDK `_job_request` / `_native_read`, `src/ddk/adapters/docspec.py:396-415,444-473` | DDK request/native receipt → exact runtime binding/schema mapping | Catalog operations refuse; exact native mapping supports listed scalar physical types and IDs. Nested list/struct paths require the declared extension. |
| DDK quality `_bind`, `src/ddk/adapters/native_quality.py:179-201` | Protected exact native version → complete Arrow table | Reads full IPC then `read_all()`; reported byte limit is checked after table construction. G03 correctly records this mechanism without claiming a measured production failure. |
| DocSpec managed Build, `src/engine/managed_build.rs:300-311,380-385` | Build/version → managed result or refusal | Exact local profile requires an independent source-only dataset with no inherited base. G02 correctly distinguishes that profile from broader engine support. |
| MCP `Reader.query_sql/page`, `reader.py:198-223` | Typed validated query and exact release → bounded read-only rows/release-bound cursor | Rejects non-SELECT/multiple statements; binds cursor to release and normalized query; uses explicit stable order. Current tests inspect typed precision and complete paging, not new replacement execution. |
| MCP `Reader.dataset_info`, `reader.py:95-129` | One metadata selector and published controls → stated tables/relationships/recipes | Unknown relationship versions leave ordinary table/SQL access available and refuse unsupported relationship interpretation. External detail descriptors do not grant external row access. |
| Committee Explorer `export/main`, `export.py:350-381,1108-1111` | Maintained source inputs and Parquet format → compatibility publication | Rejects new JSON export before assembly; CLI exposes only Parquet. C45 must separate this refusal from historical reader compatibility. |

Congressional source paths in this table are under
`packages/congress_api/src/congress_api/`; news paths are under
`packages/news_lake/src/news_lake/`; MCP paths are under
`apps/explorer_mcp/src/congressional_explorer_mcp/`; Committee Explorer paths are
under `apps/committee_youtube/src/committee_explorer/`. DDK and DocSpec paths
refer to the parent-owned repositories named in `runtime-gaps.md`, read only for
this review.

## Evidence and limitations

The original acquisition JSON contained 35 rows. A bounded reference check found all its
`baseline_sources` and `current_tests` paths present and all supplied numeric line
ranges within their files. This is path validity, not assertion coverage or
exhaustiveness. F3 illustrates why the distinction matters.

The original consumer JSON contained 54 rows. Its cited paths, numeric line ranges and
named Python test functions resolve. The proposed
`scripts/measure/ddk_consumer_acceptance.py` does not exist; every command is
expressly marked proposed and unimplemented, so it is not falsely presented as a
passing or available harness. An implementation must still bind each case to its
actual application entry point and exact family-specific evidence.

A separate metadata-only reconciliation found no missing or mismatched native
field paths, requiredness or field/element IDs across all eight native schema
sections. All 23 public tables and their 254 declared columns, including their
declared types/nullability, occur in the consumer census. All 70 relationship IDs
and 16 recipe IDs are listed. This establishes fidelity to those owning
definitions, not correctness of their values, whole-workspace completeness or
runtime parity. C45 and C49-C54 expressly retain incomplete compatibility/news/
remaining-command inventories; their catchalls cannot close those denominators.

The source-versus-retained-schema comparison was independently repeated using
the small retained schema JSON. It confirms all four added-field groups and the
`meeting_coverage.reason` declaration change named at
`model-consumers.md:13-20`, plus 69 retained versus 70 current relationships. The
consumer document correctly refuses to lower current-source obligations to the
older immutable release. C14/C35 need authentic current-source cases beyond that
old release's payload.

The retained `publication-approved/public-pointer.json` and `completion.json`
name historical selected release `e145d24c389e...`, the previous release and a
November 5 completion. They do not establish current remote state. The retained
`acceptance-six-tickets-20261105/attempt-46wmfs5a/report.md:7-10,27-43` explicitly
limits its result to 57 tests in a partial lane plus selected published metadata;
it also names remaining recording/date/retirement work. The preparation documents
correctly do not turn those reports into whole-corpus or replacement acceptance.

The native schema example `model/lake/meeting-records.schema.json:12-46` contains
list/struct field and element IDs, so a scalar-only exact mapping cannot satisfy
the planned preservation requirement. This is a source-grounded unsupported
mapping, distinct from an unexecuted scale claim. No replacement rows were read,
no authentic body completeness audit was attempted, and no runtime compatibility
or performance result is claimed.

The release prerequisite changed under the parent during this review. The live
gate was read as `implementationReady=true`, with local replacement implementation
authorized and production cutover false. Historical `false` observations should
remain labeled as historical. This report creates no further approval flow and
authorizes no external cutover or shared-runtime edits.

## Original preparation verdict — November 6, 2026

**VERDICT: REQUEST CHANGES for a claim of completed full-scope preparation.**

The documents preserve the key architectural boundaries and honestly leave every
capability unverified. The archive schema/relationship/recipe census is a useful,
source-consistent starting point. Resolve F1's named lifecycle acceptance handoff,
correct F2's independent-oracle claim, make F3's evidence scope precise and remove
F4's false supported-format assertion before calling that preparation complete.
Record remaining source-family/compatibility/news schema denominators as explicit
owned work, with their closure criteria; a list of capability names alone is not
proof of exhaustive coverage.

Coverage of proposed paths: **insufficient for replacement acceptance**. Confidence
in the cited static findings: **high**. Authentic-input fidelity, runtime
compatibility, shared-runtime extensions, connected end-to-end behavior, recovery,
incrementality, cold restore, resource bounds, complete test lanes and deployed
readback remain future evidence obligations. This review does not require those
unrun proofs to be executed during documentation preparation.

## Follow-up disposition — November 6, 2026

This follow-up inspected the corrected acquisition and consumer inventories and
their companion prose. It covers the F1-F4 preparation corrections only. No
implementation, new source behavior, runtime compatibility or replacement proof
was assessed. No suites, native tools, acquisition, Git action, shared write or
elevation occurred; this review report is the only file changed by this reviewer.

| Original finding | Current disposition | Correction and remaining limit |
| --- | --- | --- |
| F1: Missing lifecycle acceptance bindings | Addressed for the named preparation omissions | A36/A37/A38/A39 explicitly bind House all-history discovery/retry/reparse, Congress committee list/detail/history, House XML/page fallback and Senate live/archive captions. A40-A43 further distinguish maintained Congress/GPO/Senate console lifecycles. C54 has four corresponding required source branches with separate assertion scope, decisive procedure, owner and authentic-input gap. The bounded 21-command `project.scripts` census records command targets and handoffs without claiming every module/script caller or upstream source/window is enumerated. |
| F2: Shared news implementation called an independent oracle | Addressed in the proof plan | A33 explicitly labels DocSpec/PyIceberg comparison as backend differential evidence, identifies shared `_merge_upsert`/`check_corpus`, and separately requires a checker importing neither shared semantics nor production selection. It names newer/older polls, scalar presence, evidence membership, empty collections, earliest time and two poisoned-output challenges. This is a planned independent check, not evidence that it exists or passes. |
| F3: Adjacent tests and first-name source matches overstate evidence | Addressed in the cited preparation rows | A21/A28 now include assertion-level `current_test_scope`, remove the misleading adjacent links, distinguish retention/context from selection/recovery, and preserve unproved shrinking/removal/host-loss cases. A33 labels shared-helper test scope. The three recipe references now point to the recipe section (`model-consumers.md:856-858`, registry lines 3739/3762/3784). No test was run or newly qualified by this correction. |
| F4: Retired JSON export described as supported | Addressed | C45 now requires current Parquet export and explicit new-JSON refusal, while separately assigning historical JSON partition readback/history migration and distribution activation procedures. `model-consumers.md:1163-1165` preserves the maintained Committee Explorer workflow instead of retiring it with the JSON export format. Historical cold readback, distribution and current remote enablement remain unverified. |

The corrected acquisition inventory has 43 rows, including A36-A43, all marked
`unverified`; each added proof remains `planned_not_run`. The consumer inventory
retains 54 unverified rows. The new bounded console census states its declaration
boundary and explicitly excludes an inference of upstream completeness. These
are documentation-state checks only.

The unresolved denominators now have explicit owners and closure requirements in
`model-consumers.md:1169-1179`: remaining console/module/report callers; complete
Committee Explorer schemas/distribution; news nested fields, relationships and
lifetime; YouTube/caption/report coverage; actual CPI/Sheets behavior; historical
and current archive evidence; and qualification/activation. Acquisition also
retains source/site/Congress/date-window, script-only campaign, raw custody and
authentic-proof gaps (`acquisition-lifecycle.md:52,124-134` and the JSON census's
`unresolved_scope`). None of those denominators is closed by adding capability
names or passing this follow-up review.

**VERDICT: APPROVE the corrected preparation increment.** F1-F4 no longer block
using this increment as a more precise, evidence-limited preparation handoff.
This approves the corrections, not a claim that all preparation is complete.
The original broad completeness and authentic execution gaps remain required
work. Replacement acceptance is still unexecuted, and this review makes no
implementation, performance, publication or production-readiness claim.
