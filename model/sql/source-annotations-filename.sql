-- Filename producers own typed keys; the model joins their exact admitted pair.
-- Both names (owner, 2026-11-02): a redirect's shown name is the final URL's, and the requested
-- (linked) URL's own name is read too (effective-filenames.sql requested_filename). Where the shown
-- name gives no date, kind, family, congress or committee code, the linked name's value fills it;
-- where both give one and they differ, the shown name's stays and the linked one is kept in
-- linked_* with its name and URL (evidence filename_conflicts lists those pairs for triage).
WITH own AS (
 SELECT s.source_id,f.* FROM source_files s JOIN filename_readings f
  ON s.filename=f.filename AND coalesce(s.source_url,'')=f.source_url
 WHERE f.catalog_version={{CATALOG_VERSION}}
), linked AS (
 SELECT * FROM source_linked_filename_readings WHERE preference=1
)
SELECT o.source_id,o.filename,o.source_url,o.catalog_version,o.status,o.error_type,o.valid,
 CASE WHEN coalesce(array_length(o.document_kind),0)=0 THEN coalesce(l.document_kind,o.document_kind) ELSE o.document_kind END AS document_kind,
 CASE WHEN coalesce(array_length(o.document_family),0)=0 THEN coalesce(l.document_family,o.document_family) ELSE o.document_family END AS document_family,
 CASE WHEN coalesce(array_length(o.committee_code),0)=0 THEN coalesce(l.committee_code,o.committee_code) ELSE o.committee_code END AS committee_code,
 coalesce(o.congress,l.congress) AS congress,o.date_token,o.measure_type,o.measure_number,
 coalesce(o.filename_date,l.filename_date) AS filename_date,o.measure_keys,o.bioguide_ids,o.package_id,o.fields,
 l.requested_filename AS linked_filename,l.requested_url AS linked_url,
 l.filename_date AS linked_filename_date,l.congress AS linked_congress,l.document_kind AS linked_document_kind,
 l.document_family AS linked_document_family,l.committee_code AS linked_committee_code,
 -- Raw shown-name values let conflict triage compare every requested name, not the canonical fill.
 o.filename_date AS shown_filename_date,o.congress AS shown_congress,o.document_kind AS shown_document_kind,
 o.document_family AS shown_document_family,o.committee_code AS shown_committee_code,
 o.filename_date IS NULL AND l.filename_date IS NOT NULL AS filled_date,
 o.congress IS NULL AND l.congress IS NOT NULL AS filled_congress,
 coalesce(array_length(o.document_kind),0)=0 AND coalesce(array_length(l.document_kind),0)>0 AS filled_kind,
 coalesce(array_length(o.document_family),0)=0 AND coalesce(array_length(l.document_family),0)>0 AS filled_family,
 coalesce(array_length(o.committee_code),0)=0 AND coalesce(array_length(l.committee_code),0)>0 AS filled_committee
FROM linked l RIGHT JOIN own o ON l.source_id=o.source_id AND l.preference=1
