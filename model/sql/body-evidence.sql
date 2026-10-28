-- Physical sizes come from creating lines or verification, never a guessed ratio.
WITH stored AS (
 SELECT encode(sha256,'hex') AS body_sha,
 bool_or(stored_suffix='') AS bare,
 max(CASE WHEN stored_suffix='' THEN stored_bytes END) AS bare_size,
 max(CASE WHEN stored_suffix='.gz' THEN stored_bytes END) AS gzip_size
 FROM captures WHERE sha256 IS NOT NULL GROUP BY sha256
)
SELECT b.body_sha,s.format,coalesce(v.intact,s.intact) AS intact,
 CASE WHEN v.intact IS NOT NULL THEN 'copy' WHEN s.intact IS NOT NULL THEN 'read' ELSE 'unchecked' END AS intact_basis,
 s.error_type,CASE WHEN v.body_sha IS NOT NULL AND s.format='pdf' THEN '.pdf'
 WHEN b.bare THEN '' ELSE '.gz' END AS suffix,
 CASE WHEN v.body_sha IS NOT NULL AND s.format='pdf' THEN v.size
 WHEN b.bare THEN b.bare_size ELSE b.gzip_size END AS stored_size
FROM stored b LEFT JOIN sniff_facts s ON b.body_sha=encode(s.body_sha,'hex')
LEFT JOIN copy_verifications v ON b.body_sha=v.body_sha
