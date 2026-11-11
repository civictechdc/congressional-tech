-- ct-kw85, owner decision 2026-11-10: a committee member's own opening statement at the hearing is a Member statement,
-- not a Member appearance ('Member appearance' keeps meaning a Member who came before the committee). For each
-- appearance (witness_precedence person) one of whose rows says 'opening statement', the Members seated, in the
-- Congress of the hearing date, on the hearing's committee or on its parent committee.
-- The hearing's committees are the meeting's (meetings_resolved); when the meeting names none, or there is no meeting,
-- those of the print: its own documents' committee keys and the committees of the meetings they name
-- (document_packages, document_metadata), and the print's own MODS committee codes (package_mods_facts). A parent is a
-- subcommittee code's first four letters and '00' ('hsag22' -> 'hsag00'): the full committee's chair and ranking
-- member sit on every subcommittee and open its hearings, but rosters seat them on the full committee only.
-- Seated: the pinned rosters (roster_seats), and, for a Congress the rosters do not hold (before the 113th), the
-- print's own MODS committee member list (package_mods_facts.committee_members). That list omits members the
-- rosters hold, so it is read only where no roster seat can be.
WITH opening AS (
 SELECT DISTINCT person,event_id,package_id,dates[1] AS day,
  -- The Congress of the hearing date: each begins on 3 January of an odd year.
  cast((cast(substr(dates[1],1,4) AS INT)-CASE WHEN substr(dates[1],6,5)<'01-03' THEN 1 ELSE 0 END-1789)/2+1 AS SMALLINT) AS congress
 FROM witness_member_facts WHERE says_opening AND coalesce(cardinality(dates),0)>0
), meeting_codes AS (
 SELECT o.person,o.congress,lower(trim(c['system_code'])) AS code
 FROM (SELECT person,congress,event_id FROM opening WHERE event_id IS NOT NULL) o
  JOIN (SELECT event_id,unnest(committees) AS c FROM meetings_resolved) m ON m.event_id=o.event_id
), prints AS (
 -- Appearances whose meeting names no committee read their print's.
 SELECT o.person,o.congress,o.package_id FROM (SELECT DISTINCT person FROM meeting_codes) m RIGHT ANTI JOIN opening o ON o.person=m.person
 WHERE o.package_id IS NOT NULL
), print_documents AS (
 SELECT p.person,p.congress,dm.committee_keys,dm.meeting_keys
 FROM prints p JOIN document_packages dp ON dp.package_id=p.package_id JOIN document_metadata dm ON dm.component=dp.component
), codes AS (
 SELECT person,congress,code FROM meeting_codes
 UNION ALL
 SELECT person,congress,lower(trim(code)) AS code FROM (SELECT person,congress,unnest(committee_keys) AS code FROM print_documents)
 UNION ALL
 SELECT d.person,d.congress,lower(trim(c['system_code'])) AS code
 FROM (SELECT person,congress,try_cast(meeting_key AS BIGINT) AS event_id
  FROM (SELECT person,congress,unnest(meeting_keys) AS meeting_key FROM print_documents)) d
  JOIN (SELECT event_id,unnest(committees) AS c FROM meetings_resolved) m ON m.event_id=d.event_id
 UNION ALL
 SELECT person,congress,lower(trim(code)) AS code
 FROM (SELECT p.person,p.congress,unnest(f.committees) AS code FROM prints p JOIN package_mods_facts f ON f.package_id=p.package_id)
), seats AS (
 SELECT DISTINCT person,code,congress
 FROM (SELECT person,congress,code FROM codes UNION ALL SELECT person,congress,substr(code,1,4)||'00' AS code FROM codes)
 WHERE code IS NOT NULL AND code<>''
), held AS (
 SELECT DISTINCT congress FROM roster_seats
)
SELECT DISTINCT s.person,r.bioguide_id
FROM seats s JOIN roster_seats r ON r.system_code=s.code AND r.congress=s.congress
UNION
-- Before the rosters: the print's own committee member list.
SELECT o.person,upper(trim(m)) AS bioguide_id
FROM (SELECT person,unnest(f.committee_members) AS m
 FROM (SELECT o.person,o.package_id FROM held h RIGHT ANTI JOIN opening o ON o.congress=h.congress WHERE o.package_id IS NOT NULL) o
 JOIN package_mods_facts f ON f.package_id=o.package_id) o
