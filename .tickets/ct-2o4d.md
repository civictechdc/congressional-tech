---
id: ct-2o4d
status: open
deps: []
links: [ct-j2yo, ct-dx22, ct-66ns, ct-67k1]
created: 2026-11-03T00:59:37Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [release, model, witnesses, documents, phase2]
---
# Populate documents.witness_keys on House HHRG-*-Wstate-* testimony PDFs for congress_gov-sourced witnesses and superseded rows

Double-blind chaos evaluation (.cache/chaos-double-blind-20261102T2304Z/report.md, DB-5) and Red/Green Team empirical audit found that 24,647 of 35,835 (68.8%) House witness statement PDFs matching HHRG-*-Wstate-* in r1b-run (and 25,305 of 35,861 in publish_v21) have witness_keys=[] even though meeting_keys is populated. Consequently, get_entity(table='witnesses', id=witness_key, section='documents'), search_documents(witness_key=...), and the witness_documents recipe return 0 statement PDFs for most House witnesses (e.g. Sam Bankman-Fried on 114305/114729, John J. Ray III on 115246, Shou Chew on 115519).

Root cause (verified against r1b-frozen and r1b-run/d4-spec):
1. In model/registries/meeting-sources.json:15-25, house_xml is priority 1 and congress_gov is priority 2. However, 92.5% (21,975 of 23,751 in r1b-frozen/release; 28,988 of 30,254 in d4-spec) of unlinked HHRG-*-Wstate-* PDFs belong to ~5,352 House meetings that have ONLY congress_gov (and/or mods) witness rows in appearance_records and NO house_xml witness list at all.
2. In Congress.gov's /v3/committee-meeting API (congress_api/models/congress.py:92-104, 170-172), CommitteeMeeting.witnesses[] contains only {name, position, organization} (0 of 36,037 congress_gov appearances carry per-witness document_links), while the HHRG-*-Wstate-* PDF URLs are placed in the sibling meeting-level CommitteeMeeting.witnessDocuments[] array (extracted into meeting_records.document_urls -> meeting_keys, not appearance_records).
3. In addition, when a lower-priority observation (e.g. senate_page or house_xml) carries document_urls and is marked superseded_by in witness_precedence.sql, document-witness-keys.sql does not propagate the link to the canonical winning witness_key.

## Design

Owner: model/sql/document-witness-keys.sql and packages/viewer_publication/src/viewer_publication/archive_model.py (do NOT modify byte-hashed appearance_records.py).
1. Primary fix (solves 19,400+ unlinked congress_gov House Wstate/TTF/Bio PDFs): In model/sql/document-witness-keys.sql, join House witness documents that have a resolved single House meeting event_id (via source_annotations_meetings / document_metadata) and an extracted HHRG witness slug (source_filename_readings witness_id or regex (?i)HHRG-[0-9]+-[A-Z0-9]+-(?:Wstate|TTF|Bio)-([A-Za-z0-9'-]+)-[0-9]{8}) against canonical (superseded_by IS NULL) witnesses on occasion='meeting:'||event_id in appearance_people where normalized family + given_initial (regexp_replace(lower(family),'[^a-z0-9]','','g')||substr(regexp_replace(lower(coalesce(given,'')),'[^a-z0-9]','','g'),1,1), or exact normalized family when unique on that meeting) matches the slug unambiguously (count(DISTINCT canonical_witness_key) = 1 on that event_id).
2. Precedence propagation: In model/sql/document-witness-keys.sql, join witness_precedence wp and emit coalesce(wp.superseded_by, w.witness_key) (or both keys when both are published) so any document_urls attached to a superseded witness row also link to the canonical winning witness_key.
3. Ensure archive_model.py step inputs for document_witness_keys include the required relations (witness_precedence, appearance_people, source_filename_readings / source_annotations_meetings).

## Acceptance Criteria

- House HHRG-*-{Wstate,TTF,Bio}-* PDFs on congress_gov-sourced meetings unambiguously matching a single canonical witness on that event_id populate list.witness_keys (resolving 19,000+ previously unlinked House testimony PDFs, including SBF on 114305/114729, John J. Ray III c1858421dc9d7e31 on 115246, and Shou Chew on 115519).
- Document URLs on superseded witness rows propagate via witness_precedence.superseded_by to the canonical witness_key.
- All 6 model invariant suites (including model_invariants.missing_witness_keys = 0 and relationship_invariants.missing_document_witness = 0) pass.

