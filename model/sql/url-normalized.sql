-- Inputs: url_inputs(input_id,url), url_rules, active url_variants(canonical_url,variant_url).
-- Literal values remain unchanged. Every error makes the join key unusable.
WITH literals AS (
 SELECT DISTINCT url FROM url_inputs
 UNION SELECT canonical_url FROM url_variants
 UNION SELECT variant_url FROM url_variants
), first_matches AS (
 SELECT l.url,count(r.id) AS matches,
 max(CASE r.decoder WHEN 'proofpoint' THEN
   percent_decode_utf8(replace(regexp_replace(regexp_replace(l.url,r.pattern,r.replacement),'-([0-9A-Fa-f]{2})','%$1','g'),'_','/'))
 WHEN 'percent' THEN percent_decode_utf8(regexp_replace(l.url,r.pattern,r.replacement))
 ELSE regexp_replace(l.url,r.pattern,r.replacement) END) AS inner_url
 FROM literals l LEFT JOIN url_rules r ON r.kind='wrapper' AND regexp_like(l.url,r.pattern)
 GROUP BY l.url
), first_pass AS (
 SELECT url,coalesce(inner_url,url) AS value,matches>1 AS conflict FROM first_matches
), second_matches AS (
 SELECT p.url,p.conflict,count(r.id) AS matches,
 max(CASE r.decoder WHEN 'proofpoint' THEN
   percent_decode_utf8(replace(regexp_replace(regexp_replace(p.value,r.pattern,r.replacement),'-([0-9A-Fa-f]{2})','%$1','g'),'_','/'))
 WHEN 'percent' THEN percent_decode_utf8(regexp_replace(p.value,r.pattern,r.replacement))
 ELSE regexp_replace(p.value,r.pattern,r.replacement) END) AS inner_url,max(p.value) AS prior
 FROM first_pass p LEFT JOIN url_rules r ON r.kind='wrapper' AND regexp_like(p.value,r.pattern)
 GROUP BY p.url,p.conflict
), unwrapped AS (
 SELECT url,coalesce(inner_url,prior) AS value,conflict OR matches>1 AS conflict FROM second_matches
), serialized AS (
 SELECT u.url,u.value,u.conflict,uri_normalize_encoding(url_resolve(u.value,cast(NULL AS VARCHAR))) AS parsed,
 count(r.id)>0 AS still_wrapped FROM unwrapped u
 LEFT JOIN url_rules r ON r.kind='wrapper' AND regexp_like(u.value,r.pattern)
 GROUP BY u.url,u.value,u.conflict
), components AS (
 SELECT *,regexp_replace((regexp_match(parsed,'^https?://([^/?#]+)'))[1],'^www\.','') AS authority,
 coalesce((regexp_match(parsed,'^https?://[^/?#]+([^?#]*)'))[1],'') AS path,
 (regexp_match(split_part(parsed,'#',1),'\?(.*)$'))[1] AS query FROM serialized
), pairs AS (
 SELECT url,authority,unnest(string_to_array(query,'&')) AS pair FROM components WHERE query<>''
), kept_pairs AS (
 SELECT p.* FROM pairs p WHERE NOT EXISTS (
 SELECT 1 FROM url_rules r WHERE r.kind='strip'
 AND (r.host_pattern IS NULL OR regexp_like(regexp_replace(p.authority,':[0-9]+$',''),r.host_pattern))
 AND regexp_like(split_part(p.pair,'=',1),r.pattern))
), queries AS (
 SELECT url,string_agg(pair,'&' ORDER BY pair) AS query FROM kept_pairs GROUP BY url
), base_keys AS (
 SELECT c.url,
 CASE WHEN c.conflict THEN 'wrapper_conflict'
 WHEN c.authority IS NULL THEN 'invalid_url' END AS error,c.still_wrapped,
 c.authority || regexp_replace(c.path,'/$','') ||
 coalesce('?' || q.query,'') AS base_key
 FROM components c LEFT JOIN queries q ON c.url=q.url
 )
SELECT * FROM base_keys
