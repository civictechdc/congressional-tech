-- The publisher's page summary per html document, never the title or the site's own description.
-- Rejected: empty, equal to <title> or a declared site name (trim, casefold), declared on a JSON-LD
-- site node, a registry site template, or repeated across at least the registry threshold of
-- distinct bodies on one host. Kept values order by registry format rank, then pointer.
WITH docs AS (
 SELECT doc_key,arrow_cast(decode(body_hex,'hex'),'FixedSizeBinary(32)') AS body_sha,
  coalesce(regexp_replace(lower(array_element(regexp_match(source_url,'^[a-zA-Z][a-zA-Z0-9+.-]*://([^/?#:]*)'),1)),'^www[.]',''),'') AS host
 FROM base_normalized WHERE format='html' AND body_hex IS NOT NULL
), described AS (
 SELECT v.body_sha,v.value,v.path,v.format,lower(trim(v.value)) AS folded,
  regexp_replace(v.path,'/description(/[0-9]+)?$','') AS node
 FROM page_metadata_values v WHERE v.field='description'
), site_nodes AS (
 SELECT DISTINCT v.body_sha,regexp_replace(v.path,'/@type(/[0-9]+)?$','') AS node
 FROM page_metadata_values v JOIN page_signals s ON s.kind='site_node_type' AND regexp_like(v.value,s.pattern)
 WHERE v.field='declared_type'
), names AS (
 SELECT body_sha,lower(trim(value)) AS folded FROM page_metadata_values WHERE field='site_name'
 UNION SELECT body_sha,lower(trim(title)) FROM html_metadata_readings WHERE title IS NOT NULL
), repeats AS (
 SELECT host,folded,count(*) AS bodies FROM (
  SELECT DISTINCT d.host,x.folded,d.body_sha
  FROM docs d JOIN described x ON x.body_sha=d.body_sha
 ) GROUP BY host,folded
), named AS (
 SELECT DISTINCT body_sha,folded FROM names
), templated AS (
 SELECT DISTINCT x.body_sha,x.path FROM described x JOIN page_signals t ON t.kind='description_template' AND regexp_like(x.folded,t.pattern)
), threshold AS (
 SELECT min(number) AS bodies FROM page_signals WHERE kind='description_repeat'
), candidates AS (
 SELECT d.doc_key,x.*,
  x.folded='' OR n.body_sha IS NOT NULL OR s.body_sha IS NOT NULL OR t.body_sha IS NOT NULL
  OR coalesce(r.bodies>=h.bodies,false) AS rejected
 FROM docs d JOIN described x ON x.body_sha=d.body_sha
 LEFT JOIN repeats r ON r.host=d.host AND r.folded=x.folded
 LEFT JOIN named n ON n.body_sha=x.body_sha AND n.folded=x.folded
 LEFT JOIN site_nodes s ON s.body_sha=x.body_sha AND s.node=x.node AND x.format='json-ld'
 LEFT JOIN templated t ON t.body_sha=x.body_sha AND t.path=x.path
 CROSS JOIN threshold h
), ranked AS (
 SELECT c.*,row_number() OVER(PARTITION BY c.doc_key ORDER BY coalesce(f.number,99),c.path) AS choice
 FROM candidates c LEFT JOIN page_signals f ON f.kind='description_format' AND regexp_like(c.format,f.pattern)
 WHERE NOT c.rejected
)
SELECT doc_key,trim(value) AS description,path FROM ranked WHERE choice=1
