---
id: ct-1i4q
status: open
deps: []
links: [ct-o2pr, ct-t915, ct-9s7b, ct-gi01]
created: 2026-11-02T14:59:10Z
type: feature
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [transcripts, captions, coverage, phase2]
---
# Count committee transcripts and caption/subtitle files as a meeting's transcripts, labelled by source

Owner decision 2026-11-02: count both, and also count subtitle files we hold. Today a meeting's transcripts are only GPO printed hearings (CHRG packages matched through Congress.gov transcript_jackets; annex §2 'transcripts'). House committees often post their own transcript (e.g. HHRG-118-VR09-Transcript-20231108.pdf, listed in the House meeting XML) months or years before the GPO print, and recordings carry caption/subtitle tracks (recordings.tracks). Those count only as held evidence (entity-meetings.sql:11-16), and transcript coverage says not_stated.

## Acceptance Criteria

- A meeting's transcripts list every source it holds, each labelled: printed hearing (GPO CHRG package), committee transcript (a transcript file its own record lists, identified by a tested rule from the record's document type or filename, not a bare substring), and captions/subtitles (complete caption or subtitle tracks of its recordings; never segments or empty bodies).
- Transcript coverage is present when any source exists, with the sources named; unresolved and unknown keep their meanings.
- Data model §2 transcripts and coverage are updated; site and MCP show the source label.
- Every changed meeting is checked against raw: the committee file in the House XML and the caption track bodies.
- Tests fail first on a meeting with only a committee transcript, only captions, only a print, and a segment-only recording.


## Notes

**2026-11-02T16:28:57Z**

2026-11-02 (lead): impl-f r1b-transcripts 82158e12 (stacked on r1b-f): committee transcripts and caption sources counted and labelled, with tests, docs and an independent raw judge; 2,602 of 2,606 committee transcript files confirmed against raw; no caption track qualifies on v21 (none is a complete caption or subtitle track). Rebase after red-f3's r1b-f fixes.
