WITH candidate_packages AS (
 SELECT DISTINCT package_id FROM source_annotations WHERE package_id IS NOT NULL
 UNION
 SELECT DISTINCT package_id FROM document_packages WHERE package_id IS NOT NULL
 UNION
 SELECT DISTINCT a['package_id'] AS package_id FROM (
  SELECT unnest(appearances) AS a FROM appearance_records_input WHERE status='completed' AND appearances IS NOT NULL
 ) WHERE a['package_id'] IS NOT NULL
), parsed_packages AS (
 SELECT package_id,
  try_cast((regexp_match(package_id,'(?i)^CHRG-([0-9]+)([hsj])hrg0*([0-9]+)$'))[1] AS INT) AS congress,
  lower((regexp_match(package_id,'(?i)^CHRG-([0-9]+)([hsj])hrg0*([0-9]+)$'))[2]) AS chamber_letter,
  try_cast((regexp_match(package_id,'(?i)^CHRG-([0-9]+)([hsj])hrg0*([0-9]+)$'))[3] AS BIGINT) AS jacket
 FROM candidate_packages
 WHERE regexp_like(package_id,'(?i)^CHRG-[0-9]+[hsj]hrg[0-9]+$')
), meeting_jackets AS (
 SELECT event_id,congress,chamber,meeting_date,unnest(transcript_jackets) AS jacket
 FROM meetings_resolved
 WHERE transcript_jackets IS NOT NULL
)
SELECT DISTINCT p.package_id,m.event_id,m.meeting_date,m.chamber
FROM parsed_packages p
JOIN meeting_jackets m ON p.congress=m.congress AND p.jacket=m.jacket
WHERE m.chamber IS NULL
   OR (m.chamber='house' AND p.chamber_letter='h')
   OR (m.chamber='senate' AND p.chamber_letter='s')
   OR (m.chamber='joint' AND p.chamber_letter='j')
