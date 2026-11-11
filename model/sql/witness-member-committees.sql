-- ct-kw85, owner decision 2026-11-10: a committee member's own opening statement at the hearing is a Member statement,
-- not a Member appearance ('Member appearance' keeps meaning a Member who came before the committee). For each
-- appearance (witness_precedence person) one of whose rows says 'opening statement', the Members the pinned rosters
-- (roster_seats) seat, in the Congress of the hearing date, on the hearing's committee or on its parent committee.
-- The hearing's committees are the meeting's (meetings_resolved), else those of the print's own documents
-- (document_packages, document_metadata: their committee keys and the committees of the meetings they name). A
-- parent is a subcommittee code's first four letters and '00' ('hsag22' -> 'hsag00'): the full committee's chair and
-- ranking member sit on every subcommittee and open its hearings, but rosters seat them on the full committee only.
-- The print's own member list is not read: it omits members the rosters hold. Rosters hold the 113th Congress on, so
-- earlier opening statements keep their Member appearance.
WITH opening AS (
 SELECT DISTINCT person,event_id,package_id,dates[1] AS day FROM witness_member_facts
 WHERE says_opening AND coalesce(cardinality(dates),0)>0
), print_documents AS (
 SELECT o.person,o.day,dm.committee_keys,dm.meeting_keys
 FROM (SELECT person,day,package_id FROM opening WHERE event_id IS NULL) o
  JOIN document_packages dp ON dp.package_id=o.package_id JOIN document_metadata dm ON dm.component=dp.component
), codes AS (
 SELECT o.person,o.day,lower(trim(c['system_code'])) AS code
 FROM (SELECT person,day,event_id FROM opening WHERE event_id IS NOT NULL) o
  JOIN (SELECT event_id,unnest(committees) AS c FROM meetings_resolved) m ON m.event_id=o.event_id
 UNION ALL
 SELECT person,day,lower(trim(code)) AS code FROM (SELECT person,day,unnest(committee_keys) AS code FROM print_documents)
 UNION ALL
 SELECT d.person,d.day,lower(trim(c['system_code'])) AS code
 FROM (SELECT person,day,try_cast(meeting_key AS BIGINT) AS event_id
  FROM (SELECT person,day,unnest(meeting_keys) AS meeting_key FROM print_documents)) d
  JOIN (SELECT event_id,unnest(committees) AS c FROM meetings_resolved) m ON m.event_id=d.event_id
), seats AS (
 SELECT DISTINCT person,code,
  -- The Congress of the hearing date: each begins on 3 January of an odd year.
  cast((cast(substr(day,1,4) AS INT)-CASE WHEN substr(day,6,5)<'01-03' THEN 1 ELSE 0 END-1789)/2+1 AS SMALLINT) AS congress
 FROM (SELECT person,day,code FROM codes UNION ALL SELECT person,day,substr(code,1,4)||'00' AS code FROM codes)
 WHERE code IS NOT NULL AND code<>'' AND day IS NOT NULL
)
SELECT DISTINCT s.person,r.bioguide_id
FROM seats s JOIN roster_seats r ON r.system_code=s.code AND r.congress=s.congress
