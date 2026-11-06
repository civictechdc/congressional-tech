# Independent architecture review

Latest status: the final dated reassessment rejects the provisional definition
bridge as the end-state. Its default wiring was withdrawn during review. Earlier
approval concerned logical ownership boundaries only; it did not accept this
implementation or establish replacement completion. Earlier findings remain
preserved below.

Completed source/design review, November 6, 2026. No implementation qualification.

**Verdict: RECONSIDER the target seams; keep the ownership decision.** The proposed
direction can serve the full replacement, but the current documents do not yet
specify an executable native profile for the real inputs, all required checks,
durable acquisition, and each application's publication boundary. The released
DDK demonstration is narrower. Its passing qualification does not resolve these
application obligations.

This is design acceptance, not implementation qualification. A blocker below
blocks a claim that the complete replacement design is settled; it does not
create another release prerequisite or revoke the user's authorized work.

## Findings

### F1 — BLOCKER: specify the native reference and application profile

Category: named-seam / intent-versus-shape. Location: `design.md` §One owner per
decision; `runtime-gaps.md` G01, G02 and G04.

The design requires exact existing native identities, nested field/element IDs,
incremental changes, and a complete materialized model. The released adapter
cannot carry those inputs through the proposed managed path:

* Congressional model inputs use `metadata_location`, `table_uuid`, `snapshot`
  and `schema_id`, including remote metadata locations
  (`model/jobs/publish-model.json:4-51`; `lake/tables.py:123-135`). DDK explicitly
  refuses raw `native_table` and `iceberg` inputs and accepts a different local
  `VersionRef` profile (`DDK/src/ddk/adapters/docspec.py:343-353,396-440`).
* The native mapping accepts only named scalar Arrow types with top-level IDs
  (`DDK/src/ddk/adapters/docspec.py:444-473`). The actual meeting schema has
  `fixed[32]`, list element IDs and nested struct fields
  (`model/lake/meeting-records.schema.json:6-46`). Describing these paths in a
  catalog does not make them executable. DDK's core compatibility profile also
  interprets flat scalar properties only; required nested reasoning remains
  `unknown` and cannot produce an overall pass
  (`DDK/docs/specification.md:94-97,254-281`).
* The adapter refuses catalog operations, while the incumbent lake resolves,
  creates and appends native tables with them
  (`DDK/src/ddk/adapters/docspec.py:396-398`; `lake/tables.py:108-120,138-220`).
  The managed quality profile refuses inherited bases and computed/related
  groups (`DocSpec/src/engine/managed_build.rs:300-312,370-393`).

These are demonstrated profile restrictions. They are **not** proof that the
whole engine lacks native table readers or multi-output jobs. Its `JobInput`
already supports exact native table pins, and `JobSpec` already carries steps,
multiple outputs, queries and table operations
(`DocSpec/src/job/spec.rs:22-51,138-152`).

**RESHAPE:** turn G01/G02/G04 into one named congressional native profile with
explicit input reference schemes, group/schema mappings, required request kinds,
backends, protection, supported nested compatibility checks and returned evidence.
Admit the original table pin without
export/reimport or invented IDs. Preserve every nested field/element identity.
Map the declared application into the existing native job structure where it fits;
preserve shared materialization and export settings instead of invoking one
fixture calculation per SQL fragment. Extend only the missing native lifecycle
operations, then qualify that exact tuple. Keep unsupported cases explicit until
the owning profile supports them.

### F2 — BLOCKER: define which exact evidence guards each selection

Category: ownership / named-seam. Location: `design.md` §What goes in…,
Qualification and release row;
`runtime-gaps.md` G03/G05; `acceptance-plan.md` P03/P06/P10.

The plan requires six native invariant families and real reader/publication
checks. The existing model executes diagnostic SQL and refuses nonzero outcomes
before producing a release (`archive_format.py:237-265,323-336`). The publisher
then checks candidate-specific reader receipts and conditionally writes the
public pointer, reconciling acknowledgment loss by exact pointer readback
(`archive_gate.py:15-65`). Those are different decisions at different boundaries.

The released managed policy allows one evaluator identity/version and one
`duckdb-direct-view` semantic profile, and its evidence admission parses that
evaluator's report and a single source-only native read
(`DocSpec/src/engine/managed_build.rs:31-39,67-90,143-158,315-328,590-699`). It does
not establish a route for accepting the archive's cross-table SQL evidence. Merely
raising its input limit would leave this gap. Its quality bridge also collects
the IPC bytes and then calls `read_all()`, with an additional decoded table and a
separate DuckDB memory budget
(`DDK/src/ddk/adapters/docspec.py:111-146`;
`DDK/src/ddk/adapters/native_quality.py:188-201,224-233`). No production-size failure
or total-process resource result was established in this review.

**RESHAPE:** name the checks that guard native data selection and the checks that
guard application publication. Bind each to its exact candidate, complete table
membership, rule/evaluator identity and coverage. Give native SQL invariant
evidence an explicit acceptance path through DocSpec; preserve its maintained SQL
and failure meaning. Keep the browser/remote canary at the publication boundary
where it can observe the uploaded representation. Specify how both decisions
retain one exact candidate/release binding. DDK composes their evidence; it must
not turn a valid report into native acceptance, reimplement the invariant rules,
or introduce another selection pointer. Use a supported bounded native check/read
path rather than whole-population Python materialization by default.

### F3 — BLOCKER: declare durable acquisition and activation as concrete seams

Category: ownership / unstated-assumption. Location: `acquisition-lifecycle.md`
§What goes in… and §Expensive reusable phases; `design.md` §One owner per decision.

Assigning durable phases to DocSpec is correct, but assigning an owner is not an
invocation/recovery protocol. The current acquisition wrapper seals downloaded
payloads, retains exact request identity, refuses uncertain started calls,
reconciles receipts, and preserves charged retry evidence
(`acquisition/capture_journal.py:50-87,94-142,154-175`). The inspected native managed
API admits calculation/data operations; its operation enum does not declare an
acquisition task (`DocSpec/src/model/operations.rs:330-339`). No reviewed target
artifact says how a maintained domain adapter is invoked as a native durable
phase, how its external call/result is admitted and sealed, or how its retained
journal is adopted. This is an unnamed seam, not a demonstrated impossibility of
extending DocSpec.

