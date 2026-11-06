# Native requests, qualification and application activation

This document reshapes the target boundaries after independent review. It is a
requested implementation protocol, not an assertion that the released DDK API
supports it. The parent owns the shared DDK/DocSpec changes. Current source
restrictions remain in `runtime-gaps.md`; exact pinned inputs and the materialized
step census belong in `native-profile.md` and `native-profile.json`.

## Exact native input and application job

The current archive supplies `native_table` inputs with metadata location, table
UUID, snapshot and schema ID. Those facts identify an existing native snapshot.
They must enter the requested profile unchanged, with their authority and complete
schema interpretation. The profile may resolve a protected native read view, but
cannot invent a local `VersionRef`, drop a group, reassign field IDs or export and
reimport the table merely to satisfy today's adapter. Any missing snapshot or
protection refuses explicitly. Never fall back to a table's current head.

The application supplies the declared materialized job graph, exact SQL bytes,
output layout, effective parameters and original input pins. DocSpec already has
job inputs/steps/outputs; use that supported representation for computation rather
than serializing each fragment through DDK's one-output fixture use case. Shared
steps remain materialized once. The required managed profile adds durable
admission, phase completion, exact output membership, recovery and selection to
the named operation families. Native reference and check profiles must explicitly
support the actual nested structures and field/element IDs.

Before submission, persist the original operation ID and request bytes with the
caller request artifact. A retry presents the same request and asks the native
owner what committed. An incompatible request under that ID refuses. A different
input snapshot is a distinct request; it does not erase useful prior completion.
The returned evidence identifies the admitted request, protected inputs, native
phase/computation identities, all known outputs, unresolved outcomes and exact
candidate. DDK records those references without computing competing phase keys.

## Which checks guard which decision

| Decision | Required candidate-bound evidence | Owning action |
| --- | --- | --- |
| Native archive input admission | Gate 5 producer proofs bound to every exact source snapshot, before model preparation/build (`archive_publish_job.py:526-530`, `producer_proof.py:18-28`) | Native/application admission validates the original proof inventory once; publication reuses this bound evidence |
| Native archive data selection | Complete output table membership and schema; six standard native SQL families: `invariants`, `model_invariants`, `url_state_invariants`, `profile_completeness`, `entity_profile_completeness`, `relationship_invariants`, plus required `explorer_invariants` when the Explorer closure is present; exact rule bytes, engine/evaluator identity, all required outcomes and checked scope | DocSpec accepts the complete conditional check inventory declared by the actual job, then selects only when accepted evidence and current authority conditions match |
| External archive release activation | Existing application gates, including explained value/cause changes, public-link continuity, supported access, schema/reader checks and actual candidate consumer evidence as defined by the current publisher; preserved Gate 5 admission evidence, exact candidate/release/asset digests and previous selection | Application publisher performs the existing conditional pointer operation and reconciles exact readback; DDK records the result |
| News availability and checkpoint advancement | Exact pins across required native tables/views, `check_corpus` result and independent semantic acceptance, completed fenced cycle and release membership | Native/news publication owner records availability before advancing the applicable source checkpoints |
| Weekly snapshot and committee-export visibility | Preserved raw snapshot, stable IDs/history and complete requested export/assets; old/new source-ref identity | Existing Git publication owner updates its bot-owned ref only after raw preservation; public browser deployment remains a separately evidenced action |
| CPI/Sheets-visible version | A coherent pair of CPI-grid and source-series files, provider/period/missingness diagnostics, independent value expectations and intended read binding | Application publisher owns the paired file revision; Sheets formulas read a recorded revision or explicitly documented mutable selection, never an assumed atomic live workbook |

The exact Gate 1–5 implementation and its required IDs remain authoritative in
`viewer_publication`; this table does not replace those rules with prose. The
replacement must enumerate them from their owner and retain any independent raw
checks. Post-selection checks are audit evidence unless the particular visibility
boundary deliberately waits for them. A native pass cannot impersonate uploaded
asset/read-path acceptance, and a browser receipt cannot qualify missing native
invariants. One complete candidate/release binding joins the two decisions.

Missing, duplicate, wrong-candidate, wrong-rule, stale, failed, unknown or not-run
required outcomes prevent the applicable selection. A qualification-only policy
change can reuse the computed candidate, with an explicit new policy request.
The hard-wired single-table Data Contract CLI gate in dev2 does not yet implement
this cross-table acceptance route. Keep both this restriction and the complete
Arrow materialization issue explicit; they require different fixes.

