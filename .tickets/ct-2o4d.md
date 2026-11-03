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
# Populate documents.witness_keys on House HHRG-*-Wstate-* testimony PDFs when congress_gov wins witness precedence

Double-blind chaos evaluation (.cache/chaos-double-blind-20261102T2304Z/report.md, DB-5) found that 24,647 of 35,835 (68.8%) House witness statement PDFs matching HHRG-*-Wstate-* in r1b-run (and 25,305 of 35,861 in publish_v21) have witness_keys=[] even though meeting_keys is populated. Consequently, get_entity(table='witnesses', id=witness_key, section='documents'), search_documents(witness_key=...), and the witness_documents recipe return 0 statement PDFs for most House witnesses (e.g. Sam Bankman-Fried, John Ray III, Shou Chew, David Calhoun). Root cause: document-witness-keys.sql matches appearance_records_resolved.document_urls against copy_url_keys.url_key, but when congress_gov (priority 1) wins the witness observation over house_xml (priority 2) or when docs.house.gov URLs are only recorded on the house_xml observation, the surviving witness_key does not carry the house_xml document_urls or only links the superseded house_xml witness_key.

## Design

Owner: model/sql/document-witness-keys.sql and model/sql/appearance-records-resolved.sql.
1. In document-witness-keys.sql, map superseded witness keys (via witness_precedence.superseded_by) so any document URL attached to a lower-priority house_xml/senate_page observation of the same person on the same meeting also resolves to the canonical winning witness_key (or both keys when both are published in witnesses.parquet).
2. Ensure docs.house.gov URL normalization in appearance_url_keys and copy_url_keys agrees across HTTP/HTTPS and case variants for HHRG-*-Wstate-* files.
3. Verify that get_entity(table='witnesses', id=witness_key, section='documents') returns the witness's HHRG-*-Wstate-* statement PDF for the winning witness_key.

## Acceptance Criteria

- House HHRG-*-Wstate-* statement PDFs whose URLs are stated in house_xml or congress_gov populate list.witness_keys with the canonical witness_key (and any retained superseded row key).
- get_entity(table='witnesses', id=witness_key, section='documents') and the witness_documents recipe return the witness statement PDFs for House hearings where congress_gov is the top-priority witness source.
- All 6 model invariant suites (including missing_document_witness = 0) pass.

