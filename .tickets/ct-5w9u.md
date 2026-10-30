---
id: ct-5w9u
status: open
deps: [ct-73oe]
links: []
created: 2026-10-30T14:10:02Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-082q
tags: [html-metadata, extruct, congress-api, hearings]
---
# Associate Senate hearing dates and times with their own listing rows

The audit found 938 date disagreements on matched entries across 49 retained Senate listing bodies; 936 agree with the visible row date rather than the current parser's result. The existing listing-details parser returned no times for these matched microformat entries.

User value: date filters and acquisition cutoff/pagination operate on the right hearing; people get useful time and room information.

Evidence: docs/experiments/extruct-metadata-20261030/report.md and summary.json. Full extraction and comparison artifacts are under output/extruct-metadata-20261030/ (local, Git-ignored); preserve portable fixtures and manifests needed for tests rather than relying solely on these local paths.

## Design

Owner: congress_api/parsers/senate.py and acquisition/senate.py. Use semantic event boundaries from shared metadata alongside visible row text, associating link/title/date/time/location within the same event. Retain existing supported layouts. Preserve encoded and displayed values when they disagree; make selection explicit. Do not infer UTC or midnight from an unzoned/date-only value.

Listing dates guide discovery, not final event identity. Keep the separate hearing-page identity checks. The Appropriations example is body 01d7cbfd2adc71286e7de804014766ab08e5e2b81867499519d6b500ddd8c7e6: the Capitol Police hearing displays April 22 but is assigned the preceding hearing's April 28 date by proximity.

## Acceptance Criteria

- Preserve a replayable manifest and representative fixtures for the 49-body cohort; rerun the current baseline and record any input/version differences.
- No entry takes its date from a neighboring row in the cohort; explain all remaining disagreements, including the two encoded/displayed date conflicts.
- The 177 before-noon encodings paired with displayed PM are detected and retained; tests demonstrate the selected time policy and unknown-zone handling.
- Time/room outputs are associated with the correct hearing URL, existing layouts still parse, and cutoff/pagination tests cover an affected boundary.
- Final meeting identity still requires its own evidence; no false witness or meeting admission is introduced by generic page metadata.

