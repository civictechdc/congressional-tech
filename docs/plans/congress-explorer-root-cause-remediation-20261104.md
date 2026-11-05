# Congress Explorer: coordinated root-cause remediation

Status: implementation plan, November 4, 2026. No repair, acquisition, backfill,
build, publication, client refresh or deployment was performed while preparing
this plan. Existing tickets remain the work and completion records.

The plan addresses nine observed problems through their existing owners. The
goal is trustworthy answers about participation, evidence and coverage, rather
than another data model or qualification framework. Preserve raw evidence and
uncertainty; make shared decisions once; verify user-visible results from the
release the reader actually selected.

## Decision and inherited constraints

Keep the native producers, one congressional-tech model/publication, generic
MCP readers, maintained site reader and existing five publication gates.
SpicyRegs continues to own its reference data. These boundaries are declared in
[the data model](../engine-first-data-model.md), especially §§2, 6, 7.8, 7.11 and
8.4, and [the phase-2 annex](phase-2-annex-20261028.md), §§4.2–4.7.
The annex's historical implementation claims do not establish that the newly
observed residual defects are repaired.

Three GPT-6.1 Sol agents at extra-high reasoning effort proposed and reviewed
the producer, query and acceptance workstreams together. Their source baseline
was `730a2d8e0c55880fc058d13cc74d265fc315f41f`. Retained live evidence names
release `e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd`.
Implementation must recheck current source, input pins and selected release.
Neither source changes nor reinstalling the MCP repair an immutable old dataset.

The investigation and its corrections are retained under
`.cache/archive-release/chaos-personas-20261104/`. Important corrections remain:
raw amendment labels are not bill IDs; superseded source records are not extra
people; a recording locator is not held footage; a date span is not completeness.
No corpus-wide defect rate follows from the inspected examples.

## Shared decisions

### Preserve the source's scope

A multi-date printed volume does not assign every witness to every sitting.
Keep package-wide MODS appearances package-scoped unless existing
occurrence-specific evidence identifies the individual sitting. Do not add the
per-day reconstruction deferred by annex §4.2. Explicit House/Congress.gov
meeting observations retain their own support.

Changing an appearance's occasion changes its occurrence-v2 witness key. Keep
the source occurrence and record the old/new key and affected document-witness
link dispositions. Do not promise unchanged keys, drop observations to repair
counts, or invent witness redirects. The public document-link rule is separate.

### Publish recording associations once

Add one field to the existing `recording_matches` observation table:

```text
meeting_links: list<struct<event_id: int64, basis: dict, scope: dict>>
basis: direct_event | print_agreement
scope: event | package_context
```

The recording model owns the resolution. It uses existing direct evidence and
the vetted print-agreement path. Preserve `match_id`, original subject,
`event_id`, `package_id`, URL/video identity, decision, status, recording scope,
note and source reference. Association scope does not replace full/excerpt
recording scope. Sort and deduplicate association tuples, not distinct source
observations sharing a URL.

`event` requires support that this observation applies to the named sitting.
`package_context` means the print supports the context but the recording's
applicability to that sitting is unresolved. A multi-sitting print alone cannot
promote its recording to every event. An empty list means no supported
association, not proof that no recording exists.

Coverage, recipes and the existing site detail read this same interpretation.
Coverage applies its existing decision/state rules only to qualified event
associations; package context alone cannot establish present, full coverage or
confirmed absence. Recipes can expose a related package locator with its scope
and provenance without claiming that it covers the sitting. Return each
observation once per request, retaining distinct conflicting observations.

Do not reconstruct this relationship in MCP SQL from all `meetings.transcripts`.
That published list includes a no-MODS jacket fallback and omits the stronger
association basis (`entity-meetings.sql:47–54`). It is not equivalent to
`package_meeting_links`/`print_meeting_agreement`. The internal model relation is
also not an MCP table. The new field makes the supported meaning available to
readers and requires a data-bearing release.

For Altman event `334136`, qualify the retained curator/day evidence and package
`CHRG-118shrg52706` before selecting event scope. If that evidence is insufficient,
publish package context rather than force a successful event match.

### Keep current display separate from retained history

The appearance model's `superseded_by` is authoritative. Default dossier and
meeting lists use current occurrences; exact historical keys still resolve and
source rows remain available. Testimony counts can additionally exclude member
statements or statements for the record under their existing stated policy.
That is a different question from whether an occurrence is current.

