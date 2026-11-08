---
id: ct-irxg
status: closed
deps: [ct-4kuo, ct-j78x]
links: [ct-oh9y]
created: 2026-11-05T23:51:57Z
type: feature
priority: 0
tags: [mcp, mcp-research-20261105, mcp-proposal-003, transcript-reliability]
---
# Return a hearing dossier in one Congress MCP call

Add a research-friendly tool over the published `hearing_dossier` recipe from [ct-adoh](ct-adoh.md). The recipe and [ct-j78x](ct-j78x.md) own the existing joins and supported recording associations.

## Acceptance Criteria

- Expose `get_hearing_bundle(event_id, include?)`. Return the meeting, committees, current witnesses, prepared testimony, official and committee transcripts, captions, recording observations, and coverage in one bounded response. Optional includes and paging references let callers narrow or continue large sections.
- Use the transcript references from [ct-4kuo](ct-4kuo.md), the existing current-witness rule from [ct-9479](ct-9479.md), and the shared recording associations. Preserve event versus package scope and distinguish official transcripts, committee transcripts, captions, and prepared testimony.
- Return coverage states for the requested sections and preserve source references. Exercise a hearing with several material kinds, a hearing with sparse evidence, and the package-scoped recording for event `334136` against the selected release.


## Notes

**2026-11-06T18:43:10Z**

2026-11-06 owner audit: Implemented `get_hearing_bundle` with bounded meeting, committee, current-witness, testimony, labelled transcript/caption, recording and coverage sections plus continuations. At integration source `924e3ef2`, all 90 scoped files match reviewed `cffa18e0`; all 20 installed 0.6.2 modules match. The retained installed stdio native-fixture control passed all nine sections and paging (0.34 GiB peak). This is bounded fixture/consumer proof; no new full lane or authentic selected-release pass is claimed. All independent work is complete with no active job. The old metadata backlog blocker is resolved: 192,959 selected bodies, zero pending; canonical repair `1498c06c` and owner configuration `d2ec0211` are locally qualified. [Current evidence and runnable handoff](../.cache/archive-release/mcp-research-20261106/parallel-sessions/ct-irxg.md).

Keep `in_progress`: ct-m104 must provide the actual shared native/selected release. Remaining acceptance is authentic mixed/sparse dossier parity and event 334136's exact Altman source/package context, ct-4kuo source acceptance (dependent on ct-9s7b), and same-release site presentation. Local controls are not selected-release or live delivery.

Independent review is in progress. No final review approval or completed release acceptance is claimed.

**2026-11-06T19:20:02Z**

Post-review update, November 6, 2026: independent GPT-6.1 Sol/xhigh review loaded all four requested skills and APPROVED the scoped source/evidence at ceb60ec4. The bounded hearing bundle includes meetings, committees, current witnesses, testimony, labelled transcripts/captions, recordings, coverage and continuations. The independent review found no source defect; the retained installed native-fixture control passed all nine sections and paging. The old metadata backlog is settled.

This reviewed follow-up is not yet included in local main. Remaining: Authentic mixed/sparse dossier parity, event 334136 source/package context, transcript source acceptance and same-release site presentation. Keep the ticket open for those acceptance criteria. This review does not establish a deployed release. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-irxg/REVIEW.md).

**2026-11-07T22:29:58Z**

November 7 live dossier acceptance passed on Congress Explorer 0.6.2 and archive `5d24699ad9fa076e3e10c894a1cb3310ab35b12e8025adcca87feca7978080c1` from main `6300d463d1b61ebe05b4505b97537884b4842894`. The normal hosted tool matched the published rows and coverage for all nine sections on events 334136, 338785, 111120, and 100033. Mixed event 111120 returned three official and two committee transcripts. Its first hosted full request timed out and the identical retry passed. Sparse event 100033 retained unknown states for unpopulated sections.

The changed witness roster on 110001 returned seven current appearances over two pages, excluding four record materials and three member statements. Event 105990 had an empty witness section with published coverage `not_stated`. The Altman observation on 334136 kept its source reference and package link to `CHRG-118shrg52706` with `package_context`. Hosted recording coverage remained unresolved with zero event recordings. Live Pages showed “Related package recording evidence,” the Senate locator, the printed hearing and the three roster witnesses.

The shared ct-9s7b result for 338785 confirmed the `live` caption source for `senate:govtaff093026`, a readable cue and the selected Pages view. The dossier links and coverage passed. Keep `in_progress` for the formal ct-4kuo dependency. The official print `ea05e8b42b6eeadd` still times out in the live transcript and document readers. The committee control `f66588510a021760` read and reopened its citation on the same release. The dossier work has no remaining reader check.

[Live dossier acceptance](../.cache/archive-release/mcp-research-20261106/parallel-sessions/ct-irxg/live-5d24699ad9fa/acceptance.json) · [Altman page snapshot](../.cache/archive-release/mcp-research-20261106/parallel-sessions/ct-irxg/live-5d24699ad9fa/browser/hearing-snapshot.md) · [Shared caption result](../.cache/archive-release/mcp-research-20261106/parallel-sessions/ct-9s7b/live-5d24699a/result.json) · [Transcript dependency](../.cache/archive-release/mcp-research-20261106/parallel-sessions/ct-4kuo/live-5d24699a-20261107/hosted-result.json)

**2026-11-08T11:02:40Z**

Hosted Explorer 0.6.3 is deployed on both replicas against archive 5d24699ad9fa. The retained nine-section dossier acceptance remains valid on this unchanged archive, including rich and sparse hearings, package-scoped event 334136, optional includes and coverage states. The hosted transcript and caption references now read and reopen successfully. Both dependencies ct-j78x and ct-4kuo are closed.

Evidence: .cache/archive-release/mcp-research-20261106/parallel-sessions/ct-irxg/live-5d24699ad9fa/acceptance.json and releases/congress-mcp-0.6.3-20261107/hosted-acceptance-01/ under .cache/archive-release/.
