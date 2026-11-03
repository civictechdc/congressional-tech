---
id: ct-j2yo
status: open
deps: []
links: [ct-kthe, ct-x78c, ct-5w9u, ct-dx22, ct-egg6, ct-66ns, ct-2o4d, ct-67k1]
created: 2026-11-03T00:59:35Z
type: feature
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [release, model, witnesses, senate, phase2]
---
# Resolve senate_page witness occasions to meetings.event_id and propagate meeting_keys to Senate witness documents

Double-blind chaos evaluation (.cache/chaos-double-blind-20261102T2304Z/report.md, DB-4 & DB-5) found that 100% of Senate webpage witness rows (13,561 rows across publish_v21 and r1b-frozen/after-out where source='senate_page') have event_id=NULL and occasion='page:<hash>'. Because appearance-observations.sql:181-188 never links senate_page URLs or (committee, date) contexts to meetings_resolved.event_id: (1) get_entity(table='meetings', id=event_id, section='witnesses') and meeting-keyed witness joins return 0 senate_page witnesses; (2) per-person witness deduplication (witness-precedence.sql) cannot deduplicate senate_page witnesses against congress_gov or mods witnesses on the same hearing; and (3) Senate witness testimony PDFs linked via senate_page have witness_keys populated but meeting_keys=[] and document_date=NULL.

## Design

Owner: model/sql/appearance-observations.sql, model/sql/component-meeting-links.sql, and a new model/sql/senate-page-meeting-links.sql step in model/jobs/publish-model.json.
1. Build a deterministic senate_page_meeting_links relation that matches senate_page observations to meetings_resolved.event_id when the Senate page URL or (committee_system_code, meeting_date, normalized title/time agreement) resolves unambiguously to a single Senate meeting (count(DISTINCT event_id) = 1).
2. Join senate_page_meeting_links in appearance-observations.sql:172-197 so matched senate_page observations receive event_id and occasion='meeting:'||cast(event_id AS VARCHAR), allowing appearance-records-resolved.sql and witness-precedence.sql to deduplicate across congress_gov, senate_page, and mods on the same meeting.
3. Propagate resolved event_id values from matched senate_page witness documents into component-meeting-links.sql so Senate testimony PDFs populate meeting_keys and inherit meeting-sourced document_date when no filename/content date is present.

## Acceptance Criteria

- Unambiguous senate_page witness observations resolve to meetings.event_id and occasion='meeting:{event_id}', and per-person precedence (superseded_by) deduplicates them against congress_gov/mods rows on the same meeting.
- Senate testimony PDFs linked to resolved senate_page witnesses carry the parent hearing in list.meeting_keys and inherit meeting-sourced document_date where applicable.
- Ambiguous same-day Senate pages with no distinguishing title/time/witness agreement remain occasion='page:{hash}' with zero false meeting attachments, verified by an independent raw-record check.

