WITH matched AS (
  SELECT t.list_row,list(DISTINCT m.event_id ORDER BY m.event_id) AS meeting_ids
  FROM meetings m,UNNEST(m.transcripts) AS u(t)
  WHERE list_contains(m.subject_keys,?) GROUP BY t.list_row
)
SELECT l.list_row,l.filename,l.title,lower(hex(d.link_key)) AS link_key,matched.meeting_ids
FROM matched JOIN "list" l USING (list_row) JOIN detail d USING (list_row)
WHERE NOT coalesce(l.hidden,false) ORDER BY l.list_row LIMIT 100