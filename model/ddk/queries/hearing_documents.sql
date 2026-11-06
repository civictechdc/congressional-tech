SELECT l.list_row,l.filename,l.title,lower(hex(d.link_key)) AS link_key,m.event_id,m.title AS hearing
FROM "list" l JOIN detail d USING (list_row) JOIN meetings m ON list_contains(l.meeting_keys,CAST(m.event_id AS VARCHAR))
WHERE NOT coalesce(l.hidden,false) AND m.event_id=? ORDER BY l.list_row LIMIT 100