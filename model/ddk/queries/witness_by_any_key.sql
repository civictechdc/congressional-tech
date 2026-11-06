WITH k AS (SELECT ? AS key)
SELECT w.witness_key,w.name,w.occasion,w.superseded_by,m.old_key,m.status
FROM k LEFT JOIN witness_key_map m ON m.old_key=k.key
JOIN witnesses w ON w.witness_key=coalesce(m.witness_key,k.key)