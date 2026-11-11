---
id: ct-rhqw
status: open
deps: []
links: [ct-uywf, ct-960v]
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


## Notes

**2026-11-11T16:06:21Z**

2026-11-11 owner decision (release session, questions dialog): 'Everything from Congress.gov publishes'. Any Congress.gov meeting update publishes unattended, with a morning report of what changed; only lost links or keys stop the night. Built on branch claude/ct-rhqw-congress-gov-updates (not merged): the comparison names the meetings whose successful detail read names a body the live release cites nowhere, in another receipt and later than the live read (or first stated with such a read), and sets apart as refetch_only every column the record states (never transcripts or house_xml_updated; the outcome columns only on a publisher basis), its Congress.gov witnesses (added; removed with a map row; edited; reordered) whose new body is the meeting's read, their key-map rows, documents whose witness_keys moved only by them, and witness coverage. Still stopping: the link rule, a removed witness key with no map row, a map row naming an unpublished successor, a collapsing map, any other source or meeting, a listed-only meeting, and any read or body the capture table does not prove. The gate writes meeting-updates.txt/.json beside its automatic trace; the nightly keeps them and puts the line in summary.json. The ct-uywf all-or-nothing witness rule is replaced (its clean re-keys are a special case). Replay: 619db5f9e08e to 77673bfb8fcf sets apart 23 updated meetings (2 first stated) incl. 119590's 4 new witnesses; 630164505301 to 619db5f9e08e 31 incl. the 22 reorders; what still stops there is other sources (transcripts, transcript-based outcomes, the MODS reader change) and one listed-only meeting. Evidence: .cache/archive-release/investigations/ct-uywf-20261110/uy-rhqw-replay-*/ (report.json, meeting-updates.txt), uy-mutations-rhqw.json (10 clause mutations, each caught).
