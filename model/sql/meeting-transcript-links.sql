-- A meeting's jacket names a package; a package named anywhere we hold (annotations, document
-- packages, appearance records or a capture address) links when its congress, chamber and jacket match.
-- Capture addresses are parsed per row and joined to the meetings' small jacket set before any
-- DISTINCT (AGENTS.md candidate rule): DISTINCT over all captures exhausts the aggregate memory cap.
WITH meeting_jackets AS (
 SELECT event_id,congress,chamber,meeting_date,unnest(transcript_jackets) AS jacket
 FROM meetings_resolved
 WHERE transcript_jackets IS NOT NULL
), named_packages AS (
 SELECT package_id FROM source_annotations WHERE package_id IS NOT NULL
 UNION ALL
 SELECT package_id FROM document_packages WHERE package_id IS NOT NULL
 UNION ALL
 SELECT nullif(trim(r.package_id),'') AS package_id
 FROM selected_appearance_records r
 WHERE r.status='completed' AND r.package_id IS NOT NULL AND trim(r.package_id)<>''
 UNION ALL
 SELECT (regexp_match(coalesce(c.url,c.requested_url,c.context_url,c.member_path,''),'(?i)(CHRG-[0-9]+[hsj]hrg[0-9]+)'))[1] AS package_id
 FROM captures c
 WHERE regexp_like(coalesce(c.url,c.requested_url,c.context_url,c.member_path,''),'(?i)CHRG-[0-9]+[hsj]hrg[0-9]+')
), parsed_packages AS (
 SELECT package_id,
  try_cast((regexp_match(package_id,'(?i)^CHRG-([0-9]+)([hsj])hrg0*([0-9]+)$'))[1] AS INT) AS congress,
  lower((regexp_match(package_id,'(?i)^CHRG-([0-9]+)([hsj])hrg0*([0-9]+)$'))[2]) AS chamber_letter,
  try_cast((regexp_match(package_id,'(?i)^CHRG-([0-9]+)([hsj])hrg0*([0-9]+)$'))[3] AS BIGINT) AS jacket
 FROM named_packages
 WHERE regexp_like(package_id,'(?i)^CHRG-[0-9]+[hsj]hrg[0-9]+$')
), linked_print_meetings AS (
 SELECT DISTINCT dp.package_id,try_cast(mk.meeting_key AS BIGINT) AS event_id,
  lower((regexp_match(dp.package_id,'(?i)^CHRG-[0-9]+([hsj])hrg[0-9]+$'))[1]) AS chamber_letter
 FROM document_packages dp
 JOIN (SELECT component,unnest(meeting_keys) AS meeting_key FROM document_metadata WHERE coalesce(cardinality(meeting_keys),0)>0) mk
  ON mk.component=dp.component
 WHERE regexp_like(dp.package_id,'(?i)^CHRG-[0-9]+[hsj]hrg[0-9]+$')
)
SELECT DISTINCT p.package_id,m.event_id,m.meeting_date,m.chamber
FROM parsed_packages p
JOIN meeting_jackets m ON p.congress=m.congress AND p.jacket=m.jacket
WHERE m.chamber IS NULL
   OR (m.chamber='house' AND p.chamber_letter='h')
   OR (m.chamber='senate' AND p.chamber_letter='s')
   OR (m.chamber='joint' AND p.chamber_letter='j')
UNION
SELECT package_id,event_id,meeting_date,chamber FROM meeting_mods_links
UNION
SELECT DISTINCT l.package_id,m.event_id,m.meeting_date,m.chamber
FROM linked_print_meetings l
JOIN print_meeting_agreement a ON a.package_id=l.package_id AND a.event_id=l.event_id
JOIN meetings_resolved m ON m.event_id=l.event_id
WHERE m.chamber IS NULL
   OR (m.chamber='house' AND l.chamber_letter='h')
   OR (m.chamber='senate' AND l.chamber_letter='s')
   OR (m.chamber='joint' AND l.chamber_letter='j')