Publication also has several real visibility boundaries:

| Workflow | Existing boundary that must be preserved or deliberately replaced |
| --- | --- |
| Archive | Immutable candidate assets, exact reader checks, then conditional pointer and exact readback (`archive_publish.py:480-507`; `archive_gate.py:23-65`). |
| News | Fenced cycle, exact dataset pins, validation, manifest, availability and checkpoint activation (`news_lake/storage/docspec/lake.py:639-769`). |
| Weekly snapshot / committee export | Raw snapshot before updating the bot-owned ref; export also retains persistent IDs/history and browser files (`.github/scripts/save-pipeline-data.sh:1-20`; `.github/workflows/publish-explorer.yml:89-167`). |
| Inflation / Sheets | Two CSV outputs committed together; documented Sheets readers import their mutable main-branch URLs (`.github/workflows/bls-cpi-update.yml:24-48`; `apps/inflation_gsheets/README.md:25-34`). |

One native selected dataset does not by itself settle these application effects.
Hosted archive capture currently keeps its work under runner temporary storage
and uploads only three summary/selection files, so local phase kill tests do not
prove recovery after runner loss (`.github/workflows/capture-archive.yml:57-68`;
`packages/congress_api/tests/test_capture_durable.py:32-83`).

**RESHAPE:** add a compact operation/activation matrix for these workflows. For
each, name the exact native phase request, domain adapter, immutable input and
completion identities, adopted incumbent state, reconciliation action, visible
selection authority and last protected consumer. State what survives process
loss and host loss. Keep one DocSpec lifecycle owner and the existing application
publication authority at its actual external boundary. The final application
command can compose these supported operations; it must not retain the incumbent
journal/controller as a second active state machine. Do not make independent
products share a global release or a generic scheduler merely to fit the design.

### F4 — CONCERN: keep scope and policy decisions separate from proof status

Category: scope / acceptance gap. Location: `acquisition-lifecycle.md` §§Scope,
Refusal… and Current gaps; `acceptance-plan.md` §§Authentic evidence and Evidence
per capability.

The final consumer inventory considerably improves the archive census: 54 planned
capabilities, eight nested lake schemas, 23 public tables, 70 relationships, 16
recipes, six MCP tools, 17 browser-worker routes, direct reader helpers and 21
console entry points (`model-consumers.md` §§Lake table/field/type census, Public
table/field/type/grain census, All relationship definitions, Recipe and pinned
upstream census, Route… and Console entry points). I independently checked the
registry's 23/70/16 counts and the native worker/MCP routes, not every listed
field or test citation. The inventory is useful preparation, but it does not yet
enumerate every required path: C45 and C49–C54 explicitly leave compatibility,
news and remaining command/consumer detail incomplete. The acquisition inventory also disclaims a
complete source/window census. No capability row has replacement evidence.

The Committee Explorer workflow still declares push/completed-run
triggers, state recovery, export, packaging and deployment dispatch; the exporter
retires only its legacy JSON format
(`.github/workflows/publish-explorer.yml:5-22,89-167`;
`apps/committee_youtube/src/committee_explorer/export.py:379-381`). Source presence
does not prove live enablement, but a transitional label alone cannot retire that
caller. The final inventory correctly keeps the compatibility export in required
scope; its successful format must follow current code, which refuses JSON, rather
than the older README's JSON claim.

Some uncovered decisions concern intended behavior, not just missing tests.
Inflation's workflow says BLS/FRED must succeed, while the implementation skips
failed providers and emits only returned columns; all-source failure returns
zero without writing (`.github/workflows/bls-cpi-update.yml:27-33`;
`apps/inflation_gsheets/src/fetch-inflation-sources.py:126-175`). News accepts a
caller-supplied raw URI/hash without storing or verifying custody at that point
(`news_lake/adapters/common.py:57-97`). No architecture review can infer missing
historical raw bytes from these records.

**RESHAPE:** complete a census from source entry points through outputs to
consumers, with explicit preserved, deliberately changed, unavailable and retired
dispositions. Resolve the inflation freshness/failure decision and each raw
custody obligation in the domain definition. Record unavailable historical raw
evidence honestly. Preserve currently deferred live news/OCR surfaces as explicit
limits unless the user's scope separately requires their implementation. Do not
promote an incumbent defect to intended behavior or invent a new source to make a
coverage row pass. This is an acceptance-scope blocker for complete delivery, not
a demand for a full-corpus replay during design review.

## Artifact summary and decision frame

The reviewed proposal replaces duplicated definitions, execution control and
catalog infrastructure while retaining maintained domain acquisition, parsing,
identity, correction and SQL semantics (`design.md` §§Outcome and scope, One owner
per decision). It spans acquisition, native lake/model operations, publication,
MCP/API/site readers, news, YouTube/reporting, committee export and inflation.
The beneficiaries are researchers who need exact answers and historical links,
and maintainers who need one reusable definition and recoverable execution path.

Category: **product replacement design with proof and operational work**. The
documents currently change no user-facing behavior. Their value is a credible
route to replacing the complete maintained path; catalog coverage alone would
not supply that value (`design.md:11-23,164-169`).

Source roots used below:

* Unprefixed congressional source: this worktree at
  `a06eb64bf3caa4a44e12a89bdd08939323de3092`;
  `lake/`, `acquisition/` and `news_lake/` abbreviate their package `src` roots,
  and `archive_*.py` abbreviates `packages/viewer_publication/src/viewer_publication/`.
* `DDK/`: `/Users/mikewolfd/Work/data-design-kit`, clean at documentation commit
  `3d2622b7a1cd0a454451987cd0ff7faf29d86e21`; its release record names qualified
  implementation `8e9a53e81ec6258f2068557ff5e4788c80c32995`
  (`DDK/docs/local-release.md:7-23`).
* `DocSpec/`: `/Users/mikewolfd/Work/worktrees/docspec-ddk-runtime`, clean at
  `b1270b2e964becc5844bb6ca95ee5d605c7a3d79`.

