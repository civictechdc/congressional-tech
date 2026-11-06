# Independent architecture review

Latest status: the dated re-review at the end approves the revised logical
boundaries for authorized local definition/consumer work, with specific remaining
design actions and unqualified upstream capabilities listed separately. The
initial findings below are preserved as the earlier review record.

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