Use short explicit predicates over the published fields. Do not introduce a
general policy engine or merge genuinely distinct appearances by name.

### Preserve supplied activity structure and uncertainty

The nomination projection adds a nullable, committee-grouped
`committee_activities` collection with `system_code` and nullable `activities`;
each activity preserves its supplied `name` and exact `date` string. Preserve
order and multiplicity. A missing group/list, an explicitly empty list and an
unrecognized source value require different dispositions. Do not flatten away
the committee context, truncate to `date32`, or infer a timestamp precision.

Record the exact field names, Arrow types and source availability meanings
together in the model, data-model reference and registry before coding the
projection. Use the maintained structured-input adapter; do not independently
parse upstream JSON in the MCP. These activities do not supply committee vote
tallies or complete floor scheduling history.

## Work packages and ownership

| Ticket / owner | User-visible result and smallest change | Decisive check / prerequisite |
| --- | --- | --- |
| [ct-dx22](../../.tickets/ct-dx22.md), appearance model | Prevent wrong hearing timelines by leaving multi-date package witnesses unresolved unless a sitting is supported. Keep document/recording package links separate. | Two-date print: Farmer/Reese cannot attach to June 2 solely from the package; explicit sitting source remains valid; source occurrences and changed keys are accounted for. |
| [ct-lx67](../../.tickets/ct-lx67.md), shared witness extraction | Keep job-title clauses out of organization grouping. Prefer supplied structure; retain uncertainty when a flat line cannot support a boundary. | Independently read Farmer/Reese source lines, normal title, comma-containing employer and ambiguous line. Prove actual parser digest/replay scope before reuse. |
| [ct-j78x](../../.tickets/ct-j78x.md), recording model and registry | Make supported recordings discoverable through consistent coverage, dossier, recipe and site paths using `meeting_links`. | Qualified package-only and direct-only cases; duplicate traversal; conflicting observations; multi-date context; wrong sibling/jacket fallback; unknown/missing evidence. |
| [ct-9479](../../.tickets/ct-9479.md), registry and default reader lists | Stop double-counting superseded witnesses while retaining source history and genuinely repeated occurrences. | Superseded pair plus distinct occurrences; exact superseded key; separate statement/testimony policy; published schema rather than only the existing local filter. |
| [ct-j49p](../../.tickets/ct-j49p.md), nomination projection | Expose referral/hearing/markup/report dates already present in the pinned input. | PN1011's four supplied activities, exact date precision, null/empty and repeated entries, nomination-part separation. No new acquisition prerequisite. |
| [ct-nh41](../../.tickets/ct-nh41.md), recovery decision authoring | Give users a supported identity explanation or an honest null, rather than pipeline provenance in an explanatory field. | Preserve kind/body/URL/attachment/provenance. Verify append/supersession identity before correcting the exact legacy sentinel cohort; no immutable record overwrite. |
| [ct-717p](../../.tickets/ct-717p.md), source admission investigation | Explain and resolve why Rules event `118300` is absent from committee-record input despite retained document links. | First trace the one frozen receipt/capture/parser/stage/selection chain. Choose a fix only after the first missing boundary is known. Compare all 31 CA links in both directions; numeric ordinals cannot become bill IDs. |
| [ct-m94a](../../.tickets/ct-m94a.md), date derivation/publication | Prevent modern or suspect filename values from becoming unqualified historical coverage. Finish existing qualification and its delivery. | Preserve literal readings and accepted/suspect/undated/unresolved distinctions; independently verify bounds, counts and source meanings. Re-extract only proven stale readings. |
| [ct-mx3g](../../.tickets/ct-mx3g.md), coverage metadata | Tell users that the selected roster data is 119th-only without waiting for acquisition. | Metadata agrees with actual populated Congresses; local corrected wording is distinguished from the selected release. |
| [ct-8cno](../../.tickets/ct-8cno.md), pinned upstream roster integration | Enable historical roster comparisons when upstream dated data actually exists. | Requires the maintained upstream `ss-ehci` generation and a verified new pin, then archive parity and reader checks. Do not revive the retired prototype or fabricate 112th-Congress data. |

`ct-gi01` coordinates source inventory, candidate contents and disposition of
retained facts. `ct-m104` owns actual-release MCP acceptance; `ct-t915` owns site
meaning and navigation. Existing `ct-tk10` gates remain the publication mechanism;
this plan does not reopen that completed machinery or add a sixth framework.

## Coordination and dependency order

