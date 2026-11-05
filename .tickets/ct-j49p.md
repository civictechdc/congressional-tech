---
id: ct-j49p
status: open
deps: []
links: [ct-mj9f, ct-sw5t]
created: 2026-11-04T15:05:25Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-gi01
tags: [nominations, model, source-parity, chaos-test]
---

# Show the committee chronology already supplied for nominations

A researcher opening a nomination should be able to see its supplied committee referral, hearing, markup and reporting actions. The selected nomination input contains those details for Charles Baldis, PN1011. Release `e145d24c389e` shows committee codes, latest action, transcript and floor votes but omits the committee chronology.

## Root cause (2026-11-05)

The pinned nomination input `d17c43e1bc6773cff17dc3ac6c7d79f5938ba9fa105a837e96deda23c91255f3` carries the actions and exact timestamp strings in `committees_json`. The input adapter keeps the JSON, but `entity-nominations.sql` extracts only distinct committee codes. The public schema has no activity field. The shared subject view also displays existing activity dates at day precision.

## Smallest useful change

Decode the structured data once from the pinned input with the existing model adapter path. Publish nullable `committee_activities` grouped by `system_code`, with a nullable list of activities containing the source `name` and exact `date` string. Align the type, aliases and missing-value meanings in the model and registry. Reuse the generic MCP read. Have the existing subject view display the supplied precision and separate committee actions from floor votes.

## Acceptance Criteria

- The native fixture and published schema retain all four PN1011 `ssga00` actions at their exact timestamps. The source lists Referred To at `2026-05-20T20:46:11Z`, Hearings By (full committee) at `2026-06-17T13:43:22Z`, Markup By at `2026-07-22T13:30:00Z`, and Reported By at `2026-07-22T14:47:05Z`. Preserve source order, repeated actions, nomination-part separation, and unresolved or unrecognized values. Check absent or unavailable versus explicitly empty at both collection levels.
- The selected release returns typed activities through nomination lookup and read-only SQL. Existing committee codes, transcript links and floor votes remain available. A voice confirmation without a roll call, such as PN247 or PN271, is still described as such. Committee activities establish the reported steps, with separate evidence required for tallies, ballots or a complete floor calendar.
- Record native fixture and candidate results separately from the final release ID and PN1011 readback through the installed reader and applicable site display.

## Coordination and evidence

Reuse the pinned nomination input and recompute the affected model outputs. Retained source values and consumer results are in `.cache/archive-release/chaos-personas-20261104/investigation-legislative/`. [ct-t915](ct-t915.md) owns the site integration, [ct-mj9f](ct-mj9f.md) other meeting and bill links, and [ct-sw5t](ct-sw5t.md) nomination transcript discovery. [Root-cause evidence](../docs/plans/production-mvp-root-causes-20261105.md).

## Notes

**2026-11-04T15:23:03Z**

Coordinated producer plan frozen 2026-11-04: docs/plans/congress-explorer-root-cause-remediation-20261104.md. This addendum refines remaining work without rewriting prior evidence. Live evidence remains release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd; source inspected at 730a2d8e0c55880fc058d13cc74d265fc315f41f. Planning/ticket update only: no implementation, tests, prepare, acquisition, data changes or publication.

Frozen interface/owner: nomination model and shared schema publish nullable committee_activities: List<Struct<system_code, activities>>, where activities is a nullable List<Struct<name,date>> and date preserves the source string exactly. Freeze field aliases/types together in model SQL/input adapter, normative schema/spec and registry before generic-reader checks. Preserve committee grouping, source order and multiplicity; NULL unavailable/absent differs from explicitly empty [], at both collection levels. Keep unresolved raw source evidence; no independent MCP JSON parsing or ad-hoc brace splitting.

The first loss is known: entity-nominations.sql:16-29 reduces committees_json to codes and final projection 86-100 omits activities. Use the already-pinned 95,904-byte nominations input; no acquisition, reference-history mirror or capture parser replay. Add the retained PN1011 four-activity fixture to maintained owning/native tests, plus committee-level absent/empty and unresolved fields. All four ssga00 labels and literal timestamps, including 2026-05-20T20:46:11Z referral, must survive. Do not truncate to date32, guess missing timestamps, collapse duplicate activities or merge nomination parts. Existing committee code, transcript and vote meanings remain; voice confirmation does not require a floor roll call, and no tallies or full calendar history is implied.

Exact nested shape/missingness semantics are the hard prerequisite to projection/registry/consumer edits. This model-only field preservation can proceed in parallel with other producers and upstream roster history. Reuse pinned inputs; regenerate nominations and only dependents whose declared inputs changed using the existing publication path. Closure separates source fixture/native schema+values, qualified candidate/gates, and actual stdio/site selected-release exposure.

**2026-11-05T20:18:06Z**

Integrated ordered nomination committee activities with publisher names and timestamp precision, displayed separately from floor votes. The retained PN1011 case and MCP readback preserve all four activities, with null and empty states distinguished. Combined-candidate and live acceptance remains due; the full build/publication is held for all waves.
