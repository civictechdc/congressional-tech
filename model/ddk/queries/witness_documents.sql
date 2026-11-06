SELECT w.witness_key,w.name,l.list_row,l.filename,l.title,lower(hex(d.link_key)) AS link_key
FROM witnesses w JOIN "list" l ON list_contains(l.witness_keys,w.witness_key) JOIN detail d USING (list_row)
WHERE NOT coalesce(l.hidden,false) AND w.witness_key=? ORDER BY l.list_row LIMIT 100