1. **Prove the changed meanings on compact retained inputs.** Work on appearance
   binding, affiliation, recording associations, nomination activities, recovery
   authoring and coverage fixtures can proceed independently. The `118300` trace
   precedes its repair choice. Historical roster integration waits for upstream
   data; truthful wording does not.
2. **Integrate shared schema and readers deliberately.** One editor integrates
   `release-schema.json`, model step/export declarations, generated references
   and shared native fixtures after each owner has supplied its field meaning
   and expected values. Shared-file serialization is not a semantic dependency
   between unrelated fixes. Nomination missingness/precision and recording scope
   must be agreed before their producer and consumer changes are joined.
3. **Build only qualified release contents.** Recording recipes need the emitted
   association field. A metadata-only release cannot deliver it. A completed
   independent correction may ship without waiting for roster acquisition or
   an unresolved admission investigation; excluded work stays explicitly open.
4. **Verify the delivered selection.** Candidate qualification, an authorized
   publication, installed selection and live site readback are separate actions
   and evidence. The current planning request authorizes none of those runs.

Task dependencies represent actual prerequisites and final acceptance, not a
requirement to serialize all investigation or to build one giant repair branch.
Do not add a dependency merely because tickets mention the same dossier. Preserve
the existing umbrella/child ownership and keep the graph acyclic.

The final consumer-acceptance tickets `ct-m104` and `ct-t915` depend on `ct-j78x`
and `ct-9479` for the promised recording/current-appearance behavior. These four
edges do not make unrelated producer work wait. `ct-mx3g` does not depend on
historical roster acquisition; `ct-8cno` retains its external upstream prerequisite.

## ETL reuse, invalidation and recovery

- Reuse the pinned source bodies, metadata, raw audits, nomination input,
  recovery inventory and valid completed stages before any new read or copy.
  Two witnesses demonstrate a defect, not a safe selective-replay predicate.
- A `witness_names.py` change currently belongs to the MODS digest closure.
  Verify the actual closure at implementation time. With a proven exact affected
  predicate, reuse unaffected rows; otherwise measure a MODS-family replay from
  retained bytes. Do not invalidate every appearance family by assumption.
- A binding/model-only correction does not automatically require reparsing raw
  appearances. Nomination projection reuses its pinned upstream input. Recovery
  note correction reuses body evidence and changes metadata through the existing
  authored-decision supersession path, not body downloads or a full reconciliation.
- Select one applicable parser version per body/source before joins or
  re-stamping. Intentionally changed parser bytes require the maintained parser
  pins and `publish.json` model-spec hash/size updates. Reconcile authoritative
  lake/catalog inputs used by the next incremental run as well as the candidate.
- Preserve binary candidate-SHA joins before aggregation. Account for inherited
  validation/export reads even if extraction is selective. Record actual input
  identities, bytes, rows, work performed, wall time, process-tree RSS and scratch.
  No speed, memory or replay-duration improvement is claimed by this plan.
- Heavy work uses `archive_watchdog.py` with expected peak from relevant retained
  measurement, a deliberate kill limit, `--start-available-gb 6` and
  `--interval 0.2`. Read the actual engine pin and local limits before execution;
  the engine pool is not a process RSS limit. Budget overlapping native threads,
  Python workers and export buffers. Unknown costs require a bounded preflight,
  not guessed thresholds or an automatic full-corpus replay.
- Keep reusable inputs/candidates under the main checkout's
  `.cache/archive-release/`. Resume identity-valid stages and retain the selected
  and previous releases, source evidence and rollback references. Remove only
  owned disposable scratch after its consumers finish.

## Acceptance at three boundaries

| Boundary | Required proof | What it does not establish |
| --- | --- | --- |
| Source-local semantics | Expected facts derived independently from the retained source; wrong-value plant; nonauthor confirmation; expected-to-output and output-to-expected comparisons; named unread and unresolved records. | That a release was built, published or selected. |
| Candidate/publication | Real native output and typed schema, affected invariants, per-key/field cause records and identity changes, producer proofs, existing gates 1–5 and preserved public document links. | That the installed MCP or site selected the candidate. |
| Installed reader/site | Actual discovery/recipes/records over stdio and built-site navigation against the same release identity; available/unknown/absent and evidence links remain truthful. | Complete historical coverage, held footage, or repaired values in older immutable snapshots. |

