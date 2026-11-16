-- Separate host_committee_keys (e.g. hsru00 docs.house.gov/billsthisweek & rules.house.gov floor hosting)
-- from authoring/proceeding committee_keys, and guard against -Bio- 180-char career-prose lookbacks and
-- uncorroborated embargo header/footer banners.
WITH mapped AS (
 SELECT DISTINCT f.source_id,c.system_code,c.chamber
 FROM committee_codes c JOIN source_annotation_codes f ON f.code=c.code
),
qualified AS (
 SELECT m.source_id,m.system_code,m.chamber,
  regexp_like(coalesce(s.filename,''),'(?i)^(?:HHRG|HMTG|HMKP|CRPT)-[0-9]{3}-[A-Z]{2}[0-9]{2}-') AS has_clerk_slug,
  regexp_like(coalesce(s.filename,''),'(?i)(?:^|[-_. ])bio(?:graphy)?(?:$|[-_. ])')
   OR regexp_like(coalesce(p.text_head,''),'(?i)^\s*(?:page\s+[0-9]+(?:\s+of\s+[0-9]+)?\s+)?(?:biography|biographical\s+sketch|curriculum\s+vitae|r[eé]sum[eé])\s+(?:of|for)\b') AS is_bio_source,
  p.text_head IS NOT NULL AND regexp_like(
   p.text_head,
   '(?is)(?:\b(?:counsel|staff|advisor|adviser|fellow|intern|director|clerk|assistant|liaison|member)\s+(?:to|on|of|for|with)|\b(?:worked|served|testified|appeared|prior\s+to\s+joining|before\s+joining|formerly\s+with)).{0,180}?\bcommittee\s+on\b'
  ) AS has_career_prose_180,
  p.text_head IS NOT NULL
   AND regexp_like(p.text_head,'(?is)(?:^\s*(?:strictly\s+)?embargoed\s+(?:until|for\s+release)\b|\bembargoed\s+until\s+(?:delivery|[0-9]{1,2}:[0-9]{2})|^\s*hold\s+for\s+release\b|\bfor\s+release\s+on\s+delivery\b)')
   AND NOT regexp_like(p.text_head,'(?im)^\s*(?:one\s+hundred\s+[a-z-]+\s+congress\s+)?(?:u[.]?s[.]?\s+house\s+of\s+representatives|united\s+states\s+senate)\s+committee\s+on\b') AS has_embargo_exclusion,
  starts_with(m.system_code,'hsru')
   AND NOT regexp_like(coalesce(s.filename,''),'(?i)^(?:HHRG|HMTG|HMKP|CRPT)-[0-9]{3}-RU[0-9]{2}-')
   AND NOT regexp_like(coalesce(s.source_url,''),'(?i)/meetings/RU/')
   AND NOT (
    p.text_head IS NOT NULL
    AND NOT regexp_like(p.text_head,'(?i)(?:\bRULES\s+COMMITTEE\s+PRINT\s+1[0-9]{2}\s*[-–—]\s*[0-9]+\b|^\s*(?:Report\s+Generated:.{0,80}?\s+)?(?:Comparative\s+Print:|Comparing\s+the\s+base\s+document\b))')
    AND regexp_like(p.text_head,'(?i)(?:^\s*(?:Page\s+[0-9]+\s+of\s+[0-9]+\s+|[0-9]+\s+)?MOTION\s+BY\b|\bProviding\s+for\s+consideration\s+of\s+the\s+(?:bill|joint\s+resolution|resolution|senate\s+amendment)\b|\bFROM\s+THE\s+COMMITTEE\s+ON\s+RULES\b|\bRULES\s+OF\s+THE\s+COMMITTEE\s+ON\s+RULES\b)')
   )
   AND (
    regexp_like(coalesce(s.source_url,''),'(?i)^https?://(?:web[.]archive[.]org/web/[0-9a-z_*]+/https?://)?(?:docs[.]house[.]gov/(?:billsthisweek|floor)(?:/|$)|(?:[a-z0-9-]+[.])?rules[.]house[.]gov/)')
    OR regexp_like(coalesce(s.filename,''),'(?i)^(?:bills|cp)-\s*[0-9]+.*-rcp\s*[0-9]|^bill-to-bill_')
    OR regexp_like(coalesce(p.text_head,''),'(?i)(?:\bRULES\s+COMMITTEE\s+PRINT\s+1[0-9]{2}\s*[-–—]\s*[0-9]+\b|^\s*(?:Report\s+Generated:.{0,80}?\s+)?(?:Comparative\s+Print:|Comparing\s+the\s+base\s+document\b))')
   ) AS is_hsru_floor_host
 FROM mapped m
 JOIN source_files s ON s.source_id=m.source_id
 LEFT JOIN page_facts p ON s.body_sha=lower(encode(p.body_sha,'hex'))
),
classified AS (
 SELECT source_id,system_code,chamber,
  is_hsru_floor_host OR (NOT has_clerk_slug AND (is_bio_source OR has_career_prose_180 OR has_embargo_exclusion)) AS excluded_from_committee,
  is_hsru_floor_host OR is_bio_source OR has_career_prose_180 OR has_embargo_exclusion AS host_only
 FROM qualified
)
SELECT source_id,
 array_sort(array_distinct(array_agg(system_code))) AS host_committee_keys,
 coalesce(
  array_sort(array_distinct(array_agg(system_code) FILTER (WHERE NOT host_only))),
  arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')
 ) AS authoring_committee_keys,
 coalesce(
  array_sort(array_distinct(array_agg(system_code) FILTER (WHERE NOT excluded_from_committee))),
  arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')
 ) AS committee_keys,
 coalesce(
  array_sort(array_distinct(array_agg(chamber) FILTER (WHERE NOT excluded_from_committee))),
  arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')
 ) AS chambers
FROM classified GROUP BY source_id
