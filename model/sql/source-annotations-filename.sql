-- Filename producers own typed keys; the model joins their exact admitted pair.
-- Both names (owner, 2026-11-02): a completed, nonempty shown value has precedence. Otherwise each
-- field takes the first completed linked reading that supplies it, in canonical URL/name order, and
-- keeps that supplier's name and URL. Shown status/error stay separate from the per-field suppliers.
WITH own AS (
 SELECT s.source_id,
  f.* EXCLUDE(document_kind,document_family,committee_code),
  -- Normalize Iceberg element field ids before these values meet the aggregated linked choices.
  arrow_cast(f.document_kind,'List(Utf8)') AS document_kind,
  arrow_cast(f.document_family,'List(Utf8)') AS document_family,
  arrow_cast(f.committee_code,'List(Utf8)') AS committee_code
 FROM source_files s JOIN filename_readings f
  ON s.filename=f.filename AND coalesce(s.source_url,'')=f.source_url
 WHERE f.catalog_version={{CATALOG_VERSION}}
), choices AS (
 -- One scan and one choices join: window the five supplying subsets together, then fold each
 -- field's first row and the canonical linked row. Separate per-field joins exhaust the pool.
 SELECT source_id,
  max(requested_filename) FILTER (WHERE preference=1) AS linked_filename,
  max(requested_url) FILTER (WHERE preference=1) AS linked_url,
  max(filename_date) FILTER (WHERE preference=1) AS linked_filename_date,
  max(congress) FILTER (WHERE preference=1) AS linked_congress,
  max(document_kind) FILTER (WHERE preference=1) AS linked_document_kind,
  max(document_family) FILTER (WHERE preference=1) AS linked_document_family,
  max(committee_code) FILTER (WHERE preference=1) AS linked_committee_code,
  max(filename_date) FILTER (WHERE date_choice=1) AS filename_date,
  max(requested_filename) FILTER (WHERE date_choice=1) AS date_name,
  max(requested_url) FILTER (WHERE date_choice=1) AS date_url,
  max(congress) FILTER (WHERE congress_choice=1) AS congress,
  max(requested_filename) FILTER (WHERE congress_choice=1) AS congress_name,
  max(requested_url) FILTER (WHERE congress_choice=1) AS congress_url,
  max(document_kind) FILTER (WHERE kind_choice=1) AS document_kind,
  max(requested_filename) FILTER (WHERE kind_choice=1) AS kind_name,
  max(requested_url) FILTER (WHERE kind_choice=1) AS kind_url,
  max(document_family) FILTER (WHERE family_choice=1) AS document_family,
  max(requested_filename) FILTER (WHERE family_choice=1) AS family_name,
  max(requested_url) FILTER (WHERE family_choice=1) AS family_url,
  max(committee_code) FILTER (WHERE committee_choice=1) AS committee_code,
  max(requested_filename) FILTER (WHERE committee_choice=1) AS committee_name,
  max(requested_url) FILTER (WHERE committee_choice=1) AS committee_url
 FROM (
  SELECT l.*,
   CASE WHEN filename_date IS NOT NULL THEN row_number() OVER(
    PARTITION BY source_id ORDER BY filename_date IS NULL,preference) END AS date_choice,
   CASE WHEN congress IS NOT NULL THEN row_number() OVER(
    PARTITION BY source_id ORDER BY congress IS NULL,preference) END AS congress_choice,
   CASE WHEN coalesce(array_length(document_kind),0)>0 THEN row_number() OVER(
    PARTITION BY source_id ORDER BY coalesce(array_length(document_kind),0)=0,preference) END AS kind_choice,
   CASE WHEN coalesce(array_length(document_family),0)>0 THEN row_number() OVER(
    PARTITION BY source_id ORDER BY coalesce(array_length(document_family),0)=0,preference) END AS family_choice,
   CASE WHEN coalesce(array_length(committee_code),0)>0 THEN row_number() OVER(
    PARTITION BY source_id ORDER BY coalesce(array_length(committee_code),0)=0,preference) END AS committee_choice
  FROM source_linked_filename_readings l
 ) l GROUP BY source_id
)
SELECT o.source_id,o.filename,o.source_url,o.catalog_version,o.status,o.error_type,o.valid,
 o.status AS shown_status,o.error_type AS shown_error_type,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.document_kind),0)>0 THEN o.document_kind ELSE l.document_kind END AS document_kind,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.document_family),0)>0 THEN o.document_family ELSE l.document_family END AS document_family,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.committee_code),0)>0 THEN o.committee_code ELSE l.committee_code END AS committee_code,
 CASE WHEN o.status='completed' AND o.congress IS NOT NULL THEN o.congress ELSE l.congress END AS congress,
 o.date_token,o.measure_type,o.measure_number,
 CASE WHEN o.status='completed' AND o.filename_date IS NOT NULL THEN o.filename_date ELSE l.filename_date END AS filename_date,
 o.measure_keys,o.bioguide_ids,o.package_id,o.fields,
 l.linked_filename,l.linked_url,l.linked_filename_date,l.linked_congress,l.linked_document_kind,
 l.linked_document_family,l.linked_committee_code,
 -- Raw shown-name values and status remain available independently of the effective choices.
 o.filename_date AS shown_filename_date,o.congress AS shown_congress,o.document_kind AS shown_document_kind,
 o.document_family AS shown_document_family,o.committee_code AS shown_committee_code,
 CASE WHEN o.status='completed' AND o.filename_date IS NOT NULL THEN o.status WHEN l.filename_date IS NOT NULL THEN 'completed' ELSE o.status END AS filename_date_status,
 CASE WHEN o.status='completed' AND o.congress IS NOT NULL THEN o.status WHEN l.congress IS NOT NULL THEN 'completed' ELSE o.status END AS congress_status,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.document_kind),0)>0 THEN o.status WHEN l.document_kind IS NOT NULL THEN 'completed' ELSE o.status END AS document_kind_status,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.document_family),0)>0 THEN o.status WHEN l.document_family IS NOT NULL THEN 'completed' ELSE o.status END AS document_family_status,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.committee_code),0)>0 THEN o.status WHEN l.committee_code IS NOT NULL THEN 'completed' ELSE o.status END AS committee_code_status,
 CASE WHEN o.status='completed' AND o.filename_date IS NOT NULL THEN o.filename ELSE l.date_name END AS filename_date_name,
 CASE WHEN o.status='completed' AND o.filename_date IS NOT NULL THEN o.source_url ELSE l.date_url END AS filename_date_url,
 CASE WHEN o.status='completed' AND o.congress IS NOT NULL THEN o.filename ELSE l.congress_name END AS congress_name,
 CASE WHEN o.status='completed' AND o.congress IS NOT NULL THEN o.source_url ELSE l.congress_url END AS congress_url,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.document_kind),0)>0 THEN o.filename ELSE l.kind_name END AS document_kind_name,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.document_kind),0)>0 THEN o.source_url ELSE l.kind_url END AS document_kind_url,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.document_family),0)>0 THEN o.filename ELSE l.family_name END AS document_family_name,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.document_family),0)>0 THEN o.source_url ELSE l.family_url END AS document_family_url,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.committee_code),0)>0 THEN o.filename ELSE l.committee_name END AS committee_code_name,
 CASE WHEN o.status='completed' AND coalesce(array_length(o.committee_code),0)>0 THEN o.source_url ELSE l.committee_url END AS committee_code_url,
 NOT (o.status='completed' AND o.filename_date IS NOT NULL) AND l.filename_date IS NOT NULL AS filled_date,
 NOT (o.status='completed' AND o.congress IS NOT NULL) AND l.congress IS NOT NULL AS filled_congress,
 NOT (o.status='completed' AND coalesce(array_length(o.document_kind),0)>0) AND l.document_kind IS NOT NULL AS filled_kind,
 NOT (o.status='completed' AND coalesce(array_length(o.document_family),0)>0) AND l.document_family IS NOT NULL AS filled_family,
 NOT (o.status='completed' AND coalesce(array_length(o.committee_code),0)>0) AND l.committee_code IS NOT NULL AS filled_committee
FROM own o LEFT JOIN choices l ON l.source_id=o.source_id