Extend existing owner fixtures and raw checks rather than create another testing
system. A raw check must obey repository independence rules: no producer/parser
imports, model SQL or registry oracle; use independent facts or a distinct
measure. A test that merely restates the rule is insufficient. Scope independent
auditing to the changed semantic family and reuse identity-bound accepted proof;
do not require a fresh manual audit of the entire corpus for every release.

Witness-key changes and derived document-witness links belong in gate-1 cause
evidence. Gate 2 protects public document references and does not itself verify
appearance identity. Keep those responsibilities distinct. Use the existing six
model invariant suites for changed model generations; apply
`capture_backfill_guard.validate_generation` when its capture-generation scope
is actually implicated. That guard cannot validate raw extraction semantics.

The native fixture and reader checks cover the following user questions:

- Who appeared at this sitting, for which organization, and which source supports
  the assertion? Ambiguous package appearances remain visible without a false date.
- Which current appearances are shown, and can an exact retained historical key
  still be inspected without inflating default counts?
- What recording evidence applies to this event, versus related package context,
  and what is unknown about captions, media custody and present-day availability?
- Which nomination activities and date precisions were supplied?
- Is this recovery an original, substitute or related material, and what evidence
  or absence of an explanation supports that description?
- What roster/date coverage does this exact release contain, and what remains
  unavailable? A missing optional table must not erase the core hearing view.

## Maintained verification routes

These are future execution routes, not results from this planning task. Use each
checkout's own frozen environments and local-only pinned runtime as required by
`AGENTS.md`. Run heavy commands through the watchdog after its measured resource
inputs are established. A filtered/path/shard run remains partial; only a full
lane exit 0 or all shards establishes full-lane success.

- Run the affected producer/model fixtures first through
  `.venv/bin/python scripts/dev.py test production-offline --path ...`.
  Reuse the four fixture paths in
  `.github/workflows/validate-congress-mcp.yml:69–83`: phase-2 entities,
  `test_phase1_model_profile.py`, `test_archive_maintenance.py` and the repaired
  filename publication test. Put their retained native outputs under the main
  checkout's archive-release cache. Give each producer attempt a fresh owned
  subdirectory: pytest recursively removes an existing explicit `--basetemp`.
  Never reuse the accepted attempt's path while stdio/site or a later run still
  needs its outputs. Reuse those completed outputs directly, not by rerunning
  their producer into the same directory.
- Sync the independent MCP environment with its own lock, then use
  `apps/explorer_mcp/.venv/bin/python scripts/dev.py test explorer-mcp --path
  apps/explorer_mcp/tests/test_native_release.py -- --native-fixture-root ...`
  against that real output. Run the full relevant lane for final integrated
  qualification. Keep the root producer's DuckDB environment separate.
- Registry changes use `.venv/bin/python -m viewer_publication.archive_schema
  --check`, generated-reference checks and maintained recipe tests. The new
  recipe can reference only fields/tables in its own published release.
- Site changes use focused `test:archive-unit` or the broader `test:explorer`
  script, which already includes that reader unit file; run
  `test:archive-native` when its boundary changes, then
  `npm --prefix apps/site run contract:archive-ci -- --work <absolute-retained-dir>`.
  Install the exact pinned Playwright/browser as instructed in `AGENTS.md`.
- A broad integrated producer/model or release-gate change requires the
  maintained full `production-offline` lane or all declared shards after decisive
  focused checks. Reuse unchanged qualification and recovery evidence. Publication
  still uses the existing gate path, cause comparison, input/catalog continuity
  and rollback records; authorized readback uses maintained contract/canary tools.

Older releases keep their original data and examples. Readers may explain their
limitations and use their supported existing fields; they must not fabricate the
new associations, silently refresh selection or claim that a local filter has
changed the selected dataset. Record the chosen old-schema behavior explicitly.
Current site performance ceilings remain deferred under their existing decision;
this plan neither invents a service objective nor reactivates that gate.

## Completion and scope limits

Each ticket records source-local, candidate and delivered evidence separately.
Close an outcome only at the level its acceptance promises. `ct-gi01` retains the
inventory and named unresolved work; `ct-m104`/`ct-t915` establish reader results;
the existing live-switch owner records publication/rollback separately.

This plan adds no global text index, OCR, person/organization identity system,
full attempt-history service, complete floor calendar, new source crawl, alternate
engine, scheduler or licensing inference. Those capabilities are not repairs for
the nine observed problems. No implementation or publication authority is implied
by updating the plan and tickets.
