---
id: ct-tbrj
status: closed
deps: []
links: []
created: 2026-10-31T07:22:48Z
type: feature
priority: 3
assignee: mikewolfd
external-ref: ss-ikn9
tags: [spicy-regs, meetings, layer2]
---

# Tell users whether and when Congress.gov meeting detail was read

A researcher or the SpicyRegs comparison should be able to distinguish a listed meeting from a successful detail read. The archive currently exposes the publisher's update time, not an event-specific detail-read observation. Listing and detail responses share the normalized `congress_gov` source. The newer `chamber_basis` field describes meeting-row coverage; it does not prove a detail read.

The original comparison lives in `spicy-stack/spicy-regs/docs/evidence/committee-meetings-archive-comparison-2026-10-30.json`. Its `state_without_destination` entry lists a missing destination but does not compare the `committee_meetings_detail_reads` attempt journal. Treat it as a feature inventory, not proof of every event's acquisition state.

## Smallest useful change

Derive a small event-keyed observation from retained evidence: the exact Congress, chamber and event detail route, its bound successful receipt, and evidence that the response supplied that event's detail. Use the observed read time and receipt locator separately from Congress.gov's `updateDate`. A digest-wide maximum fetch time alone is insufficient. Reuse held evidence and nullable meeting fields where possible; avoid a parser pin move if existing evidence supplies the qualification.

## Acceptance Criteria

- State successful detail reads, failed attempts, listings with no successful detail read within known observation coverage, and unknown coverage distinctly. Missing evidence must not become a claim that detail was never read. Document the state, time and evidence fields in the release schema.
- Qualify each successful observation against the exact event route, receipt and detail response. Keep source update time separate from retrieval and journal times. Cover one success, one known-scope listing-only case, one failure and one undated legacy case; preserve missing timestamps rather than inventing them.
- Have the `ss-ikn9` comparison read the actual detail-attempt evidence and compare selected observations on pinned inputs. Confirm the fields needed by its consumer. Keep the SpicyRegs retirement decision separate from this feature's implementation.

[Final root-cause review](../docs/plans/production-mvp-root-causes-round4-20261105.md).


## Notes

**2026-11-05T20:56:46Z**

Final root-cause review: require event-specific successful detail evidence, preserve unknown coverage and source update time, and extend the SpicyRegs comparison to the actual attempt journal.

**2026-11-06T17:28:19Z**

Local implementation adds meetings.congress_gov_detail_observation, qualified by the exact Congress/chamber/event request and final route, one bound successful receipt/body, selected meeting identity and the existing version-bound detail-only appearance reader. No parser or runtime pin changes. Earlier success survives later failure; selected-scope listing-only, failure and unknown stay distinct; missing times remain null and congress_gov_updated remains the publisher clock.

38 focused checks passed across the selected reruns (11 feature/export checks plus 27 schema/lifetime checks; partial lanes only). Real retained117688 receipt/body and bounded record-table pins were independently checked: retrieval2026-11-05T20:16:58.486180Z versus publisher update2025-01-02T05:57:18Z. Eight reused retained observations are six successes and two404failures, not corpus coverage. Independent GPT-6.1 Sol/xhigh consultant found no material logic blocker.

Implementation branch codex/ct-tbrj-detail-observations-20261106; durable results and concrete comparator handoff: .cache/archive-release/implementation/reviewed-non-news-20261106/ct-tbrj/. Public fields and evidence meaning: docs/meeting-detail-observations.md and model/registries/release-schema.json.

Ticket remains open: ct-r4rd/ss-ikn9 must pin and read actual committee_meetings_detail_reads evidence and compare observations against integrated final inputs. DDK/release owners must reconcile the small archive_model.py/archive_format.py edits and qualify final delivery. No main merge, push, full-corpus replay, new acquisition, shared import, deployment or publication occurred.

**2026-11-06T18:43:10Z**

Reviewed local implementation at 02526166 adds event-specific Congress.gov detail-read observations to meeting exports: qualified success, recorded failure, listing-only within selected evidence, and unknown. Each success binds the exact event route, receipt and response; retrieval time stays separate from publisher update time, and later failures preserve earlier success. All 38 selected checks passed across the relevant focused runs (partial lanes). An independently checked retained receipt/response for event 117688 confirms the binding; eight reused observations contain six successes and two 404 failures. Evidence and consumer fields: .cache/archive-release/implementation/reviewed-non-news-20261106/ct-tbrj/HANDOFF.md and COMPARATOR-HANDOFF.json. The reviewed commit is unchanged and the worktree is clean; no independent feature work remains. The pending House-only transition preserves the qualified Congress.gov proof versions.

Keep open: the original root owns consolidated source integration; ct-r4rd/ss-ikn9 owns comparison against the actual pinned detail-attempt journal; ct-m104 owns final native qualification, deployment and selected-release readback. Local preparation does not establish delivered or live behavior.

A new independent four-skill review found that HTTP 304 unchanged responses were incorrectly called failures. Follow-up 89851988 fixes the classification and clarifies unknown evidence; the regression failed before the change and all six focused observation/public-export checks passed afterward. The same independent reviewer is checking the final delta. Original 02526166 remains preserved. The source integrator must include the separate follow-up before final freeze; no ticket closure or live-delivery claim is made.

Independent review is in progress. No final review approval or completed release acceptance is claimed.

**2026-11-06T19:20:02Z**

Post-review update, November 6, 2026: independent GPT-6.1 Sol/xhigh review loaded all four requested skills and APPROVED the scoped source/evidence at 89851988. Event-specific detail-read observations distinguish qualified success, failure, listing-only evidence and unknown. Review caught HTTP 304 unchanged responses being classified as failures; the repair preserves prior qualified success. All six focused observation/export checks passed after the failing regression.

The reviewed source reference is included in local main 1a5ae01c. Remaining: Actual pinned detail-attempt journal comparison with ct-r4rd/ss-ikn9 and final combined/native, deployment and selected readback checks. Keep the ticket open for those acceptance criteria. This review does not establish a deployed release. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-tbrj/REVIEW.md).

**2026-11-08T11:00:52Z**

Closed after verifying the published detail-read observations and the exact ss-ikn9 comparison. All 99 attempt-journal rows were assessed: 98 match 97 event identities, 90 have equal response bytes, seven differ, and two remain explicitly unassessed. Publisher update, retrieval and journal times remain distinct; different bytes do not establish which source is newer.

Hosted success, failure and unknown controls match archive 5d24699ad9fa. Retained fixtures cover 304 and listing-only states absent from the release. The wrong-Congress plant is rejected. Upstream comparator landing remains with ct-r4rd/ss-ikn9.

Evidence: .cache/archive-release/implementation/post-release-ticket-finish-20261107/owners/ct-tbrj/RESULTS.md and STATUS.json.
