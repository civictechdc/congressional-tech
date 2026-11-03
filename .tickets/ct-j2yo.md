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

Owner: model/registries/meeting-sources.json, model/sql/senate-page-meeting-links.sql, model/sql/appearance-observations.sql, model/sql/component-meeting-links.sql, model/sql/document-witness-keys.sql, model/sql/entity-meeting-coverage.sql, and packages/viewer_publication/src/viewer_publication/archive_model.py (do NOT modify byte-hashed senate_page.py).
1. Swap source priorities in model/registries/meeting-sources.json:27-37 so senate_page is priority = 3 and mods is priority = 4 (and update model/jobs/publish.json hashes). On 100% of Senate meetings (4,575/4,575), congress_gov has collection_state='absent'; keeping mods at priority 3 above senate_page (priority 4) would cause mods (which has position=NULL, organization=NULL, document_urls=[]) to supersede senate_page on every printed Senate hearing and strip titles/organizations/PDF links from canonical witnesses. Also ensure document-witness-keys.sql maps coalesce(wp.superseded_by, w.witness_key) (with ct-2o4d).
2. Guard empty/unrecognized senate_page containers: In senate-page-meeting-links.sql / appearance-observations.sql:155-157, only resolve senate_page rows with collection_state='present' to occasion='meeting:'||event_id (or map non-'present' senate_page rows to 'absent') so the 28 empty senate_page containers do not produce an odd top_code in appearance-records-resolved.sql:38-46 and suppress mods witnesses.
3. Build model/sql/senate-page-meeting-links.sql (registered in archive_model.py:appearance_steps() right before appearance_observations) using the signals that actually exist in the DAG (since appearance_records has 0 dates/titles/committees for senate_page):
   - Committee (system_code): Join capture_contexts.source_url hostname (*.senate.gov) against spicy_committees.website_url (WHERE parent_system_code IS NULL AND system_code <> 'jjec00' — matches 20/20 Senate hosts 1:1 to parent system_code, matching meetings_resolved.committees[].system_code on substr(system_code,1,4)||'00'). Also propagate .senate.gov host committee codes in source-annotations-codes.sql so Senate witness PDFs populate list.committee_keys.
   - Date & Title: Join page_facts pf ON pf.body_sha = arrow_cast(decode(r.record_sha_hex,'hex'),'FixedSizeBinary(32)') (3,886/3,886 titles and 2,076 content_dates) plus URL date regex extraction on capture_contexts.source_url.
   - Disambiguation: When (parent_committee, meeting_date) has 1 Senate meeting, link 1:1; when multiple same-day hearings exist, disambiguate via normalized page_facts.title/heading vs meetings_resolved.title and witness surname overlap (appearance_people on senate_page vs mods via package_meeting_links). Leave ambiguous rows as occasion='page:<hash>'.
4. Add 'document_witness_keys' and 'appearance_records_resolved' to component_meeting_links inputs in archive_model.py:893 and union resolved witness event_ids into model/sql/component-meeting-links.sql so Senate witness PDFs populate list.meeting_keys and inherit meeting-sourced document_date. Reconcile senate_page_links_pending in model/sql/entity-meeting-coverage.sql:63-90.

## Acceptance Criteria

- Unambiguous senate_page witness observations (collection_state='present') resolve to meetings.event_id and occasion='meeting:{event_id}', with senate_page (priority 3) outranking mods (priority 4) so canonical Senate witnesses retain position, organization, and document_urls while empty senate_page containers never suppress mods witnesses.
- Senate testimony PDFs linked to resolved senate_page witnesses carry the parent hearing in list.meeting_keys, committee in list.committee_keys, and inherit meeting-sourced document_date where applicable.
- Ambiguous same-day Senate pages with no distinguishing title/witness agreement remain occasion='page:{hash}' with zero false meeting attachments, verified by an independent raw-record check and all 6 model invariant suites.

