SELECT m.event_id,m.title,m.meeting_date,m.chamber,r.congress,r.event_id IS NOT NULL AS has_record,
 k.committee_codes,k.committee_names
FROM meetings_export m
LEFT JOIN (SELECT event_id,cast(congress AS VARCHAR) AS congress FROM meetings_resolved) r ON m.event_id=r.event_id
LEFT JOIN (
 SELECT h.event_id,array_agg(h.system_code) AS committee_codes,
  array_to_string(array_sort(array_distinct(array_agg(c.name))),' | ') AS committee_names
 FROM (SELECT event_id,unnest(committees)['system_code'] AS system_code FROM meetings_export) h
 LEFT JOIN committees_export c ON c.system_code=h.system_code
 GROUP BY h.event_id
) k ON m.event_id=k.event_id
