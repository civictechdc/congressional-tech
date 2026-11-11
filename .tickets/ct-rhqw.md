---
id: ct-rhqw
status: open
deps: []
links: [ct-uywf]
created: 2026-11-11T00:15:02Z
type: task
priority: 2
assignee: mikewolfd
tags: [gate, nightly, release, owner-decision]
---
# Decide what an unattended nightly may publish when Congress.gov updates a meeting with real content

Follow-up to ct-uywf (re-fetch exemption, branch claude/ct-uywf-refetch-gate, under review 2026-11-10). That rule lets a re-fetched meeting pass unattended only when its witnesses are unchanged and only its read-bookkeeping columns moved; by the owner's choice, real content still stops for review. Replayed on the last two releases, most re-read meetings carry real content, so relist nights will still stop: 619db5f9e08e -> 77673bfb8fcf: 18 of 32 re-read meetings had real changes (documents, videos, titles, one moved date) and 4 new witnesses arrived on meeting 119590; 630164505301 -> 619db5f9e08e: 15 of 27. Evidence: .cache/archive-release/investigations/ct-uywf-20261110/uy-replay-*-after.json. Today the relist runs only by hand (ct-4jms), so this does not yet block unattended nights; it will once the relist is scheduled. Needs an owner decision on which kinds of new publisher content may publish without a person (e.g. additions proved from new receipts: new documents, videos, witnesses on an existing meeting) versus what must stop (removals, changed titles or dates, status changes), and a gate rule that proves each kind from capture facts the candidate does not control.

## Acceptance Criteria

The owner's decision is recorded; the gate classifies each kind of meeting change accordingly with planted tests for each; a replay on the two recorded releases states which groups pass and which stop.

