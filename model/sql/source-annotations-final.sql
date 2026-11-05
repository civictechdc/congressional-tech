WITH packages AS (
 SELECT source_id,min(package_id) AS package_id FROM source_annotation_addresses
 WHERE package_id IS NOT NULL AND NOT publisher GROUP BY source_id
)
SELECT s.source_id,
 CASE WHEN f.document_kind_status='completed' AND coalesce(array_length(f.document_kind),0)>0
 THEN array_sort(array_distinct(f.document_kind)) ELSE coalesce(k.document_kind,{{EMPTY_STRINGS}}) END AS document_kind,
 coalesce(CASE WHEN f.document_family_status='completed' THEN array_sort(array_distinct(f.document_family)) END,{{EMPTY_STRINGS}}) AS document_family,
 CASE WHEN f.congress_status='completed' THEN f.congress END AS congress,
 -- A filename names a package only in GovInfo's own form (govinfo.gov/help/{bills,chrg,crpt,cprt,cdoc});
 -- a granule's part, volume or errata suffix names its package. Look-alike committee-site names
 -- (BILLS-117hr1833ih-Katko, BILLS-1171833ih, CHRG-116hhrg43625-add2) name none.
 coalesce(u.package_id,CASE WHEN f.status='completed' THEN coalesce(
  (regexp_match(f.package_id,'^(BILLS-[1-9][0-9]{0,2}(?:hr|s|hjres|sjres|hconres|sconres|hres|sres)[1-9][0-9]*[a-z]+)$'))[1],
  (regexp_match(f.package_id,'^(CHRG-[1-9][0-9]{0,2}[hsj]hrg[0-9]+)(?:-vol[0-9]+)?(?:-pt[0-9]+)?(?:-err[0-9]*)?$'))[1],
  (regexp_match(f.package_id,'^(CRPT-[1-9][0-9]{0,2}(?:hrpt|srpt|erpt)[1-9][0-9]*)(?:-vol[0-9]+)?(?:-pt[0-9]+)?(?:-ERRATA[0-9]*)?$'))[1],
  (regexp_match(f.package_id,'^(CPRT-[1-9][0-9]{0,2}[HSJ]PRT[0-9]+)$'))[1],
  (regexp_match(f.package_id,'^(CDOC-[1-9][0-9]{0,2}(?:hdoc|sdoc|tdoc)[0-9]+)$'))[1]) END) AS package_id,
 CASE WHEN f.filename_date_status='completed' THEN f.filename_date END AS filename_date,
 CASE WHEN p.status='completed' THEN cast(p.content_date AS DATE) END AS content_date,
 coalesce(CASE WHEN p.status='completed' AND nullif(trim(p.title),'') IS NOT NULL THEN p.title END,
 CASE WHEN p.status='completed' AND nullif(trim(p.heading),'') IS NOT NULL THEN p.heading END,k.listing_title) AS title,
 coalesce(CASE WHEN p.status='completed' AND nullif(trim(p.title),'') IS NOT NULL THEN p.title END,
 CASE WHEN p.status='completed' AND nullif(trim(p.heading),'') IS NOT NULL THEN p.heading END) AS reading_title,
 k.listing_title,
 coalesce(m.meeting_keys,{{EMPTY_STRINGS}}) AS meeting_keys,
 coalesce(CASE WHEN f.status='completed' THEN array_sort(array_distinct(f.measure_keys)) END,{{EMPTY_STRINGS}}) AS measure_keys,
 coalesce(CASE WHEN f.status='completed' THEN array_sort(array_distinct(f.bioguide_ids)) END,{{EMPTY_STRINGS}}) AS bioguide_ids,
 coalesce(c.committee_keys,{{EMPTY_STRINGS}}) AS committee_keys,
 array_sort(array_distinct(array_concat(coalesce(c.chambers,{{EMPTY_STRINGS}}),coalesce(m.chambers,{{EMPTY_STRINGS}})))) AS chambers,
 coalesce(d.facts,{{EMPTY_FACTS}}) AS facts,f.status AS filename_status
FROM packages u RIGHT JOIN (
 source_annotation_meetings m RIGHT JOIN (
  source_annotation_facts d RIGHT JOIN (
   source_annotation_committees c RIGHT JOIN (
    source_annotation_publisher k RIGHT JOIN (
     source_annotation_pages p RIGHT JOIN (
      source_files s LEFT JOIN source_filename_readings f ON s.source_id=f.source_id
     ) ON s.body_sha=encode(p.body_sha,'hex')
    ) ON s.source_id=k.source_id
   ) ON s.source_id=c.source_id
  ) ON s.source_id=d.source_id
 ) ON s.source_id=m.source_id
) ON s.source_id=u.source_id