Main advanced to `3fa33b744ca5f1806c70f88b9ff5086fe9ef6984` during this review.
A bounded Git name comparison found no tracked differences from the frozen
baseline in the inspected API, publication, news, YouTube, inflation, MCP, site,
model and workflow paths. Its two untracked paths were left untouched. This is
not a future drift guarantee.

The live parent release record was re-read with `implementationReady=true` and
`releaseState=local-release-complete; local-replacement-implementation-authorized;
publication-destination-pending`. External package publication is a separate
pending action. The earlier false values in the preparation records describe an
earlier observation, not a current implementation prohibition.

## Lineage and relationships

| Prior artifact | Relation and practical meaning | Evidence |
| --- | --- | --- |
| User's full replacement objective | Supersedes retaining a whole incumbent controller behind a new metadata layer; preserves domain meaning and source-to-user scope. | `design.md:11-23,78-81,102-107` records that decision; supplied review objective. |
| Congressional model | Constrains raw fidelity, expensive computation, source versions, occurrence meaning, output identity and every retained field's destination. | `docs/engine-first-data-model.md:15-23,39-46,755-779,952-981`. |
| Root-cause remediation plan | Retained native producers/controllers for its earlier repair scope. The new request changes that infrastructure choice, while its package/witness scope, supersession and nested activity rules remain obligations. | `docs/plans/congress-explorer-root-cause-remediation-20261104.md:13-21,38-116`; `design.md:102-107`. |
| DDK normative architecture and reuse requirements | DDK owns definitions/checks and explicit injection; runtime owns computation reuse, phases, protection and managed selection. | `DDK/docs/specification.md:145-148,418-430,609-628`. |
| DDK catalog requirements | Generated descriptions preserve native identity, occurrence, scope, unknown coverage, exact membership and historical bindings; catalog assembly cannot create qualification. | `DDK/docs/specification.md:703-741`. |
| Released local profile | Provides reusable completed qualification for its exact small local scope; does not qualify arbitrary native operations or these project consumers. | `DDK/docs/local-release.md:34-46`; `DDK/docs/implementation-status.md:49-55`. |
| Repository execution rules | Require pinned runtime, isolated environment, native admission and measured total-resource control; raw checks need separate facts and a nonauthor-confirmed planted error. | `AGENTS.md` §§Test execution, Raw checks, Archive ETL; `acceptance-plan.md:17-21,54-64`. |

| Component / seam | Owner | Reads / produces | Declared and executable status |
| --- | --- | --- | --- |
| Reusable definitions to generated consumer metadata | DDK definitions; native schema owns physical types/IDs | Existing schemas, meaning, relationships and recipes → checker/catalog/service formats | Named in `design.md:48-54`; conversion and retirement parity unrun. |
| Source adapter to durable acquisition | Domain adapter and policy; DocSpec phase/custody owner | Exact request/occurrence → retained body/disposition/receipt | Ownership named; invocation, adopted state and host-loss durability need F3. |
| Exact table/reference to protected read | DocSpec; explicit DDK mapping adapter | Native pin and schema → exact typed view with field IDs | Current local source-only version path exists; original pin/nested path needs F1. |
| Domain model to native job | Domain SQL/rules; DocSpec execution | Exact lake/reference versions → materialized steps and exports | Existing native multi-step substrate; DDK application mapping needs F1. |
| SpicyRegs reference generation to model/discovery | SpicyRegs owns the generation; congressional domain owns its use; DDK describes the binding | Exact generation/table pins → bounded local summaries and external-detail descriptors | Existing import verifies each table's generation path (`archive_model_job.py:144-165`). Seven external descriptors do not establish MCP access to external detail (`model-consumers.md:864-885`, C37). Preserve exact versions on both sides of any qualified cross-project read. |
| Candidate to accepted qualification | Maintained check evaluator; DocSpec admission | Exact rule/check evidence → accepted native qualification | DCC-only local profile demonstrated in source; cross-table qualification needs F2. |
| Native result to application activation | DocSpec retained result; existing publication authority | Protected complete candidate → app-specific selected release | Application semantics differ by workflow; F3 names the missing matrix. |
| Release to researcher response | Maintained MCP/site and other consumers | Exact membership/representations → answers, stable links, cursors, reports, Sheets values | Reader behavior stays a separate acceptance obligation; catalogs alone cannot prove it. |
| Kept references to retirement | DocSpec/native maintenance, with domain policy | Complete protected-reference set → eligible derived cleanup | Existing native purge protects kept table UUIDs and historical pins; no cleanup performed (`lake/maintenance.py:168-195`). |

## Invariants and commitments

These statuses describe the **proposal**, not passed implementation tests.

