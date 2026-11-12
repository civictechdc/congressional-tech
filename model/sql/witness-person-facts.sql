-- Normalized person-grouping facts for witness rows (ct-ha10).
-- Classifies each resolved appearance row into Tier 1 Member Bioguide (publisher Bioguide present in
-- spicy_members, or ct-kw85 matched_bioguide_id), Tier 2 non-Member candidate (normalized name_key,
-- middle_norm, suffix_norm, and full normalized org_key), superseded row (inheriting its canonical
-- witness's person_key in witness_people), or non-person row (record entries, unnamed rows, and
-- unmatched member_appearance rows).
WITH known_members AS (
 SELECT DISTINCT bioguide_id FROM spicy_members WHERE bioguide_id IS NOT NULL
), pkg_raw_dates AS (
 SELECT
  pmf.package_id,
  try_cast((regexp_match(pmf.package_id,'^CHRG-([0-9]{1,3})'))[1] AS INT) AS pkg_congress,
  unnest(pmf.held_dates) AS hd_str
 FROM package_mods_facts pmf
 WHERE pmf.held_dates IS NOT NULL AND cardinality(pmf.held_dates)>0
), pkg_dates AS (
 SELECT
  package_id,
  coalesce(
   min(CASE
    WHEN pkg_congress IS NOT NULL
     AND extract(year FROM try_cast(hd_str AS DATE)) BETWEEN 1789+(pkg_congress-1)*2-2 AND 1789+pkg_congress*2+2
    THEN try_cast(hd_str AS DATE)
   END),
   min(try_cast(hd_str AS DATE))
  ) AS pkg_hearing_date
 FROM pkg_raw_dates
 WHERE try_cast(hd_str AS DATE) IS NOT NULL
 GROUP BY package_id
), joined AS (
 SELECT
  r.witness_key,
  r.occasion,
  r.source,
  r.name,
  r.rank,
  r.credentials,
  r.organization,
  r.position,
  p.superseded_by,
  coalesce(mr.meeting_date,pd.pkg_hearing_date) AS hearing_date,
  coalesce(ms.priority,99) AS source_priority,
  CASE
   WHEN wm.outcome='member' AND tf.statement_only THEN 'member_statement'
   WHEN wm.outcome='member' THEN 'member_appearance'
   WHEN wm.outcome='statement' THEN 'member_statement'
   WHEN tf.promote THEN NULL
   ELSE r.witness_type
  END AS eff_witness_type,
  coalesce(wm.matched_bioguide_id,CASE WHEN km.bioguide_id IS NOT NULL THEN r.bioguide_id END) AS member_bioguide_id
 FROM meeting_sources ms
 RIGHT JOIN (
  pkg_dates pd
  RIGHT JOIN (
   meetings_resolved mr
   RIGHT JOIN (
    known_members km
    RIGHT JOIN (
     witness_transcript_facts tf
     RIGHT JOIN (
      witness_members wm
      RIGHT JOIN (
       witness_precedence p
       RIGHT JOIN appearance_records_resolved r ON p.witness_key=r.witness_key
      ) ON wm.witness_key=r.witness_key
     ) ON tf.witness_key=r.witness_key
    ) ON km.bioguide_id=r.bioguide_id
   ) ON mr.event_id=r.event_id
  ) ON pd.package_id=r.package_id
 ) ON ms.source=r.source AND ms.kind='appearance'
), folded AS (
 SELECT
  j.*,
  translate(
   regexp_replace(
    replace(replace(replace(replace(replace(replace(lower(coalesce(j.name,'')),'ß','ss'),'ﬀ','ff'),'ﬁ','fi'),'ﬂ','fl'),'ﬃ','ffi'),'ﬄ','ffl'),
    '\p{Mn}','','g'
   ),
   'áàâäãåāăąçćčďéèêëēėęěğíìîïīįñńņňóòôöõōőřśšşťúùûüūůűýÿźżž',
   'aaaaaaaaacccdeeeeeeeegiiiiiinnnnooooooorssstuuuuuuuyyzzz'
  ) AS name_f,
  translate(
   replace(replace(replace(replace(replace(replace(lower(coalesce(j.organization,'')),'ß','ss'),'ﬀ','ff'),'ﬁ','fi'),'ﬂ','fl'),'ﬃ','ffi'),'ﬄ','ffl'),
   '⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉',
   '01234567890123456789'
  ) AS org_f
 FROM joined j
), noparen AS (
 SELECT f.*,regexp_replace(f.name_f,'\([^)]*\)',' ','g') AS s
 FROM folded f
), comma AS (
 SELECT n.*,
  strpos(n.s,',') AS cpos,
  CASE WHEN strpos(n.s,',')>0 THEN substr(n.s,1,strpos(n.s,',')-1) ELSE n.s END AS before_c,
  CASE WHEN strpos(n.s,',')>0 THEN substr(n.s,strpos(n.s,',')+1) ELSE '' END AS after_c
 FROM noparen n
), comma_clean AS (
 SELECT c.*,
  regexp_replace(regexp_replace(translate(c.before_c,chr(39)||'’',''),'[^\p{L}\p{N}]+',' ','g'),'\s+',' ','g') AS b_clean,
  regexp_replace(regexp_replace(translate(replace(c.after_c,'.',''),chr(39)||'’',''),'[^\p{L}\p{N}]+',' ','g'),'\s+',' ','g') AS a_clean
 FROM comma c
), comma_toks AS (
 SELECT cc.*,
  CASE WHEN trim(cc.b_clean)='' THEN arrow_cast(make_array(),'List(Utf8)') ELSE string_to_array(trim(cc.b_clean),' ') END AS b_toks,
  CASE WHEN trim(cc.a_clean)='' THEN arrow_cast(make_array(),'List(Utf8)') ELSE string_to_array(trim(cc.a_clean),' ') END AS a_toks
 FROM comma_clean cc
), reordered AS (
 SELECT ct.*,
  CASE
   WHEN ct.cpos=0 THEN ct.s
   WHEN cardinality(ct.a_toks) BETWEEN 1 AND 3
    AND ct.a_toks[1] NOT IN (
     'jr','sr','ii','iii','iv','mr','mrs','ms','miss','mx','dr','hon','honorable','the','rev','reverend',
     'sen','senator','rep','representative','gen','general','lt','lieutenant','col','colonel','maj','major',
     'adm','admiral','vadm','radm','ltg','mg','bg','vice','rear','capt','captain','sgt','sergeant','brigadier',
     'chief','ambassador','secretary','judge','governor','mayor','professor','prof','commissioner','chairman',
     'chairwoman','chair','ranking','member','congressman','congresswoman','delegate','phd','md','mph','jd',
     'rn','mba','dvm','esq','cpa','edd','dds','mpa','mpp','msw','ret','usa','usn','usaf','usmc','uscg','ussf'
    )
    AND (
     cardinality(ct.b_toks)=1
     OR (cardinality(ct.b_toks)=2 AND ct.b_toks[1] IN ('van','von','de','del','della','la','le','di','da','du','st','mac','mc','dos','das'))
    )
   THEN ct.after_c||' '||ct.before_c
   ELSE ct.before_c||' '||regexp_replace(
    regexp_replace(trim(ct.a_clean),'\b(jr|sr|ii|iii|iv)\b','_$1','g'),
    '\b[^\s_]+\b',' ','g'
   )
  END AS s2
 FROM comma_toks ct
), cleaned AS (
 SELECT r.*,
  trim(regexp_replace(
   regexp_replace(
    trim(regexp_replace(regexp_replace(translate(replace(r.s2,'_',''),chr(39)||'’',''),'[^\p{L}\p{N}]+',' ','g'),'\s+',' ','g')),
    '\b(?:mr|mrs|ms|miss|mx|dr|hon|honorable|the|rev|sen|rep|gen|lt|col|maj|adm|vadm|radm|ltg|mg|bg|capt|sgt|prof|phd|md|mph|jd|rn|mba|dvm|esq|cpa|edd|dds|mpa|mpp|msw|ret|retired|usa|usn|usaf|usmc|uscg|ussf|\d+)\b',
    ' ','g'
   ),
   '\s+',' ','g'
  )) AS s_no_hon,
  regexp_replace(
   trim(regexp_replace(regexp_replace(translate(r.org_f,chr(39)||'’',''),'[^\p{L}\p{N}]+',' ','g'),'\s+',' ','g')),
   '^the ',''
  ) AS org_key
 FROM reordered r
), split_suf AS (
 SELECT c.*,
  trim(regexp_replace(
   regexp_replace(
    trim(regexp_replace(regexp_replace(c.s_no_hon,'\b(?:jr|sr|ii|iii|iv)\b',' ','g'),'\s+',' ','g')),
    '\b(?:reverend|senator|representative|general|lieutenant|colonel|major|admiral|vice|rear|captain|sergeant|brigadier|chief|ambassador|secretary|judge|justice|governor|mayor|professor|commissioner|chairman|chairwoman|chair|ranking|member|congressman|congresswoman|delegate)\s+',
    ' ','g'
   ),
   '\s+',' ','g'
  )) AS s_core,
  replace(trim(regexp_replace(
   regexp_replace(regexp_replace(c.s_no_hon,'\b(jr|sr|ii|iii|iv)\b','_$1','g'),'\b[^\s_]+\b',' ','g'),
   '\s+',' ','g'
  )),'_','') AS s_suf
 FROM cleaned c
), tok_arrays AS (
 SELECT ss.*,
  CASE WHEN ss.s_core='' THEN arrow_cast(make_array(),'List(Utf8)') ELSE string_to_array(ss.s_core,' ') END AS t,
  CASE WHEN ss.s_suf='' THEN '' ELSE array_to_string(array_sort(string_to_array(ss.s_suf,' ')),'') END AS suf
 FROM split_suf ss
), parts AS (
 SELECT ta.*,cast(cardinality(ta.t) AS BIGINT) AS n
 FROM tok_arrays ta
), with_k AS (
 SELECT p.*,
  CASE
   WHEN p.n<2 THEN ''
   ELSE trim(p.t[1]||' '||trim(regexp_replace(
    regexp_replace(array_to_string(array_slice(p.t,2,p.n),' '),'\b\S\b',' ','g'),
    '\s+',' ','g'
   )))
  END AS k
 FROM parts p
)
SELECT
 witness_key,
 occasion,
 source,
 name,
 rank,
 credentials,
 organization,
 position,
 superseded_by,
 hearing_date,
 source_priority,
 eff_witness_type,
 member_bioguide_id,
 org_key,
 CASE WHEN n>=2 AND strpos(k,' ')>0 THEN k END AS name_key,
 CASE
  WHEN n<3 THEN ''
  ELSE regexp_replace(regexp_replace(array_to_string(array_slice(t,2,n-1),' '),'\b\S{2,}\b',' ','g'),'\s+','','g')
 END AS middle_norm,
 CASE WHEN n<2 THEN '' ELSE suf END AS suffix_norm
FROM with_k
