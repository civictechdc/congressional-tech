---
id: ct-j78x
status: open
deps: []
links: [ct-9479, ct-adoh]
created: 2026-11-04T15:05:50Z
type: bug
priority: 2
assignee: mikewolfd
tags: [mcp, recipes, recordings, chaos-test]
---
# Include package-linked recording observations in meeting recipes

When callers follow the published hearing_dossier or meeting_recordings recipe, a hearing can appear to have no recordings even though meeting_coverage reports a present recording and the release contains its original locator.

Retained reproduction on release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd, 2026-11-04: event 334136 (Sam Altman, May 16, 2023) links printed-hearing package CHRG-118shrg52706. meeting_coverage has recording state=present/count=1. Both published recipes filter recording_matches by event_id only; hearing_dossier returns recordings=[] and meeting_recordings returns zero rows. The recording observation instead has subject_kind=package, package_id=CHRG-118shrg52706 and event_id=NULL, with URL https://www.senate.gov/isvp/?comm=judiciary&filename=judiciary051623, basis=curated, decision=found_offsite, recording_scope=full and status=decided. Its note records a September 2026 Senate archive probe; it is a locator observation, not proof that media or captions are held.

Recording association belongs to the native recording model; model/registries/release-schema.json owns the published shape and recipe meanings. Current checkout 730a2d8e0c55880fc058d13cc74d265fc315f41f still has the event-only filter in both recording recipes. model/sql/entity-meeting-coverage.sql:5-11 already combines direct event observations with package observations through package_meeting_links. That maintained mapping uses print_meeting_agreement, rather than a bare jacket/event-number guess, and can support multiple meetings when the print independently supports each.

A bounded exposure query found 2,934 package-only observations across 2,599 uniquely transcript-linked meetings, including 2,540 full-scope observations. These are candidate exposure counts, not a verified defect total, distinct recording count or absence of other direct observations.

Exact retained tool arguments, responses and timings: .cache/archive-release/chaos-personas-20261104/investigation-discovery/calls.jsonl, M5/M7/M9 (coverage/package evidence), M19/M20 (immutable published recipe SQL), M23/M24 (recipe replay), M32 (candidate exposure). Related cases P8Q1/P8Q4/P8Q10 and P7Q8. This is distinct from superseded-witness ticket ct-9479 and from closed recipe-authoring ticket ct-adoh.

## Design

Frozen coordinated plan: [Coordinated root-cause remediation plan](../docs/plans/congress-explorer-root-cause-remediation-20261104.md). This ticket is a model/schema/consumer change, not a recipe-only metadata patch.

- Add one field on existing recording_matches: meeting_links: List<Struct<event_id int64, basis dict, scope dict>>. Association basis is direct_event or print_agreement; association scope is event or package_context. Lists are non-null, deterministically ordered and unique by the full association tuple. Every target resolves to a published meeting. An empty list means no supported association, never no recording.
- One native recording-model resolver consumes existing direct event evidence and vetted package_meeting_links. Publish its result and remove the private coverage association copy; coverage, published examples and actual site meeting-detail consumption use the same field. The internal package_meeting_links CTE is not an MCP table. meetings.transcripts includes a no-MODS jacket fallback without retaining its proof basis (entity-meetings.sql:47-54), so a bare transcript-package join is not an equivalent repair.
- Preserve match_id and every original observation field: subject_kind, event_id/package_id, URL/video key, basis, decision, status, recording_scope, note and source_ref. Association scope differs from a recording's full/excerpt claim. Repeated traversal of one observation does not multiply it; separate match_ids sharing URL/video key remain visible with their distinct provenance/conflicts.
- A print's supported multi-meeting membership can yield package_context links, but it does not establish that a recording covers every sitting. Coverage applies its existing verdict/state policy only to qualified event-scope links. Package-context locators remain returned and labelled related; they cannot promote per-event present/full or confirmed absence. Unknown, claimed, unresolved, conflicting and excerpt semantics remain explicit.
- The Altman observation is a qualified target, not a forced pass: retain match b0ac3d1823bf0deacb479b9b3b6ab17e4cb45299e2bc74e8b3c13ea3b64912b3, source_ref recording_decisions:b7680266fc4c839db86369c34690312859a60cacc6f42e7851b949736af97b77 and curator/day evidence for judiciary051623, together with the vetted package/meeting evidence. If those facts cannot justify event scope, return explicit package context/unresolved scope. No new acquisition or per-day parser is included.
- hearing_dossier and meeting_recordings use the published association field with bounded parameterized SQL and include match_id, association basis/scope and original provenance. Reuse the existing site reader/detail path where it consumes recordings. Static source inspection identifies its current video precedence and merge loops; this is a planned migration, not a new live browser failure claim. Preserve retained tracks separately from locator observations.
- Update normative data-model/phase-2 field meaning, native export typing/dictionaries/invariants, registry relationships/requires, generated documentation and maintained fixtures together. This changes recording_matches bytes and needs a data-bearing candidate/release; it cannot claim the metadata-only relationship_metadata_update route. On an older schema without the field, mark resolved associations unavailable instead of normalizing absence to [] and claiming none. Original event/package observation lookup remains available without fabricated associations. No generic relationship engine or second MCP model.

