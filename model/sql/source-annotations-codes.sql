WITH url_hosts AS (
 SELECT DISTINCT
  lower(regexp_replace((regexp_match(website_url,'(?i)^https?://(?:www[.])?([a-z0-9-]+(?:[.][a-z0-9-]+)+)/?$'))[1],'^(?:democrats-|republicans-)','')) AS host_key,
  substr(lower(system_code),1,4)||'00' AS parent_committee
 FROM spicy_committees
 WHERE parent_system_code IS NULL AND lower(system_code)<>'jjec00'
  AND regexp_like(coalesce(website_url,''),'(?i)^https?://(?:www[.])?[a-z0-9-]+(?:[.][a-z0-9-]+)+/?$')
 UNION SELECT 'aging.senate.gov' AS host_key,'spag00' AS parent_committee
 UNION SELECT 'ag.senate.gov','ssaf00'
 UNION SELECT 'agriculture.senate.gov','ssaf00'
 UNION SELECT 'appropriations.senate.gov','ssap00'
 UNION SELECT 'armed-services.senate.gov','ssas00'
 UNION SELECT 'banking.senate.gov','ssbk00'
 UNION SELECT 'budget.senate.gov','ssbu00'
 UNION SELECT 'commerce.senate.gov','sscm00'
 UNION SELECT 'drugcaucus.senate.gov','scnc00'
 UNION SELECT 'energy.senate.gov','sseg00'
 UNION SELECT 'epw.senate.gov','ssev00'
 UNION SELECT 'ethics.senate.gov','slet00'
 UNION SELECT 'finance.senate.gov','ssfi00'
 UNION SELECT 'foreign.senate.gov','ssfr00'
 UNION SELECT 'help.senate.gov','sshr00'
 UNION SELECT 'hsgac.senate.gov','ssga00'
 UNION SELECT 'indian.senate.gov','slia00'
 UNION SELECT 'intelligence.senate.gov','slin00'
 UNION SELECT 'judiciary.senate.gov','ssju00'
 UNION SELECT 'rules.senate.gov','ssra00'
 UNION SELECT 'sbc.senate.gov','sssb00'
 UNION SELECT 'veterans.senate.gov','ssva00'
 UNION SELECT 'jec.senate.gov','jsec00'
 UNION SELECT 'csce.gov','jcse00'
 UNION SELECT 'cecc.gov','jcpk00'
 UNION SELECT 'jct.gov','jstx00'
 UNION SELECT 'uscc.gov','jcuc00'
 UNION SELECT 'cha.house.gov','jslc00'
 UNION SELECT 'cha.house.gov','jspr00'
),
exported_hosts AS (
 SELECT DISTINCT uh.host_key,upper(sc.system_code) AS code
 FROM url_hosts uh
 JOIN spicy_committees sc ON sc.parent_system_code IS NULL AND lower(sc.system_code)=uh.parent_committee
)
SELECT source_id,unnest(committee_code) AS code FROM source_filename_readings WHERE committee_code_status='completed'
UNION
SELECT DISTINCT c.source_id,eh.code AS code
FROM exported_hosts eh
JOIN capture_source_contexts c
 ON eh.host_key=lower(regexp_replace(
  coalesce((regexp_match(coalesce(c.context_url,''),'(?i)^https?://(?:web[.]archive[.]org/web/[0-9a-z_*]+/https?://)?(?:www[.])?([^/?#:]+)'))[1],''),
  '^(?:democrats-|republicans-|democrats[.]|republicans[.])',''))
WHERE CASE
 WHEN eh.host_key='cha.house.gov' AND eh.code='JSLC00' THEN
  regexp_like(coalesce(c.context_url,''),'(?i)^https?://(?:web[.]archive[.]org/web/[0-9a-z_*]+/https?://)?(?:www[.])?cha[.]house[.]gov/(?:about/joint-committees/)?joint-committee-on-(?:the-)?library(?:[/?#]|$)')
 WHEN eh.host_key='cha.house.gov' AND eh.code='JSPR00' THEN
  regexp_like(coalesce(c.context_url,''),'(?i)^https?://(?:web[.]archive[.]org/web/[0-9a-z_*]+/https?://)?(?:www[.])?cha[.]house[.]gov/(?:about/joint-committees/)?joint-committee-on-printing(?:[/?#]|$)')
 WHEN eh.host_key='cha.house.gov' AND eh.code='HSHA00' THEN
  NOT regexp_like(coalesce(c.context_url,''),'(?i)^https?://(?:web[.]archive[.]org/web/[0-9a-z_*]+/https?://)?(?:www[.])?cha[.]house[.]gov/(?:about/joint-committees/)?joint-committee-on-(?:(?:the-)?library|printing)(?:[/?#]|$)')
 ELSE true
END