| Invariant | Status | Evidence and failure mode |
| --- | --- | --- |
| DDK never becomes a second lifecycle, retry, retention or selection owner. | PRESERVED in intent; RELIED UPON at F3. | `DDK/docs/specification.md:609-623`; `design.md:60-71`. A retained incumbent journal plus new native journal would split recovery authority. |
| Original native schema IDs, binary values and exact versions survive the boundary; missing data never falls back to latest. | RELIED UPON; released mapping insufficient. | `DDK/docs/specification.md:614-616`; `design.md:85-99`; F1. Flattening/reimport or latest fallback would change identities and historical answers. |
| Source occurrence, content, interpretation, release and selection remain distinct. | PRESERVED in target definitions. | `DDK/docs/specification.md:718-725`; `acquisition-lifecycle.md:46-50`. Shared bytes must not erase distinct acquisitions or repeated observations. |
| Missing, empty, refused, pending, superseded and unknown remain separate; partial omission is not deletion. | PRESERVED in stated policy; domain edge decisions open. | `design.md:89-97`; `acquisition-lifecycle.md:52-62`; F4. A partial refresh must not become an unsupported removal or fabricated absence. |
| Required checks and exact candidate membership guard the relevant selection; uncertainty cannot pass. | RELIED UPON; missing complete seam. | `DDK/docs/specification.md:618-623,732-741`; `acceptance-plan.md:29-36,60-64`; F2. A passing scalar evaluator must not authorize a release with failed joins or unready representations. |
| Reuse follows relevant immutable dependencies, while qualification-only changes reuse computation. | PRESERVED in target; unproved through final caller. | `DDK/docs/specification.md:427-430`; `design.md:109-130`. Hashing whole project provenance or replaying all phases would invalidate valuable work unnecessarily. |
| One applicable parser version per logical key; multiplicity/order and occurrence identity survive correction. | PRESERVED in target. | `AGENTS.md` §§Byte-hashed parser pins, Archive ETL; `design.md:85-97`. Carrying all historical parser rows or merging names would duplicate or erase facts. |
| Relationship conversions, list traversal, release scope and consumer SQL dialect retain their meaning. | RELIED UPON; mapping proof open. | The registry includes `decimal_string_to_integer` and `shared_list_value`, while DDK's shared rule is `equal` with versioned `project_rule` for other semantics (`model-consumers.md:774,782`; `DDK/docs/specification.md:725-727`). Preserve the domain rule reference and the MCP's DuckDB SQL behavior (`apps/explorer_mcp/src/congressional_explorer_mcp/server.py:134-145`); relabeling everything as equality or changing dialect would change answers. |
| Selected/historical bindings, active work and raw evidence remain protected through retirement. | RELIED UPON; whole lifecycle unqualified. | `DDK/docs/specification.md:739`; `design.md:117-123`; `lake/maintenance.py:168-195`. A catalog reference alone does not protect underlying bytes. |
| Native job limits are not total process/capacity limits; materialization and candidate filtering must survive the conversion. | PRESERVED as a requirement; scale proof missing. | `AGENTS.md` §Archive ETL; `design.md:125-148`; F1/F2. Atomizing shared SQL or collecting whole native tables can increase reads/live memory despite a bounded component. |

## User value, smaller shape and counterfactuals

The target user value is unchanged trusted research behavior under a simpler
maintained definition/runtime structure: answers retain source scope and
multiplicity, exact historical keys still resolve, and interrupted work resumes
without repeating paid acquisition or expensive completed computation. The
proposed documentation supports that goal but does not yet establish it
(`design.md:11-16,85-130`; `acceptance-plan.md:23-36`).

The smallest useful shape is one DDK design for each actual publication/use case,
sharing maintained definitions and native operations. Reuse the current domain
parsers, native schema files, SQL, exporter settings, transport adapters and
accepted retained artifacts. Give missing durable execution capabilities to
DocSpec. Generate the existing consumer formats from DDK definitions after parity.
Remove replaced infrastructure only when all its callers and preserved fields
have destinations. There is no demonstrated need for another engine, a new
general scheduler, a universal plan, a corpus copy, or one managed operation per
CTE (`DDK/docs/runtime-integration.md:13-35`; `DocSpec/src/job/spec.rs:138-152`;
`design.md:109-130`; `archive_model.py:1042-1076`).

| Probe | Result |
| --- | --- |
| Kill criterion | If real supported data requires flattening away native IDs, export/reimport solely for DDK, unbound check evidence, fallback to latest, or a parallel retry/current-state store, this route violates its own requirements and must be reshaped (`DDK/docs/specification.md:609-623`). |
| Opposite decision | Keeping whole incumbent controllers behind DDK metadata would reduce immediate integration work and preserve current behavior, but fail the requested infrastructure replacement. Rewriting domain parsers would add semantic risk without addressing the demonstrated missing seams (`design.md:55-64,78-81`). |
| Removal probe | Removing these preparation documents breaks no current production consumer. That confirms design/proof status, not completed replacement. Removing the actual release schema would affect MCP identity/relationship discovery and the site/capture readers first (`docs/engine-first-data-model.md:769,845-881`; `apps/explorer_mcp/src/congressional_explorer_mcp/reader.py:24-48,95-103`). |
| Sibling subsumption | Existing DocSpec jobs/table operations, native checks, publishers and maintained domain logic already supply substantial behavior. Extend/adopt them; do not recreate their state/control policies in DDK. Catalog output is intentionally a generated description, not their replacement (`DDK/docs/specification.md:703-710`; F1–F3). |
| Six-month failure signal | The catalog looks complete while scheduled jobs still call the old controllers, a routine delta rereads the inherited population, a failed runner repeats source requests, or a new release invalidates exact historical reads. P05/P06/P07/P10 are the proposed falsification paths (`acceptance-plan.md:31-36`). |

Conceptual debt falls only when replaced handwritten definitions/controllers are
actually removed and native operations have one owner. Until then, a second
descriptive layer adds maintenance. The plan correctly makes that retirement and
real-consumer acceptance part of completion (`design.md:48-52,164-169`).

## Reasoning trace and evidence limits

| Hypothesis before inspection | Observation | Result |
| --- | --- | --- |
| H1: the proposal is only a catalog adapter. | Its scope explicitly rejects wrappers and requires controller/definition retirement and connected source-to-user evidence (`design.md:11-23,78-81,164-169`; `acceptance-plan.md:27-36`). | REFUTED as intended scope; actual replacement remains unimplemented. |
| H2: the released native profile can run the existing application with mappings alone. | Exact table pins, nested schemas, table operations, managed inheritance and evidence formats cross explicit profile restrictions (F1/F2). | REFUTED for the released profile; broader engine reuse is supported by inspected source. |
| H3: naming DocSpec as lifecycle owner settles acquisition and app activation. | Existing wrappers retain material phase state and application-specific authority; the target lacks invocation/adoption and per-workflow activation details (F3). | REFINED: ownership is sound, but the seam must be declared. |
| H4: missing proof means proven data loss or resource failure. | Every replacement proof is planned; retained reports refer to incumbent/historical results. | REFUTED. Restrictions are source facts; parity, capacity and recovery outcomes remain unverified. |

I read all seven proposed design/inventory artifacts, including the capability
inventories' behaviors/proof descriptions/gaps, parent normative/integration/
release documents, relevant source owners/callers and test bodies. The final
consumer inventory also separates current source additions from the narrower
retained e145 schema (`model-consumers.md:9-22`); an old release cannot qualify
those newer fields. I also read the named small
`r1b-frozen/README.txt` and historical publication `completion.json`. Their stated
hashes were not rechecked and their historical live claims were not treated as
current service observations. I wrote only this review. No source download,
corpus scan, payload replay, test, native job, build, Git history/index change,
shared-source edit, cleanup or publication was performed. No other reviewer's
conclusions were read.