The parent-owned `docs/replacement-runtime-plan.md` further fixes candidate
composition and retry semantics: initially refuse a changed composition while
retaining useful completions; bind every check's complete target/reference view
set; retain the original publication attempt and authorization point. A completed
retry returns its historical result even after a successor is selected. It never
rewinds that successor. Unknown historical publication outcomes remain unknown
when current-pointer readback cannot settle the original attempt.

Record all authored definition and recipe digests as provenance/publication
inputs. Native computation dependencies remain the exact consumed schemas,
implementations and values required by that phase. Metadata-only recipe or
description changes require catalog regeneration; rule changes can require
requalification. Neither automatically invalidates expensive native computation.
The incumbent model profile remains its existing conservative compatibility
boundary until the successor runtime's narrower reuse identity is qualified.

## Durable acquisition request and completion

Maintain source-specific discovery, protocol interpretation and network adapters.
The proposed native acquisition phase must admit the exact scope/window, request
parameters, adapter/tool identity, bounded rate/spend/wire/spool/entity budgets and
original operation ID before the external effect. It invokes the supported domain
adapter and records its actual outcome; declared bindings alone are not execution.
The adapter's receipt semantics remain domain-owned.

A sealed completion names the original bytes or saved representation, storage
encoding, original digest, occurrence locator, writer/time/fidelity, prior attempts
and explicit refusal/pending state. Body and receipt acknowledgment loss must be
reconciled by their actual owner. An uncertain started network call remains
uncertain and charged; only the existing explicit retry decision can authorize
another call. Do not treat cancellation of the caller's wait as remote cancellation.

The greenfield caller starts new native operation state. It does not import
historical `DurableCapture` journals or old model/publication checkpoint formats.
A bounded input manifest can identify valid retained bodies, receipts and
completed results; old uncertain effects remain evidence without automatic
replay. Both process-loss and host-loss survival must be specified for new work:
runner temporary storage alone does not satisfy the latter. The new caller uses
one durable owner and preserves sealed completion and effect reconciliation.

## Per-workflow recovery and protection

| Workflow | Immutable request/completion identity | Recovery action | Visibility authority | Last protected consumer |
| --- | --- | --- | --- | --- |
| Archive capture | Exact selected capture scope + request/attempt ID; sealed downloaded body and frozen receipt | Inspect the original native phase; read back original body/receipt key after acknowledgment loss; refuse unknown started call | Raw create-only receipt owner; capture is not model publication | Pending interpretation, provenance and recovery obligation |
| Archive model/release | Frozen input table pins + SQL/definition identities; complete candidate and export receipts | Resume valid native materialized steps, qualification and exports; reconcile exact external pointer/ETag | Native dataset authority then application publication authority | Selected and prior new-stack versions, rollback pins, source-link obligations |
| News | Source/page checkpoint + cycle/attempt/fence; exact native dataset pins and manifest | Inspect original cycle; do not reopen closed checkpoint or repeat accepted data commits; recover availability then cursor activation | Native/news control owner with its existing fence | Selected/unretired release, pending cursor activation and current readers |
| Weekly/committee | Source snapshots, stable-ID/history state and exact export file inventory | Read back preserved raw snapshot and original ref outcome; retain prior ref if preservation failed | Bot-owned `pipeline-data` ref and separate site deployment selection | Current reports, historical ID/state readback and unpublished snapshot recovery |
| CPI/Sheets | Provider source periods and retained responses when available; exact two-file revision and formula definitions | Preserve prior complete published revision on failed/incomplete required refresh; reconcile its published revision before retrying | Application file publisher; workbook owner for any later live formula update | Current/historical time-series interpretation and documented spreadsheet consumers |

These are independent product boundaries. They do not require a global release,
shared transaction across products or a new scheduler. The current CPI all-source
failure/partial-column behavior and missing raw retention remain unresolved policy
and evidence questions. Preserve that observation; do not silently call either
the source behavior or the proposed preserve-prior-result rule accepted parity.
News offline adapters remain offline unless acquisition is explicitly supplied.

No production effects are authorized by this specification. Local test doubles
and retained authentic exchanges can exercise each boundary; actual external
publication and live Sheets updates require their separately authorized workflow.
