WITH url_hosts AS (
 SELECT DISTINCT
  lower(regexp_replace((regexp_match(website_url,'(?i)^https?://(?:www[.])?([a-z0-9-]+[.][a-z]+[.][a-z]+)'))[1],'^(?:democrats-|republicans-)','')) AS host_key,
  upper(substr(lower(system_code),1,4)||'00') AS code
 FROM spicy_committees
 WHERE parent_system_code IS NULL AND lower(system_code)<>'jjec00'
  AND regexp_like(coalesce(website_url,''),'(?i)^https?://(?:www[.])?[a-z0-9-]+[.][a-z]+[.][a-z]+')
 UNION SELECT 'aging.senate.gov' AS host_key,'SPAG00' AS code
 UNION SELECT 'ag.senate.gov','SSAF00'
 UNION SELECT 'agriculture.senate.gov','SSAF00'
 UNION SELECT 'appropriations.senate.gov','SSAP00'
 UNION SELECT 'armed-services.senate.gov','SSAS00'
 UNION SELECT 'banking.senate.gov','SSBK00'
 UNION SELECT 'budget.senate.gov','SSBU00'
 UNION SELECT 'commerce.senate.gov','SSCM00'
 UNION SELECT 'drugcaucus.senate.gov','SCNC00'
 UNION SELECT 'energy.senate.gov','SSEG00'
 UNION SELECT 'epw.senate.gov','SSEV00'
 UNION SELECT 'ethics.senate.gov','SLET00'
 UNION SELECT 'finance.senate.gov','SSFI00'
 UNION SELECT 'foreign.senate.gov','SSFR00'
 UNION SELECT 'help.senate.gov','SSHR00'
 UNION SELECT 'hsgac.senate.gov','SSGA00'
 UNION SELECT 'indian.senate.gov','SLIA00'
 UNION SELECT 'intelligence.senate.gov','SLIN00'
 UNION SELECT 'judiciary.senate.gov','SSJU00'
 UNION SELECT 'rules.senate.gov','SSRA00'
 UNION SELECT 'sbc.senate.gov','SSSB00'
 UNION SELECT 'veterans.senate.gov','SSVA00'
 UNION SELECT 'jec.senate.gov','JSEC00'
 UNION SELECT 'climatecrisis.house.gov','HLCN00'
 UNION SELECT 'coronavirus.house.gov','HLVC00'
 UNION SELECT 'modernizecongress.house.gov','HLMH00'
 UNION SELECT 'january6th.house.gov','HLIJ00'
 UNION SELECT 'selectcommitteeontheccp.house.gov','HLZS00'
 UNION SELECT 'chinaselectcommittee.house.gov','HLZS00'
 UNION SELECT 'intelligence.house.gov','HLIG00'
 UNION SELECT 'fairness.house.gov','HLEF00'
 UNION SELECT 'globalwarming.house.gov','HLGW00'
 UNION SELECT 'benghazi.house.gov','HLZI00'
 UNION SELECT 'rules.house.gov','HSRU00'
 UNION SELECT 'docs.house.gov/floor','HSRU00'
 UNION SELECT 'csce.gov','JCSE00'
 UNION SELECT 'cecc.gov','JCPK00'
 UNION SELECT 'jct.gov','JSTX00'
)
SELECT source_id,unnest(committee_code) AS code FROM source_filename_readings WHERE committee_code_status='completed'
UNION
SELECT DISTINCT c.source_id,uh.code AS code
FROM url_hosts uh
JOIN capture_source_contexts c
 ON uh.host_key=CASE
  WHEN regexp_like(coalesce(c.context_url,''),'(?i)^https?://(?:web[.]archive[.]org/web/[0-9a-z_*]+/https?://)?docs[.]house[.]gov/(?:billsthisweek|floor)(?:/|$)')
   THEN 'docs.house.gov/floor'
  ELSE lower(regexp_replace(
   coalesce((regexp_match(coalesce(c.context_url,''),'(?i)^https?://(?:web[.]archive[.]org/web/[0-9a-z_*]+/https?://)?(?:www[.])?([^/?#:]+)'))[1],''),
   '^(?:democrats-|republicans-|democrats[.]|republicans[.])',''))
 END