## Acceptance Criteria

- Extend the existing native test_phase2_model_entities.py release-explorer fixture with qualified package-only, direct-only and direct-plus-package cases. Repeated path/format input must not multiply one match; same-URL observations with distinct match_ids and conflicting decisions must survive.
- Include a supported multi-date print, event-specific recording evidence, package-context-only recording evidence, ambiguous/wrong sibling, no-MODS jacket fallback, unknown/missing link and no-observation cases. Verify association targets, basis and scope against retained source facts in both directions. Package context cannot assert coverage of every sitting.
- Native checks enforce typed non-null lists, valid association values, unique tuples and resolvable targets, preserving original observation identity/attributes. Trace print-agreement and event qualification through retained package/input evidence plus original source_ref; basis is not an unexplained confidence label.
- Extend existing test_native_release.py actual-stdio checks to discover and execute both published recipes on that native output; assert correct one-observation result grain, explicit package context and distinct provenance. Existing registry drift/required-table checks must agree with actual emitted schema. No unavailable internal CTE appears in public recipe SQL.
- In existing site reader/unit and browser contracts, check the same emitted observations and source/scope meanings through the actual getMeeting/detail path; optional association metadata failure must preserve the core hearing view. Test an older schema with the field genuinely absent, not a synthetic empty list. No new runner, broad UI rewrite or per-release exhaustive audit.
- Separate source-local/model tests, emitted-candidate proof, and delivered selected-schema MCP/site replay. Retain candidate/release identities. Replay event 334136 using its retained qualification; record an honest unresolved result if event proof fails. Do not claim footage, captions, timestamps, duration, current playback or licensing merely because a locator is exposed.
- Serialize shared registry/generated-doc/native-fixture edits with other included fixes. Those editing constraints are distinct from logical implementation dependencies. Root owns ticket links/dependencies/status and future publication authorization.


## Notes

**2026-11-04T15:23:00Z**

2026-11-04 coordinated plan frozen by root: docs/plans/congress-explorer-root-cause-remediation-20261104.md. Refined owning layer from recipe-only metadata to one native model recording-association decision published as meeting_links [{event_id,basis,scope}]. Preserve original observations; qualified event scope drives existing coverage verdict policy, package_context remains a related locator without per-sitting coverage claims. No bare published-transcript join, destructive URL dedup, new acquisition or framework. Older absent field stays unavailable. Existing native release-explorer, actual stdio and site reader/browser paths supply bounded future acceptance. Altman qualification must preserve the retained curator/day proof or remain context/unresolved. This pass planned and edited tickets only; no implementation, tests/build, data preparation or publication. Status and existing links/dependencies preserved.
