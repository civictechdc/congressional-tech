---
id: cef-9e9w
status: closed
deps: []
links: [ct-l9g0]
created: 2026-10-28T17:17:18Z
type: task
priority: 1
assignee: mikewolfd
---
# Qualify the 0cbad87 runtime for the raw rebuild application and Linux

Qualify the fully reviewed corrected native source 0cbad87574a4414af56461f442a481a4cfa93079 through current application callers and the existing Linux cross-build and project-runner paths. Preserve the deployed seed runtime885 and all private/live state.

## Acceptance Criteria

Retain exact source/build/lock/digest/platform pins, actual app and Linux runner results, source review and exact lead-only upgrade commands. Refuse foreign descriptors and keep seed885 unchanged until lead upgrades for RAW. Long jobs detached, physical ceiling under12GiB while D1 runs; start only after shared/B1-accepted.


## Notes

**2026-10-28T17:27:31Z**

Candidate0cb source and Darwin SHA match the fully qualified native snapshot; actual maintained live runtime/hash probe passes0.39s plus setup/preflight/publisher fixture runner exits0. Linux cross build and expanded application/full qualification remain unaccepted and start after B1 quiet window. Pin is local integration only; lead deploy remains885.

**2026-10-30T14:32:56Z**

Qualified 0cbad87574a4414af56461f442a481a4cfa93079 runtime across Darwin and Linux and merged to main; single-pin consolidation tracked in ct-l9g0.