The report does not independently verify every source/test citation in all 35
acquisition and 54 consumer rows, the whole expected corpus population, current
remote source/consumer behavior, historical custody, or runtime acceptance.
Source restrictions are high-confidence; the complete inventory of
source-to-consumer paths and executable seams remain unresolved as the final
inventories themselves state.

## Formal verdict

**RECONSIDER.** Keep DDK definitions/checks/catalog composition, maintained domain
meaning, and DocSpec execution/recovery/protection/selection. Finish the explicit
native application profile, mapping from checks to selection decisions, durable
acquisition protocol and per-workflow activation matrix described in F1–F3. Preserve F4's
unresolved populations and domain decisions as delivery obligations.

* Intent versus shape: **MATCHES the full objective; DIVERGES at the currently
  executable profile boundary.**
* User-value claim: **SUPPORTED as a direction; not delivered or qualified.**
* Commitments: **HONORED in policy; RELIED UPON at unresolved native seams.**
* Debt delta: **PAYS DOWN if existing infrastructure retires; ACCRETES if it only
  gains a DDK description or a second controller.**
* Sibling subsumption: **PARTIAL and useful**; reuse the existing native job and
  domain/publisher behavior.
* Confidence: **HIGH** in demonstrated profile limits and ownership findings;
  **MEDIUM** in whole-workspace completeness because wider-workflow detail and
  authentic evidence remain open.

## Re-review — November 6, 2026, operation-boundary revisions

Scope: the new `operation-seams.md`, revised ownership/gate language in
`design.md`, G09–G11 and nested compatibility in `runtime-gaps.md`, the expanded
43-capability acquisition inventory, corrected C45/C54 consumer records and the
new `native-profile.md`/`.json` binding inventory. I inspected the native
inventory's pins/schema records, graph structure, representative shared-step and
output specifications, check inventory and independently authored lifecycle
example. I did not independently re-render all 251 SQL steps or verify each of
the 678 dependency edges.

**Updated verdict: APPROVE the revised logical operation boundaries for the
already-authorized local definition and consumer work.** F1–F3 now have a concrete
target profile/protocol rather than only an ownership assignment. The small
design consistency actions below remain. This does not qualify the shared API, authorize a runtime
fallback, or close the full replacement. The initial findings above remain the
record of the earlier design; their implementation and acceptance observations
are not erased by a documentation change.

### What the revisions resolve

| Finding | Revised design evidence | Re-review result |
| --- | --- | --- |
| F1: exact inputs, schema and full job | `operation-seams.md:11-34` requires original native table pins, complete schema/field identity, protected access, the existing native job representation, materialized shared steps, original request identity and native-issued completion evidence. `native-profile.md:11-32,34-114,135-200` supplies the eight original selectors, complete recursive source schemas, 251 live steps, 40 output settings and native operation census. `runtime-gaps.md:18-31` separates the pin/protection bridge, accepted-evaluator restriction and nested compatibility support. | Addressed as a concrete extension request. Missing real version/group bindings stay `null`; original table pins remain authoritative. The native parent must return the actual protected mapping and supported operation semantics; current dev2 restrictions remain true. |
| F2: evidence and selection | `operation-seams.md:38-59` names the usual six native SQL families, complete output membership, exact rule/evaluator/scope binding, native acceptance and authority conditions. It separately retains existing publisher checks and exact external conditional activation. `native-profile.md:189` additionally identifies the required conditional `explorer_invariants` family. Unknown or wrong-bound evidence cannot select either result. | The two-boundary design is addressed. Reconcile the six-versus-seven check inventory and preserve existing admission timing as noted below. The runtime must still implement and qualify the new cross-table accepted-evidence path; the current Data Contract CLI-only profile is not relabeled as that capability. |
| F3: acquisition and activation | `operation-seams.md:63-84` defines admission before effects, request/tool/budget identities, sealed byte/occurrence completion, charged uncertain calls, acknowledgment reconciliation and adoption of prior journals without two active controllers. The workflow matrix at `:88-101` names separate visibility authorities, recovery actions and protection obligations. | Addressed as a logical protocol. No universal scheduler or global transaction is introduced. The supported backend, durable phase storage and tested invocation/adoption API remain implementation/profile obligations, particularly for host loss. |
| F4: source and consumer scope | `acquisition-lifecycle.md:31-58` now distinguishes all 21 declared console commands, eleven network-acquisition commands, derived handoffs and module/script-only gaps. A36–A43 add separate discovery, committee history, House fallback, Senate captions, overlapping detail windows and GPO continuation. `model-consumers.md:1161-1179` names the remaining full-scope populations and their owners. | Improved and still explicitly incomplete. The new rows are planned proofs, not source completeness or parity evidence. This no longer leaves those named branches hidden inside a generic output-preservation case. |

C45 now correctly requires Parquet success and explicit new-JSON refusal, while
keeping historical JSON partition readback/history migration separate
(`model-consumers.md:951,1163-1165`; `consumer-capabilities.json`, C45). This matches
the current export refusal previously inspected at `export.py:380-381`; it does
not revive the stale README's successful JSON-export claim. C54's four subcases
now identify source paths, actual incumbent assertion scope, independent
expectations and authentic-input gaps. None is presented as an executed
replacement result.

The new native inventory correctly distinguishes source declarations from
observed remote schema/custody, a named job relation from a managed native group,
and the current source graph from the older retained release/job
(`native-profile.md:26-32,102-114,214-226`). These distinctions prevent the exact
mapping work from inventing a local manifest or treating historical evidence as
proof of new fields. Preserving one shared native job and its exporter is the
smaller supported shape; nothing in the revisions justifies another engine or a
DDK-owned scheduler.

### Remaining design actions, distinct from missing implementation

1. Reconcile the required native check inventory. The full Explorer graph has
   **seven** blocking SQL families, including `explorer_invariants`, as the new
   inventory states at `native-profile.md:189`. Current source creates that
   report when `explorer_inputs` is present (`archive_model.py:1225-1233`) and
   the exporter refuses any nonzero diagnostic (`archive_format.py:333-336`).
   `operation-seams.md:40` and G09 must therefore include the seventh family for
   that closure, rather than admitting only the habitual six. Derive the exact
   required set from the declared conditional job scope and bind it to the
   native policy before selection.
