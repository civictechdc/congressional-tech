---
id: ct-h8dr
status: in_progress
deps: []
links: [ct-yuf0, ct-f7hp]
created: 2026-11-10T05:38:12Z
type: feature
priority: 2
assignee: mikewolfd
tags: [model, filenames, owner-decision]
---
# File names: a document takes its official House name whenever a copy has one, unless that name contradicts the committee's

Owner decision 2026-11-10 (questions dialog): adopt the broader name rule in the next release. Measured by simulation for ct-f7hp ('convention name, reader fields, then earliest'): 27,633 documents renamed, none losing information; 20,298 documents currently show a plain name beside a convention-named copy. Evidence: .cache/archive-release/release-20261110/fixes/saved-name/ (fs-05-effect.out, fs-10-final.out). It must NOT ship as simulated: the published release 619db5f9e08e showed that the House repository's slot names are sometimes wrong. 54 documents whose committee name says testimony now carry a House 'Bio' (37) or support-document (17) name; 13 of 13 read are testimony, one under another witness's surname (ct-yuf0); the live release before it already had 63 such contradictions by name and 1,688 'biographies' over 400 KB. So the rule needs a way to settle a House name against a committee name that states a different kind: by kind agreement, by the reading of the document, or by keeping the committee's name when they disagree.

## Acceptance Criteria

The rule is built and measured on a full model build, not simulated: renames against live with gains, losses and neutral counted; no document whose committee name and House name state different kinds takes the House name without a reading of the document that supports it; the 54 ct-yuf0 documents read as testimony; the rename list is reviewed like the 2026-11-10 one before it publishes.


## Notes

**2026-11-10T13:16:36Z**

Owner decision 2026-11-10 on the 343 non-slot official names against a committee kind: 'Review them manually'. Each is read and decided per document; until then they stay as published (the built behaviour on claude/ct-name-rule).

**2026-11-10T13:27:30Z**

2026-11-10 status: the name rule is built on claude/ct-next-release (0f427b29..c03c43da): 18,033 renames measured, 17,778 gain an official name, 253 contradicted slot names give way. Lanes green on a43f83d1. A reader is going through the 343 clashes one by one (.cache/archive-release/investigations/name-clash-review-20261110/decisions.csv). Left: full model build on the stack (none run yet), the 343 sheet checked by the owner, review, release. Follow-ups filed on the branch: ct-fk4w (settle a contradiction by reading the document), ct-29n4 (Truth in Testimony filename reader defect).
