---
id: ct-j2yo
status: closed
deps: []
links: [ct-kthe, ct-x78c, ct-5w9u, ct-dx22, ct-egg6, ct-66ns, ct-2o4d, ct-67k1]
created: 2026-11-03T00:59:35Z
type: feature
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [release, model, witnesses, senate, phase2]
---
# Resolve senate_page witness occasions to meetings.event_id and propagate vetted meeting/committee/congress/chamber links to documents

Double-blind chaos evaluation (.cache/chaos-double-blind-20261102T2304Z/report.md, DB-4 & DB-5) found that 100% of Senate webpage witness rows (13,561 rows across publish_v21 and r1b-frozen/after-out where source='senate_page') have event_id=NULL and occasion='page:<hash>'. Because appearance-observations.sql:181-188 never links senate_page URLs or (committee, date) contexts to meetings_resolved.event_id: (1) get_entity(table='meetings', id=event_id, section='witnesses') and meeting-keyed witness joins return 0 senate_page witnesses; (2) per-person witness deduplication (witness-precedence.sql) cannot deduplicate senate_page witnesses against congress_gov or mods witnesses on the same hearing; and (3) Senate witness testimony PDFs linked via senate_page have witness_keys populated but meeting_keys=[] and document_date=NULL.

## Design

Owner: model/registries/meeting-sources.json, model/sql/senate-page-meeting-links.sql, model/sql/appearance-observations.sql, model/sql/component-meeting-links.sql, model/sql/document-witness-keys.sql, model/sql/entity-meeting-coverage.sql, and packages/viewer_publication/src/viewer_publication/archive_model.py (do NOT modify byte-hashed senate_page.py).
1. User Decision (A3 Confirmed): Swap source priorities in model/registries/meeting-sources.json:27-37 so senate_page is priority = 3 and mods is priority = 4 (and update model/jobs/publish.json hashes). On 100% of Senate meetings (4,575/4,575), congress_gov has collection_state='absent'; keeping mods at priority 3 above senate_page (priority 4) would cause mods (which has position=NULL, organization=NULL, document_urls=[]) to supersede senate_page on every printed Senate hearing and strip titles/organizations/PDF links from canonical witnesses. Also store both canonical (wp.superseded_by) and superseded (w.witness_key) keys in list.witness_keys via document-witness-keys.sql (with ct-2o4d) so any witness row resolves its PDFs.
2. Guard empty/unrecognized senate_page containers: In senate-page-meeting-links.sql / appearance-observations.sql:155-157, only resolve senate_page rows with collection_state='present' to occasion='meeting:'||event_id (or map non-'present' senate_page rows to 'absent') so the 28 empty senate_page containers do not produce an odd top_code in appearance-records-resolved.sql:38-46 and suppress mods witnesses.
3. Build model/sql/senate-page-meeting-links.sql (registered in archive_model.py:appearance_steps() right before appearance_observations) using the signals that actually exist in the DAG (since appearance_records has 0 dates/titles/committees for senate_page):
   - Committee (system_code): Join capture_contexts.source_url hostname (*.senate.gov) against spicy_committees.website_url (WHERE parent_system_code IS NULL AND system_code <> 'jjec00' — matches 20/20 Senate hosts 1:1 to parent system_code, matching meetings_resolved.committees[].system_code on substr(system_code,1,4)||'00'). Also propagate .senate.gov host committee codes in source-annotations-codes.sql so Senate witness PDFs populate list.committee_keys.
   - Date & Title: Join page_facts pf ON pf.body_sha = arrow_cast(decode(r.record_sha_hex,'hex'),'FixedSizeBinary(32)') (3,886/3,886 titles and 2,076 content_dates) plus URL date regex extraction on capture_contexts.source_url.
   - Disambiguation: When (parent_committee, meeting_date) has 1 Senate meeting, link 1:1; when multiple same-day hearings exist, disambiguate via normalized page_facts.title/heading vs meetings_resolved.title and witness surname overlap (appearance_people on senate_page vs mods via package_meeting_links). Leave ambiguous rows as occasion='page:<hash>'.
4. Add 'document_witness_keys' and 'appearance_records_resolved' to component_meeting_links inputs in archive_model.py:893 and union resolved witness event_ids into model/sql/component-meeting-links.sql so Senate (and House) witness PDFs populate list.meeting_keys and inherit meeting-sourced document_date. Reconcile senate_page_links_pending in model/sql/entity-meeting-coverage.sql:63-90.
5. /etl-workflow Cross-Table Propagation & Vetting Fixes (F1 & F2 — zero extra table scans):
   - Vetted CHRG-* links in list.meeting_keys (F1): In model/sql/source-annotations-meetings.sql:1-10, remove the unvetted package_records (unnest(p.named_meetings)) branch, and in model/sql/component-meeting-links.sql:1-14 replace raw JOIN meeting_transcript_links l with the vetted package_meeting_links union meeting_transcript_links LEFT JOIN package_mods_facts WHERE f.package_id IS NULL (matching entity-meetings.sql:51-54) so the 6,700 rejected false (package_id, event_id) edges do not leak into list.meeting_keys.
   - Propagate committee_keys, congress, and chambers across component_meeting_links (F2): In model/sql/component-meeting-links.sql:29-36 (which already joins LEFT JOIN meetings_resolved mr ON cm.event_id=mr.event_id), aggregate mr.committees[].system_code (committee_keys), mr.chamber (chambers), and min(mr.congress) (congress) at zero extra join cost, and merge them into model/sql/document-normalized.sql:7 and document-recovery-normalized.sql. Bounded probe over r1b-frozen/release verified this enriches +53,675 hearing-linked documents with committee_keys (including 21,173 published-hearing transcripts, 14,277 committee amendments, 10,080 committee bills, and 1,104 published-report docs), +19,784 with congress, and +20,589 with chambers, with lost_committees = 0 (MERGED_RECOVERY_SQL) and missing_committee_keys = 0.

## Acceptance Criteria

- Unambiguous senate_page witness observations (collection_state='present') resolve to meetings.event_id and occasion='meeting:{event_id}', with senate_page (priority 3) outranking mods (priority 4) so canonical Senate witnesses retain position, organization, and document_urls while empty senate_page containers never suppress mods witnesses.
- Senate testimony PDFs linked to resolved senate_page witnesses carry the parent hearing in list.meeting_keys, committee in list.committee_keys, and inherit meeting-sourced document_date where applicable.
- Hearing-linked documents in list.parquet inherit committee_keys (+53,675 docs), congress (+19,784 docs), and chambers (+20,589 docs) from component_meeting_links, while false CHRG-* package-to-meeting links rejected by print_meeting_agreement are excluded from list.meeting_keys.
- Ambiguous same-day Senate pages with no distinguishing title/witness agreement remain occasion='page:{hash}' with zero false meeting attachments, verified by an independent raw-record check and all 6 model invariant suites.


## Notes

**2026-11-03T12:48:59Z**

Implemented and verified on r3-mcp / release-train (4d583687): added linearized window-function senate-page-meeting-links.sql (95.7ms on r1b-frozen, 0 OOM, 9,464 senate_page witnesses linked across 2,790 Senate hearings), swapped senate_page (priority 3) above mods (priority 4) in meeting-sources.json, updated entity-meeting-coverage.sql (+1,615 Senate meetings with witnesses=present), canonicalized .senate.gov host codes (spag00, slet00, jsec00, scnc00, ssaf00), and propagated committee_keys/congress/chambers in component-meeting-links.sql.