2. Preserve the existing timing of input admission checks. The external
   activation row's reference to Gates 1–5 must not move an earlier check behind
   native selection. In particular, current Gate 5 verifies producer records
   for every input snapshot **before any model build**
   (`archive_publish_job.py:526-530`; `producer_proof.py:18-28`). Its accepted
   input evidence can be reused by publication rather than recomputed or moved.
3. Keep full DDK definition/recipe digests as provenance and relevant publication
   dependencies, then distinguish computation, qualification and catalog changes.
   The ownership proposal's fingerprint wording at `model-consumers.md:1187`
   must not make all catalog/recipe edits unconditional native computation
   dependencies. Retain the runtime-owned dependency separation required by
   `DDK-LOCK-005` and the metadata-only path already declared at
   `docs/engine-first-data-model.md:854-861`.
4. Resolve the CPI required-source/freshness/partial-year policy and complete the
   remaining source/window/consumer populations when implementing those
   workflows. `operation-seams.md:94-100` correctly labels preserve-prior-result
   behavior as proposed, not accepted parity. Choose the actual persistent phase
   authority/backend and its host-loss storage/protection configuration before
   migrating capture callers; runner temporary files remain insufficient.
5. Strengthen the planned explicit-empty example. The initial synthetic event
   `900000002` already has empty document collections, and lifecycle step `v3`
   again requests an empty replacement (`native-profile.json`,
   `/acceptance_example/row/meetings/1` and
   `/acceptance_example/lifecycle_sequence/3`). Give the prior A2 value a
   nonempty collection before `v3`, then require that explicit empty clears it
   while omission from a partial input preserves it. Empty-to-empty alone would
   not expose a stale-list implementation. This is a proof-design improvement,
   not a new architecture or release gate.

These actions belong to their affected workflow or profile. They do not block
the parent's authorized independent DDK definition/catalog/consumer
implementation, and they do not introduce another package-release prerequisite.

### Upstream implementation and qualification still required

The design now requests the right capabilities. It does not supply them:

* The DDK/native adapter must admit and protect the original table-pin scheme and
  retain exact nested type/field/element mappings, with supported compatibility
  checks. A rich catalog alone does not establish execution support.
* DocSpec must expose the requested retained multi-step/multi-output operations,
  update/correction/delete behavior and exact native SQL qualification. Its
  selection must enforce the admitted check inventory and current authority.
* Native durable acquisition must invoke the maintained adapter, preserve its
  phase/custody/budget facts, adopt historical state once, and reconcile the
  original operation after process and host loss. A wrapper that keeps the old
  state machine active would still fail F3.
* Each application's activation must use its real publication authority and
  exact complete membership. The upgraded tuple and actual consumers still need
  their missing acceptance cases. Reuse dev2's existing local package evidence
  where its identity/scope applies; do not rebuild that qualification merely
  because these additional capabilities need tests.

The native parent's N01–N06 decisions at `native-profile.md:228-239` are the
remaining supported API/profile choices and qualification work: protected remote
pin read/adoption, recursive mapping, durable shared-step/group binding,
append/correction/retraction semantics, native accepted evidence and the exact
runtime/client tuple. N07/N08 retain application custody and authentic acceptance
obligations. Naming these explicitly addresses the earlier architectural
ambiguity; it does not make the implementations available.

All 43 acquisition capabilities and all 54 consumer capabilities remain
unverified. Independent authentic checks, failure/cold-recovery evidence,
required full lanes and eventual infrastructure retirement remain full-delivery
obligations. No source download, payload scan, test, native execution, shared
source change or Git history/index change was performed in this re-review.

## Architecture reassessment — November 6, 2026, clarified simplification criterion

**Verdict: RECONSIDER the first implementation; remove the provisional bridge
from the target architecture.** The user requires DDK to standardize and simplify
the complete catalog-to-validation path. Reproducing the old registry through a
new compiler while retaining the old validation path does not satisfy that
criterion. Preserve the useful transcription, semantic expectations and domain
SQL as migration evidence. Do not extend this converter into the replacement's
permanent execution path.

This reassessment inspected the uncommitted `model/ddk/**`,
`archive_definitions.py`, changes to `archive_schema.py` and
`archive_model_profile.py`, and the relevant DDK APIs. It did not read the other
code review's conclusions. Code line references marked **draft** refer to the
uncommitted implementation as first inspected, before its withdrawal; key
mechanisms are described below so restoration of the files does not erase the
evidence.

### Findings against the inspected draft

**S1 — BLOCKER, intent versus shape: the increment adds a second metadata
compiler instead of retiring the old definition/checking path.**

The draft's default chain was:

```text
DDK authored files → build_catalog → 307-line archive_definitions compiler
    → old registry-shaped object → byte comparison with generated registry
    → incumbent validate_schema → incumbent native publication-check generation
    → incumbent documentation/reader formats
```

`archive_schema.build_schema` called the new `checked_archive_schema` and then
the existing `validate_schema` (**draft** `archive_schema.py:159-162`). The latter
still parsed the compact type language and checked paths, identities, cardinality,
join types and recipe references (`archive_schema.py:16-146`, retained after
withdrawal). DDK already resolves dataset aliases and checks field paths, key
components, cardinality, equality types and recipe dependencies in its catalog
assembly (`DDK/src/ddk/catalog.py:175-206,239-308`). The new compiler adds another
type/mapping validation layer before returning to those incumbent checks
(`archive_definitions.py`, **draft** `:73-110,130-171,196-297`).

This is not two independently authored copies of the old registry: the draft
intended that file to be generated. The problem is a retained runtime dependency
on that generated copy plus multiple implementations of the same declaration
rules. There is no demonstrated simplification of the current consumer path.
**RESHAPE:** consume the admitted standard catalog directly for a real maintained
discovery/checking consumer and remove the corresponding old current-path
definition checks in that same increment. Keep a narrowly named external-format
export only where an actual supported reader requires it. Do not delete native
data checks merely because a static DDK declaration check exists.

