SELECT n.nomination_id,d.package_id,l.list_row,l.filename,l.title,lower(hex(d.link_key)) AS link_key
FROM nominations n JOIN detail d ON list_contains(n.transcripts,d.package_id) JOIN "list" l USING (list_row)
WHERE NOT coalesce(l.hidden,false) AND n.nomination_id=? ORDER BY l.list_row LIMIT 100