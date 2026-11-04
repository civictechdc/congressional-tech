---
id: ct-yr9o
status: open
deps: []
links: [ct-717p]
created: 2026-11-02T18:20:46Z
type: bug
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [records, post-release]
---
# house_xml record parsers stamp unparseable XML 'completed' instead of an unreadable decision

Found by impl-h on 2026-11-02 while fixing the shared record producer's unreadable decision (r1b-h3). The meeting, appearance and committee house_xml parsers return a 'completed' row for bytes that don't parse, so an unreadable body would be recorded as a success with no records. Measured on the v21 inputs: 0 affected bodies. All 6,179 house_xml meeting rows hold a meeting; the 2 empty witness rows (111420, 105459) are real empty <witness-list> bodies, read in full; candidates route only after a successful XML reading. Strict xfail tests pin the gap (r1b-h3 7a7f5e38, test_record_producer_unreadable.py).

## Acceptance Criteria

The three house_xml parsers raise on unparseable XML, so the shared unreadable_decision() records it; the strict xfails flip to passing; land with the next intentional record-pin move (no data impact today).

