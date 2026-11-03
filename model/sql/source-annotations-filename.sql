-- Filename producers own typed keys; the model joins their exact admitted pair.
-- Both names (owner, 2026-11-02): a completed, nonempty shown value has precedence. Otherwise each
-- field takes the first completed linked reading that supplies it, in canonical URL/name order, and
-- keeps that supplier's name and URL. Shown status/error stay separate from the per-field suppliers.
WITH own AS (
 SELECT s.source_id,f.* FROM source_files s JOIN filename_readings f
  ON s.filename=f.filename AND coalesce(s.source_url,'')=f.source_url
 WHERE f.catalog_version={{CATALOG_VERSION}}
), linked AS (
 SELECT * FROM source_linked_filename_readings WHERE preference=1
), linked_date AS (
 SELECT source_id,filename_date,requested_filename,requested_url,
  row_number() OVER(PARTITION BY source_id ORDER BY preference) AS choice
 FROM source_linked_filename_readings WHERE filename_date IS NOT NULL
), linked_congress AS (
 SELECT source_id,congress,requested_filename,requested_url,
  row_number() OVER(PARTITION BY source_id ORDER BY preference) AS choice
 FROM source_linked_filename_readings WHERE congress IS NOT NULL
), linked_kind AS (
 SELECT source_id,document_kind,requested_filename,requested_url,
  row_number() OVER(PARTITION BY source_id ORDER BY preference) AS choice
 FROM source_linked_filename_readings WHERE coalesce(array_length(document_kind),0)>0
), linked_family AS (
 SELECT source_id,document_family,requested_filename,requested_url,
  row_number() OVER(PARTITION BY source_id ORDER BY preference) AS choice
 FROM source_linked_filename_readings WHERE coalesce(array_length(document_family),0)>0
), linked_committee AS (
 SELECT source_id,committee_code,requested_filename,requested_url,
  row_number() OVER(PARTITION BY source_id ORDER BY preference) AS choice
 FROM source_linked_filename_readings WHERE coalesce(array_length(committee_code),0)>0
)
SELECT o.source_id,o.filename,o.source_url,o.catalog_version,o.status,o.error_type,o.valid,
 o.status AS shown_status,o.error_type AS shown_error_type,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.document_kind),0)>0 THEN o.document_kind ELSE k.document_kind END AS document_kind,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.document_family),0)>0 THEN o.document_family ELSE g.document_family END AS document_family,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.committee_code),0)>0 THEN o.committee_code ELSE e.committee_code END AS committee_code,
 CASE WHEN o.status='completed' AND o.congress IS NOT NULL THEN o.congress ELSE c.congress END AS congress,
 o.date_token,o.measure_type,o.measure_number,
 CASE WHEN o.status='completed' AND o.filename_date IS NOT NULL THEN o.filename_date ELSE d.filename_date END AS filename_date,
 o.measure_keys,o.bioguide_ids,o.package_id,o.fields,
 l.requested_filename AS linked_filename,l.requested_url AS linked_url,
 l.filename_date AS linked_filename_date,l.congress AS linked_congress,l.document_kind AS linked_document_kind,
 l.document_family AS linked_document_family,l.committee_code AS linked_committee_code,
 -- Raw shown-name values and status remain available independently of the effective choices.
 o.filename_date AS shown_filename_date,o.congress AS shown_congress,o.document_kind AS shown_document_kind,
 o.document_family AS shown_document_family,o.committee_code AS shown_committee_code,
 CASE WHEN o.status='completed' AND o.filename_date IS NOT NULL THEN o.status WHEN d.source_id IS NOT NULL THEN 'completed' ELSE o.status END AS filename_date_status,
 CASE WHEN o.status='completed' AND o.congress IS NOT NULL THEN o.status WHEN c.source_id IS NOT NULL THEN 'completed' ELSE o.status END AS congress_status,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.document_kind),0)>0 THEN o.status WHEN k.source_id IS NOT NULL THEN 'completed' ELSE o.status END AS document_kind_status,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.document_family),0)>0 THEN o.status WHEN g.source_id IS NOT NULL THEN 'completed' ELSE o.status END AS document_family_status,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.committee_code),0)>0 THEN o.status WHEN e.source_id IS NOT NULL THEN 'completed' ELSE o.status END AS committee_code_status,
 CASE WHEN o.status='completed' AND o.filename_date IS NOT NULL THEN o.filename ELSE d.requested_filename END AS filename_date_name,
 CASE WHEN o.status='completed' AND o.filename_date IS NOT NULL THEN o.source_url ELSE d.requested_url END AS filename_date_url,
 CASE WHEN o.status='completed' AND o.congress IS NOT NULL THEN o.filename ELSE c.requested_filename END AS congress_name,
 CASE WHEN o.status='completed' AND o.congress IS NOT NULL THEN o.source_url ELSE c.requested_url END AS congress_url,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.document_kind),0)>0 THEN o.filename ELSE k.requested_filename END AS document_kind_name,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.document_kind),0)>0 THEN o.source_url ELSE k.requested_url END AS document_kind_url,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.document_family),0)>0 THEN o.filename ELSE g.requested_filename END AS document_family_name,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.document_family),0)>0 THEN o.source_url ELSE g.requested_url END AS document_family_url,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.committee_code),0)>0 THEN o.filename ELSE e.requested_filename END AS committee_code_name,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.committee_code),0)>0 THEN o.source_url ELSE e.requested_url END AS committee_code_url,
 NOT (o.status='completed' AND o.filename_date IS NOT NULL) AND d.filename_date IS NOT NULL AS filled_date,
 NOT (o.status='completed' AND o.congress IS NOT NULL) AND c.congress IS NOT NULL AS filled_congress,
 NOT (o.status='completed' AND coalesce(array_length(o.document_kind),0)>0) AND k.source_id IS NOT NULL AS filled_kind,
 NOT (o.status='completed' AND coalesce(array_length(o.document_family),0)>0) AND g.source_id IS NOT NULL AS filled_family,
 NOT (o.status='completed' AND coalesce(array_length(o.committee_code),0)>0) AND e.source_id IS NOT NULL AS filled_committee
FROM own o
 LEFT JOIN linked l ON l.source_id=o.source_id
 LEFT JOIN linked_date d ON d.source_id=o.source_id AND d.choice=1
 LEFT JOIN linked_congress c ON c.source_id=o.source_id AND c.choice=1
 LEFT JOIN linked_kind k ON k.source_id=o.source_id AND k.choice=1
 LEFT JOIN linked_family g ON g.source_id=o.source_id AND g.choice=1
 LEFT JOIN linked_committee e ON e.source_id=o.source_id AND e.choice=1
