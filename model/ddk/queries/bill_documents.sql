SELECT l.list_row,l.filename,l.title,lower(hex(d.link_key)) AS link_key
FROM "list" l JOIN detail d USING (list_row)
WHERE NOT coalesce(l.hidden,false) AND list_contains(l.measure_keys,?) ORDER BY l.list_row LIMIT 100