**S2 — BLOCKER, unnecessary compatibility machinery: object-member ordering has
become authored data and a runtime admission condition.**

The ODCS file contains **436 `legacyKeys` records**; this is a count of authored
metadata objects, not a performance measurement. They include the different
historical key orders `name/type/meaning/nullable` and
`name/type/nullable/meaning`, along with nested `name/type` records
(`model/ddk/archive.odcs.json`, `/schema`; examples at `:28-34,73-77`).
`registry_bytes()` explicitly preserves incumbent ASCII JSON spelling;
`_column` and table assembly reconstruct key order from those lists and reject
different key sets. The default wrapper then compared the entire generated byte
sequence with the old registry (**draft** `archive_definitions.py:25-27,98-110,
228-245,300-307`). Tests required the newly generated registry and Markdown to
have the frozen old byte hashes (**draft**
`tests/test_ddk_definitions.py:534-547`).

**REMOVE** `legacyKeys`, order-restoration checks and byte-for-byte old-registry /
old-Markdown requirements from the authored end-state. Use one deterministic
serializer supplied by the maintained catalog/output API. Preserve *semantic*
ordering: physical field positions, ordered key components, list element order,
meaningful source occurrence order and positional SQL parameter order. Those are
different from JSON object-member order. Old immutable releases retain their
original bytes and hashes; a newly versioned metadata output need not reproduce
the old file's whitespace, ASCII escapes or dictionary insertion order.

The frozen baseline is useful independent evidence. Retain it as an inert
historical fixture and keep semantic field/type/nullability/key/multiplicity and
consumer-result expectations. Do not make incidental formatting a requirement
that forces hundreds of new authored annotations.

**S3 — BLOCKER, broad invalidation: description changes invalidate expensive
model work.**

The draft added these dependencies to `_definition_hashes`:

```python
files += list((root/'model/ddk').rglob('*.json'))
files += list((root/'model/ddk').rglob('*.sql'))
# archive_definitions.py was also added to the hashed source list.
```

That hash inventory becomes `profile.file_hashes` and `profile_sha256`
(**draft** `archive_model_profile.py:85-101,124-143`). `input_digest` hashes the
whole profile (`archive_publish.py:106-124`), while continuation compares the
saved file hashes with the current inventory and raises
`PublicationInputsChanged` on any difference
(`archive_controller.py:113-118,308-335`). Thus a `recipeTitles` or explanatory-note
edit in `project.ddk.json` changes the model identity even when native input,
calculation and required data checks are unchanged. A dedicated draft test
required every DDK definition/recipe file to enter that model identity
(**draft** `test_ddk_definitions.py:612-619`). This establishes unnecessary
invalidation; no rerun timing or speedup was measured.

**REMOVE** the unconditional addition. Keep full input digests in provenance and
metadata publication identity, then use the maintained DDK change analysis to
identify affected definitions, checks and consumers. `impact_projects` accepts
base/candidate catalog snapshots, and catalog impact distinguishes computation,
requalification and metadata consequences
(`DDK/src/ddk/impact.py:316-333,411-429`;
`DDK/src/ddk/catalog_impact.py:235-250`). DocSpec still owns actual computation
keys and reuse decisions; DDK impact is not a substitute native phase key.
Use the existing metadata-only publication behavior when data remains unchanged
(`docs/engine-first-data-model.md:854-861`). A rule-only change must requalify the
same candidate; a description-only change must not discard completed model work.

**S4 — CONCERN, parallel representations: the adapter reinterprets authored
documents after DDK has resolved them.**

The compiler takes the catalog's admitted effective ODCS definitions, which is
the right direction, but rereads the root project and uses its raw artifact,
identity, relationship and recipe declarations to reconstruct the old format.
It also reopens and hashes all 16 SQL recipe files after DDK has already read
them (**draft** `archive_definitions.py:196-218,220-291`). The extra digest checks
protect those extra reads from mutation; they do not make the extra reads
necessary. No payloads are read, so this is metadata/control complexity rather
than a demonstrated large-I/O incident.

DDK's assembled catalog already has resolved `datasets`, `identities`,
`relationships`, `recipes`, `sourceInventory`, effective dataset definitions and
recipe companion identities. It holds the admitted SQL bytes during assembly
and emits companion files through its standard output path
(`DDK/src/ddk/catalog.py:288-308,329-357,479-486,604-617`).
**REDESIGN:** consume that assembled view and its admitted companions once.
Remove the raw-project reverse traversal, hard-coded root object/path assumptions,
and duplicate project/recipe reread checks. If the supported result API does not
expose admitted recipe bytes or companions for inspectable-but-unqualified
metadata, give that specific API need to the shared DDK owner; do not call private
assembly internals or add another local input loader. The existing shared API
only publishes the output directory on a passed result, so incomplete-result
access must retain its true evidence status.

**S5 — CONCERN, duplicated type/annotation machinery: author structure once and
keep domain facts separate from serialization recipes.**

The ODCS draft authors **72 composite `physicalType` strings** alongside their
recursive `items`/`properties`. `_check_property` reparses the old compact grammar
and checks that the two authored shapes agree (**draft**
`archive_definitions.py:55-95`; `archive.odcs.json:927-1006`). Exact scalar physical
types, binary widths, native IDs, nullability and ordering are required. A second
formatted composite language synchronized by application code is not the needed
authority. Keep one recursive physical schema owner, with DDK references and
supported mappings, and derive any old textual display type from it.

The project extension also contains parallel maps for identity scope/notes,
external labels, recipe titles/notes and positional restoration of contextual
relationships (`project.ddk.json:3521-3820`; **draft**
`archive_definitions.py:130-193`). Some facts are legitimate domain meaning that
must survive; the serialization/restoration scheme is incidental. DDK already
has fields for dataset title/row meaning, scoped identities, relationship
meaning/scope, recipe inputs/parameters/grain and external endpoints. Use those
fields first. The current recipe shape lacks title/notes and a distinct
informational-relationship list
(`DDK/schemas/0.1/catalog.schema.json:546-605`), so those are specific shared
catalog feature decisions if needed by real consumers, not permission for a
growing application-owned catalog dialect. Do not add an unread table as a recipe
input merely to satisfy relationship checking. Keep execution bindings distinct
from descriptive annotations; their historical array positions are not a new
runtime obligation.

