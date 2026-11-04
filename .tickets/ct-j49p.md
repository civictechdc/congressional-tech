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
# Preserve supplied nomination committee activity dates in the public nomination record

The pinned nomination input already supplies committee referral, hearing, markup and reporting activities, but the public nomination record drops them. Users reading a nomination can see its committee codes and latest action without the supplied committee chronology. Related meetings can recover some dates, but do not replace the source activity list.

Verified on release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd, follow-up cases P5Q1/P5Q7. For 119-pn-1011 (Charles Baldis), pinned upstream nominations generation d17c43e1bc6773cff17dc3ac6c7d79f5938ba9fa105a837e96deda23c91255f3 retains committees_json for ssga00 with Referred To (2026-05-20T20:46:11Z), Hearings By (full committee) (2026-06-17T13:43:22Z), Markup By (2026-07-22T13:30:00Z), and Reported By (2026-07-22T14:47:05Z). The public record contains committees=[ssga00], transcript CHRG-119shrg64122, and two floor votes, with no committee activities field. Meetings 338565 and 338666 independently locate the hearing and business meeting.

This is a confirmed supplied-field loss, not evidence of missing committee vote tallies or complete floor scheduling history. The inspected upstream table has neither tallies nor a complete action/calendar history. Missing floor roll calls cannot imply no floor consideration: PN247 and PN271 were confirmed by voice vote.

Narrow reproduction: inspect the named pinned nominations.parquet row's committees_json; compare get_dataset_info(table='nominations') and query_sql SELECT nomination_id,committees,latest_action_text FROM nominations WHERE nomination_id='119-pn-1011'. Inspect entity-nominations.sql committee_chunks/committee_extracted/committees_agg and final SELECT, which reduce committees_json to committee codes.

Evidence: .cache/archive-release/chaos-personas-20261104/investigation-legislative/baldis-upstream.json; calls.jsonl calls 1,10,14,24,25; voice-vote-upstream.json; report.md. The 95,904-byte pinned input is .cache/archive-release/r1b/inputs/spicy_regs/generations/nominations/d17c43e1bc6773cff17dc3ac6c7d79f5938ba9fa105a837e96deda23c91255f3/nominations.parquet. Source inspected at HEAD 730a2d8e0c55880fc058d13cc74d265fc315f41f; this source revision is separate from the served release.

## Design

Owner: archive nomination modeling and published schema metadata: model/sql/entity-nominations.sql, packages/viewer_publication/src/viewer_publication/archive_model.py as needed, model/registries/release-schema.json, and existing generic readers/consumers. Preserve the supplied activity name, committee identity and date/time precision in a typed published collection using the maintained schema/reader path. Keep committee codes, hearing packages and floor votes distinct. Do not fetch new upstream data or create a new complete procedural-history service for this repair.

No blocking ticket dependency established: the pinned input already holds the required values. Related context: ct-mj9f covers meeting subject links and bill activity modeling; ct-sw5t covers nomination transcript discovery. Neither ticket covers this nomination field loss.

## Acceptance Criteria

- A fixture from the retained PN1011 source preserves all four supplied committee activities, ssga00 identity, exact labels and source date/time precision through the native model output and published schema.
- Published nomination lookup and read-only SQL expose the same typed activities through the maintained generic reader; existing committee codes, transcript references and floor votes retain their meanings.
- Missing or empty activities remain explicit source availability, with no inferred votes, floor scheduling or no-action claims. A negative control with no floor roll calls and a voice-confirmation latest action remains correctly described.
- Validation distinguishes local/model evidence from a new release actually consumed by MCP/site. Record final release identity and replay PN1011 when delivered; do not call an unchanged live release repaired.
- No committee tally, individual ballot or complete floor scheduling-history claim is added by this change.


## Notes

**2026-11-04T15:23:03Z**

Coordinated producer plan frozen 2026-11-04: docs/plans/congress-explorer-root-cause-remediation-20261104.md. This addendum refines remaining work without rewriting prior evidence. Live evidence remains release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd; source inspected at 730a2d8e0c55880fc058d13cc74d265fc315f41f. Planning/ticket update only: no implementation, tests, prepare, acquisition, data changes or publication.

Frozen interface/owner: nomination model and shared schema publish nullable committee_activities: List<Struct<system_code, activities>>, where activities is a nullable List<Struct<name,date>> and date preserves the source string exactly. Freeze field aliases/types together in model SQL/input adapter, normative schema/spec and registry before generic-reader checks. Preserve committee grouping, source order and multiplicity; NULL unavailable/absent differs from explicitly empty [], at both collection levels. Keep unresolved raw source evidence; no independent MCP JSON parsing or ad-hoc brace splitting.

The first loss is known: entity-nominations.sql:16-29 reduces committees_json to codes and final projection 86-100 omits activities. Use the already-pinned 95,904-byte nominations input; no acquisition, reference-history mirror or capture parser replay. Add the retained PN1011 four-activity fixture to maintained owning/native tests, plus committee-level absent/empty and unresolved fields. All four ssga00 labels and literal timestamps, including 2026-05-20T20:46:11Z referral, must survive. Do not truncate to date32, guess missing timestamps, collapse duplicate activities or merge nomination parts. Existing committee code, transcript and vote meanings remain; voice confirmation does not require a floor roll call, and no tallies or full calendar history is implied.

Exact nested shape/missingness semantics are the hard prerequisite to projection/registry/consumer edits. This model-only field preservation can proceed in parallel with other producers and upstream roster history. Reuse pinned inputs; regenerate nominations and only dependents whose declared inputs changed using the existing publication path. Closure separates source fixture/native schema+values, qualified candidate/gates, and actual stdio/site selected-release exposure.
