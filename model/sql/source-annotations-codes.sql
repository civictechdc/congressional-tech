WITH senate_hosts AS (
 SELECT DISTINCT
  lower((regexp_match(website_url,'(?i)^https?://(?:www[.])?([a-z0-9-]+)[.]senate[.]gov'))[1]) AS host,
  substr(lower(system_code),1,4)||'00' AS parent_committee
 FROM spicy_committees
 WHERE parent_system_code IS NULL AND lower(system_code)<>'jjec00'
  AND regexp_like(coalesce(website_url,''),'(?i)^https?://(?:www[.])?[a-z0-9-]+[.]senate[.]gov')
 UNION
 SELECT 'aging' AS host,'spag00' AS parent_committee
 UNION SELECT 'ag','ssaf00'
 UNION SELECT 'agriculture','ssaf00'
 UNION SELECT 'appropriations','ssap00'
 UNION SELECT 'armed-services','ssas00'
 UNION SELECT 'banking','ssbk00'
 UNION SELECT 'budget','ssbu00'
 UNION SELECT 'commerce','sscm00'
 UNION SELECT 'drugcaucus','scnc00'
 UNION SELECT 'energy','sseg00'
 UNION SELECT 'epw','ssev00'
 UNION SELECT 'ethics','slet00'
 UNION SELECT 'finance','ssfi00'
 UNION SELECT 'foreign','ssfr00'
 UNION SELECT 'help','sshr00'
 UNION SELECT 'hsgac','ssga00'
 UNION SELECT 'indian','slia00'
 UNION SELECT 'intelligence','slin00'
 UNION SELECT 'judiciary','ssju00'
 UNION SELECT 'rules','ssra00'
 UNION SELECT 'sbc','sssb00'
 UNION SELECT 'veterans','ssva00'
 UNION SELECT 'jec','jsec00'
)
SELECT source_id,unnest(committee_code) AS code FROM source_filename_readings WHERE status='completed'
UNION
SELECT DISTINCT c.source_id,upper(sc.system_code) AS code
FROM capture_source_contexts c
JOIN senate_hosts sh ON sh.host=lower((regexp_match(coalesce(c.context_url,''),'(?i)^https?://(?:www[.])?([a-z0-9-]+)[.]senate[.]gov'))[1])
JOIN spicy_committees sc ON sc.parent_system_code IS NULL AND lower(sc.system_code)=sh.parent_committee