### Concrete retain, redesign and remove decisions

| Decision | Artifact / behavior | Required result |
| --- | --- | --- |
| RETAIN | ODPS/ODCS transcription, stable dataset/relationship/recipe meaning, actual SQL files, frozen independent baseline | Reuse these facts and evidence; do not restart source research or erase preserved work. They remain provisional until the ownership switch is implemented. |
| RETAIN | `model/lake` physical schema/field-ID authority and maintained domain SQL/parsers | Preserve exact native meanings. DDK describes and checks the mapping; it does not invent replacement physical IDs. |
| RETAIN | Independent raw checks and actual native data invariants | These answer different questions from static declaration checks. Preserve them until a qualified maintained evaluator owns the same required behavior and evidence. |
| REMOVE from the end-state | All 436 `legacyKeys`, old JSON-spelling preservation and legacy Markdown byte-parity requirements | Deterministic new output plus semantic/consumer parity; byte identity only for retained immutable artifacts and explicitly versioned inputs. |
| REDESIGN, then REMOVE superseded code | `archive_definitions` reverse compiler and generic `archive_schema.validate_schema` current-path pass | Standard admitted catalog/check result consumed by a real reader. Delete old generic path/key/type/cardinality/reference logic when the corresponding supported DDK profile supplies it; preserve unresolved checks as unknown meanwhile. |
| REMOVE from the runtime path | Comparing newly compiled metadata with a separately stored generated registry | Consume the admitted catalog directly. A generated artifact can be optional review/distribution output, not another runtime input that must match incidental bytes. |
| REDESIGN | Docs and reader discovery | Generate/read the standard catalog. DDK already exposes `resolve_query` and `run_checked_query` for exact recipe bindings (`DDK/src/ddk/catalog_access.py:168-198`); do not recreate binding logic in the representation converter. |
| REDESIGN | Native footer, required-column, FK/cardinality and domain check composition | Put reusable exact-native/schema/quality behavior in the maintained DDK/DocSpec profile; keep congressional domain rules at their domain owner. Until that profile qualifies, existing safeguards remain, explicitly un-replaced. |
| REMOVE | Whole-DDK-tree model invalidation and its implementation-mirroring test | Full provenance remains; relevant runtime material dependencies, quality rules and metadata outputs have distinct identities. |
| RETAIN narrowly | Published v1 reader output and historical immutable readback where actual supported clients require them | One small versioned representation exporter/decoder at the external boundary, consuming canonical catalog facts. No parallel authored registry, validator, retry store or permanent reverse compiler. |

### Smallest coherent end-state and next increment

The maintained path should be:

```text
native schemas + DDK/ODCS/ODPS definitions + domain rules
    → supported DDK loader/checker/catalog API, one admitted input view
    → catalog-driven maintained consumer + native qualification through DocSpec
    → application release binding/activation
    → optional versioned external-reader representation and historical decoders
```

The next coherent increment should move one real discovery consumer to that
standard catalog and its explicit checking report, while deleting the old
declaration conversion/validation it replaces in that path. Suitable scope is
the maintained MCP discovery/recipe path, with selected-release schemas and exact
membership preserved; retain a small external format exporter only if a supported
client still requires it. Do not route the new consumer back through a recreated
old registry. Do not call definition compilation a replacement of native
qualification or the rest of the workspace.

The shared external-target loader defect is real and belongs to the parent:
`DDK/src/ddk/core.py:36-54` unconditionally accesses
`item['target']['dataset']`, while supported external targets have `external`
instead. The current catalog schema and catalog relationship reader explicitly
allow external targets (`DDK/src/ddk/catalog.py:245-248`). The application must
preserve them. **No workaround is recommended:** do not drop the relationships,
invent fake local datasets, catch the exception as a passing/incomplete result,
or bypass the public loader. The shared owner must repair and qualify the
released API. Any necessary reusable catalog metadata/native-check capability
also belongs there, rather than in another application compatibility patch.

The useful proof of simplification is concrete: a real consumer uses the standard
admitted catalog; old current-path parsing/conversion/checking code and redundant
authored fields disappear; metadata-only and qualification-only changes preserve
valid computation. Measure any claimed speed/resource improvement on the same
retained inputs with equivalent results. This static review establishes extra
layers, rereads and invalidation mechanisms, not measured runtime regression or
speedup. It adds no new release gate.

### Withdrawal observed; no implementation acceptance

During reassessment the parent accepted this direction and withdrew the default
wiring. A read-only Git diff then showed `archive_schema.py` and
`archive_model_profile.py` restored to baseline, and the unused
`checked_archive_schema` wrapper/default-wiring/hash tests removed. The remaining
compiler/definitions are being retained as an explicit opt-in migration
experiment. A subsequent static read confirmed `model/ddk/README.md:1-23` now
labels that state, retains the incumbent registry as current authority, and
removes the withdrawn default command/ownership claims. DDK is now a root
workspace dev dependency (`pyproject.toml:19-21,46`);
`viewer_publication/pyproject.toml` also has no remaining diff from baseline. No
production package dependency or runtime hook was accepted. I did not make those
changes or run their tests.

That is a withdrawal of the provisional runtime integration, **not acceptance of
the bridge, a completed ownership migration, or full replacement**. The new
`design.md:92-139` correctly makes simplification part of acceptance, requires a
real standard-catalog consumer and removal of superseded code, separates
computation/qualification/metadata, and preserves historical bytes without
freezing incidental new formatting. The corrected experimental README is now
consistent with that withdrawal.

Practical disposition: retain the experiment and its evidence, stop extending its
serialization dialect, obtain the maintained DDK fix/API decisions from the
parent, and implement the catalog-driven consumer plus concrete deletions as one
coherent change. The initial logical seam plan remains useful. It does not make
this provisional bridge the desired architecture.

Only this review report was edited by this reviewer. No tests, native jobs,
heavy scans, source implementation edits, shared writes, elevation, downloads or
Git history/index changes were performed.
