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

# Return supported recording evidence in hearing results

Researchers should see the recording evidence the archive has for a hearing. In `e145d24c389e`, `hearing_dossier` and `meeting_recordings` omit the Altman recording locator for event `334136`, while `meeting_coverage` reports one present observation.

## Root cause (2026-11-05)

The released observation for `CHRG-118shrg52706` has package scope and no event ID. Coverage finds it through a qualified print-to-meeting join. In e145, both recipes filtered on the observation's `event_id`. Coverage could therefore find an observation that the recipes omitted. The transcript list also admits weaker jacket links, which carry different evidence.

## Merged implementation and remaining acceptance

Local `main` includes the implementation at merge `18049548`. The native model publishes `recording_matches.meeting_links` for coverage, both hearing recipes, and site detail. Each link identifies the event, basis (`direct_event` or `print_agreement`), and scope (`event` or `package_context`). Older releases label the association unavailable and retain access to original observations.

Twenty-five focused native tests passed. Built browser and actual MCP standard input/output checks agreed on typed fixture `aaaa08c543e4f22b0544768a0f60e76a25399cb0f448af070b0b24b7c76ad6e1`. The retained Judiciary curator note supports the Altman player locator as evidence related to the package and hearing date. The association stays at `package_context`.

The release coordinator owns the combined candidate and selected-release comparison across native coverage, both installed MCP recipes, and the site. Check that the Altman observation and source reference survive with package scope. [Release follow-through](../docs/plans/production-mvp-follow-through-20261105.md)

## Acceptance Criteria

- Use the existing native fixture to check qualified package-only, direct-only and direct-plus-package associations, supported multi-date context and event-specific evidence. Include wrong-sibling, no-MODS jacket fallback, ambiguous, missing-link and no-observation controls. Compare associations, source basis and valid targets in both directions. Package context alone establishes neither event presence, full coverage nor confirmed absence.
- Preserve `match_id`, original subject and event or package, URL/video key, basis, decision, score, status, recording scope, note and source reference. Repeated traversal returns one observation. Distinct, potentially conflicting IDs survive even when the URL matches. Keep unknown, claimed, unresolved and conflicting states and distinguish association scope from full/excerpt recording scope.
- On the same typed candidate, compare native coverage and actual MCP standard I/O results from both recipes, including association scope and usable evidence links. Use bounded, parameterized SQL against public tables. Align the model, Phase 2 annex, registry, generated docs and relationship definitions with the emitted schema.
- Qualify the Altman locator using the retained curator/day evidence before assigning event scope. If the evidence supports only package context, return it as such. Preserve match `b0ac3d1823bf0deacb479b9b3b6ab17e4cb45299e2bc74e8b3c13ea3b64912b3` and source reference `recording_decisions:b7680266fc4c839db86369c34690312859a60cacc6f42e7851b949736af97b77`. The locator establishes a link. Held media, captions, current playback, duration, timestamps and licensing require their own evidence.

## Coordination and evidence

Record source, candidate and selected-release results separately. Deliver the emitted field in a data-bearing release. Reuse the actual site recording and older-schema core-hearing check owned by [ct-t915](ct-t915.md), and the final reader acceptance in [ct-m104](ct-m104.md). [ct-9s7b](ct-9s7b.md) owns caption inventory quality. Retained calls are in `.cache/archive-release/chaos-personas-20261104/investigation-discovery/calls.jsonl`. The bounded query's 2,934 package-only observations across 2,599 meetings describe possible exposure. [Root-cause evidence](../docs/plans/production-mvp-root-causes-20261105.md).

## Notes

**2026-11-04T15:23:00Z**

2026-11-04 coordinated plan frozen by root: docs/plans/congress-explorer-root-cause-remediation-20261104.md. Refined owning layer from recipe-only metadata to one native model recording-association decision published as meeting_links [{event_id,basis,scope}]. Preserve original observations; qualified event scope drives existing coverage verdict policy, package_context remains a related locator without per-sitting coverage claims. No bare published-transcript join, destructive URL dedup, new acquisition or framework. Older absent field stays unavailable. Existing native release-explorer, actual stdio and site reader/browser paths supply bounded future acceptance. Altman qualification must preserve the retained curator/day proof or remain context/unresolved. This pass planned and edited tickets only; no implementation, tests/build, data preparation or publication. Status and existing links/dependencies preserved.

**2026-11-05T20:18:06Z**

Integrated producer-owned recording associations across coverage, recipes and site readers. Sitting evidence and package context remain distinct, and old-schema original observations remain accessible. Typed and older fixture checks passed through the browser and MCP standard I/O. The Altman observation retains its limited committee/day/player evidence. Same selected-release readback remains due; full build/publication waits all waves.
