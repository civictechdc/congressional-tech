---
id: ct-qd6o
status: closed
deps: []
links: []
created: 2026-11-17T18:18:49Z
type: task
priority: 1
assignee: mikewolfd
tags: [docs, hosted]
---
# A one-page runbook: how the nightly works and what to do when it stops

The nightly's behaviour is spread over tickets, commit messages and four gate modules. An owner who gets a ci-failure issue should be able to read one page and know what happened and what, if anything, to do.

## Acceptance Criteria

docs/nightly.md, one page: the path, what runs when, the five ways a night can stop and the single action for each, where the evidence is. The ci-failure issue links to it.

## Notes

**2026-11-17**

Done: `docs/nightly.md` (what runs when, each way a night stops keyed by the line the log shows, the one action for each, switches, where evidence is). Every `ci-failure` issue and comment now ends with a link to it (`.github/scripts/ci-alerts.py`).

The one manual step left, writing a cause record, has a checked-in tool instead of ad hoc scripts: `python -m viewer_publication.cause_record draft|pin`. It copies the stopped run's findings into the record, keeps the gate report's facts as pinned evidence, pins the record in `model/jobs/publish.json`, and runs the draft through `release_gate.verdict`, so a night no record can pass (vanished or unchecked links, moved links beyond the report's sample) is refused with the gate's own reasons. Run against the saved evidence of the three nights hand-recorded on 2026-11-17, it drafted the same groups, counts and named corrections as the records that published. It is outside the model definition hash.

Cannot see: whether the differences are right. It writes the reason you give; reading the record before merging is still the review.
