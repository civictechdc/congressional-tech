-- Physical sizes come from creating lines or verification, never a guessed ratio.
WITH stored AS (
 SELECT encode(sha256,'hex') AS body_sha,max(bytes) AS original_size,
 bool_or(stored_suffix='') AS bare,
 max(CASE WHEN stored_suffix='' THEN stored_bytes END) AS bare_size,
 max(CASE WHEN stored_suffix='.gz' THEN stored_bytes END) AS gzip_size
 FROM captures WHERE sha256 IS NOT NULL GROUP BY sha256
), keys AS (
 SELECT *,'bodies/sha256/'||substr(body_sha,1,2)||'/'||body_sha AS body_key FROM stored
)
SELECT b.body_sha,b.original_size,coalesce(s.format,a.format) AS format,coalesce(v.intact,s.intact) AS intact,
 CASE WHEN v.intact IS NOT NULL THEN 'copy' WHEN s.intact IS NOT NULL THEN s.intact_basis ELSE 'unchecked' END AS intact_basis,
 s.error_type,CASE WHEN v.body_sha IS NOT NULL AND s.format='pdf' THEN '.pdf'
 WHEN b.bare THEN '' ELSE '.gz' END AS suffix,
 CASE WHEN v.body_sha IS NOT NULL AND s.format='pdf' THEN pdf.size
 WHEN b.bare THEN coalesce(b.bare_size,bare.size) ELSE coalesce(b.gzip_size,gz.size) END AS stored_size
-- Keep corpus-sized body rows on the streamed side of every evidence join.
FROM storage_verifications gz RIGHT JOIN (
 storage_verifications bare RIGHT JOIN (
  storage_verifications pdf RIGHT JOIN (
   copy_verifications v RIGHT JOIN (
    body_admissions a RIGHT JOIN (
     sniff_facts s RIGHT JOIN (
      verification_conflicts c RIGHT ANTI JOIN keys b ON c.body_sha=b.body_sha
     ) ON b.body_sha=encode(s.body_sha,'hex')
    ) ON b.body_sha=encode(a.body_sha,'hex')
   ) ON b.body_sha=v.body_sha
  ) ON pdf.key=b.body_key||'.pdf'
 ) ON bare.key=b.body_key
) ON gz.key=b.body_key||'.gz'
