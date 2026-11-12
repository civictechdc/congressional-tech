WITH hhrg_slugs AS (
 SELECT DISTINCT
  dm.component,
  smc.event_id,
  regexp_replace(
   lower((regexp_match(sf.filename,'(?i)^(?:[0-9a-f]{64}[.])?(?:HHRG|HMTG)-[0-9]+-[A-Z0-9]+-(?:Wstate|TTF|Bio)-([A-Za-z0-9''-]+)-[0-9]{8}'))[1]),
   '[^a-z0-9]','','g'
  ) AS norm_slug
 FROM document_members dm
 JOIN source_files sf ON sf.source_id=dm.source_id
 JOIN document_witness_single_meeting_components smc ON smc.component=dm.component
 WHERE NOT EXISTS (SELECT 1 FROM document_witness_chrg_components c WHERE c.component=dm.component)
  AND NOT EXISTS (SELECT 1 FROM document_witness_url_matches u WHERE u.component=dm.component)
  AND regexp_like(sf.filename,'(?i)^(?:[0-9a-f]{64}[.])?(?:HHRG|HMTG)-[0-9]+-[A-Z0-9]+-(?:Wstate|TTF|Bio)-[A-Za-z0-9''-]+-[0-9]{8}')
 UNION
 SELECT DISTINCT
  r.component,
  smc.event_id,
  regexp_replace(
   lower((regexp_match(n.filename,'(?i)^(?:[0-9a-f]{64}[.])?(?:HHRG|HMTG)-[0-9]+-[A-Z0-9]+-(?:Wstate|TTF|Bio)-([A-Za-z0-9''-]+)-[0-9]{8}'))[1]),
   '[^a-z0-9]','','g'
  ) AS norm_slug
 FROM saved_recoveries r
 JOIN effective_filenames n ON n.input_id='recovery:'||r.id
 JOIN document_witness_single_meeting_components smc ON smc.component=r.component
 WHERE NOT EXISTS (SELECT 1 FROM document_witness_chrg_components c WHERE c.component=r.component)
  AND NOT EXISTS (SELECT 1 FROM document_witness_url_matches u WHERE u.component=r.component)
  AND regexp_like(n.filename,'(?i)^(?:[0-9a-f]{64}[.])?(?:HHRG|HMTG)-[0-9]+-[A-Z0-9]+-(?:Wstate|TTF|Bio)-[A-Za-z0-9''-]+-[0-9]{8}')
), unique_family_per_event AS (
 SELECT event_id,norm_family
 FROM document_witness_meeting_witnesses
 GROUP BY event_id,norm_family
 HAVING min(witness_key)=max(witness_key)
), witness_slug_candidates AS (
 SELECT event_id,witness_key,norm_family_init AS norm_slug
 FROM document_witness_meeting_witnesses
 WHERE norm_family_init<>''
 UNION
 SELECT w.event_id,w.witness_key,w.norm_family AS norm_slug
 FROM document_witness_meeting_witnesses w
 JOIN unique_family_per_event u ON u.event_id=w.event_id AND u.norm_family=w.norm_family
 WHERE w.norm_family<>''
), unambiguous_slug_witness AS (
 SELECT event_id,norm_slug,min(witness_key) AS witness_key
 FROM witness_slug_candidates
 GROUP BY event_id,norm_slug
 HAVING min(witness_key)=max(witness_key)
), slug_matched_members AS (
 SELECT DISTINCT h.component,u.witness_key
 FROM hhrg_slugs h
 JOIN unambiguous_slug_witness u ON u.event_id=h.event_id AND u.norm_slug=h.norm_slug
 WHERE h.norm_slug<>''
), chrg_packages AS (
 SELECT DISTINCT component,package_id FROM document_packages WHERE regexp_like(package_id,'(?i)^CHRG-')
 UNION
 SELECT DISTINCT r.component,a.package_id
 FROM saved_recoveries r
 JOIN effective_filenames n ON n.input_id='recovery:'||r.id
 JOIN source_files f ON f.body_sha IS NULL AND f.source_url=r.original_url AND f.filename=n.filename
 JOIN source_annotations a ON f.source_id=a.source_id
 WHERE regexp_like(a.package_id,'(?i)^CHRG-')
)
SELECT component,witness_key FROM document_witness_url_matches
UNION
SELECT component,witness_key FROM slug_matched_members
UNION
SELECT DISTINCT p.component,w.witness_key
FROM chrg_packages p
JOIN appearance_records_resolved w ON w.package_id=p.package_id
WHERE w.package_id IS NOT NULL
