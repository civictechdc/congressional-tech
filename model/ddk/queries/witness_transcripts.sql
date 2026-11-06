WITH w AS (SELECT witness_key,name FROM witnesses WHERE witness_key=?),
  packages AS (SELECT DISTINCT p.package_id FROM witnesses p, w WHERE p.package_id IS NOT NULL AND (p.witness_key=w.witness_key OR p.superseded_by=w.witness_key))
SELECT w.witness_key,w.name,d.package_id,l.list_row,l.filename,l.title,lower(hex(d.link_key)) AS link_key
FROM w, packages k JOIN detail d ON d.package_id=k.package_id JOIN "list" l USING (list_row)
WHERE NOT coalesce(l.hidden,false) ORDER BY l.list_row LIMIT 100