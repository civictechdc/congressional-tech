SELECT
 cast(congress AS SMALLINT) AS congress,
 lower(system_code) AS system_code,
 bioguide_id,
 nullif(trim(position),'') AS title,
 try_cast(cast(rank AS VARCHAR) AS SMALLINT) AS rank,
 nullif(trim(party),'') AS party
FROM spicy_committee_assignments
WHERE system_code IS NOT NULL AND bioguide_id IS NOT NULL
