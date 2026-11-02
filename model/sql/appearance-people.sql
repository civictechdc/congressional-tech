-- One person key per stated appearance: family name and given name from the stated name, so two rows can be
-- judged the same person. Shared by print-to-meeting agreement and per-person witness precedence.
-- Built from the name, not name_key: a parenthetical ("(TX-27)") and everything after the first comma
-- (", M.D., M.P.H.", ", Jr.") are dropped, so credentials and districts never become keys (red-f3: Walke and
-- Marston both keyed "mph"). Honorifics, ranks, suffixes and credentials are dropped as words. A surname
-- particle belongs to the family name only before it ("Carlos Del Toro" -> del toro, carlos); a two-word
-- "Van Jackson" has no given name and the family "van jackson". Nicknames map one way to the formal name
-- (Bob -> Robert, never Barbara -> Robert).
WITH rows AS (
 SELECT r.record_sha_hex,r.source,r.event_id,nullif(trim(r.package_id),'') AS print_id,
  unnest(r.appearances) AS a,unnest(range(0,cast(array_length(r.appearances) AS BIGINT))) AS ordinal
 FROM selected_appearance_records r
 WHERE r.status='completed' AND r.appearances IS NOT NULL AND coalesce(array_length(r.appearances),0)>0
), words AS (
 SELECT record_sha_hex,source,event_id,print_id,ordinal,a['witness_type'] AS witness_type,
  array_except(string_to_array(trim(regexp_replace(regexp_replace(split_part(regexp_replace(
    lower(coalesce(a['name'],a['name_key'],'')),'\([^)]*\)',' ','g'),',',1),'[^a-z \-]+','','g'),'[ \-]+',' ','g')),' '),
   make_array('','mr','mrs','ms','miss','mx','dr','hon','honorable','the','rev','reverend','sen','senator','rep','representative',
    'gen','general','lt','lieutenant','col','colonel','maj','major','adm','admiral','vadm','radm','ltg','mg','bg','vice','rear',
    'capt','captain','sgt','sergeant','brigadier','chief','ambassador','secretary','judge','governor','mayor','professor','prof',
    'commissioner','chairman','chairwoman','chair','ranking','member','congressman','congresswoman','delegate',
    'jr','sr','ii','iii','iv','phd','md','mph','jd','rn','mba','dvm','esq','cpa','edd','dds','mpa','mpp','msw','ret',
    'usa','usn','usaf','usmc','uscg','ussf')) AS t
 FROM rows
), keyed AS (
 SELECT *,cast(cardinality(t) AS BIGINT) AS n FROM words
), parted AS (
 SELECT *,n>=2 AND t[n-1] IN ('del','de','della','van','von','la','le','di','da','du','st','mac','mc','dos','das') AS particle FROM keyed
), named AS (
 SELECT record_sha_hex,source,event_id,print_id,ordinal,witness_type,
  CASE WHEN n=0 THEN NULL WHEN particle THEN concat(t[n-1],' ',t[n]) ELSE t[n] END AS family,
  CASE WHEN particle AND n>=3 THEN t[1] WHEN NOT particle AND n>=2 THEN t[1] END AS given
 FROM parted
)
SELECT record_sha_hex,source,event_id,print_id AS package_id,ordinal,
 coalesce(witness_type IN ('statement_for_record','member_statement'),false) AS statement,
 family,given,
 CASE given
  WHEN 'bob' THEN 'robert' WHEN 'bobby' THEN 'robert' WHEN 'rob' THEN 'robert' WHEN 'bill' THEN 'william' WHEN 'billy' THEN 'william'
  WHEN 'will' THEN 'william' WHEN 'dick' THEN 'richard' WHEN 'rick' THEN 'richard' WHEN 'rich' THEN 'richard'
  WHEN 'ted' THEN 'edward' WHEN 'ned' THEN 'edward' WHEN 'ed' THEN 'edward' WHEN 'eddie' THEN 'edward'
  WHEN 'liz' THEN 'elizabeth' WHEN 'beth' THEN 'elizabeth' WHEN 'betsy' THEN 'elizabeth' WHEN 'betty' THEN 'elizabeth' WHEN 'libby' THEN 'elizabeth'
  WHEN 'peggy' THEN 'margaret' WHEN 'maggie' THEN 'margaret' WHEN 'meg' THEN 'margaret'
  WHEN 'jim' THEN 'james' WHEN 'jimmy' THEN 'james' WHEN 'mike' THEN 'michael' WHEN 'tom' THEN 'thomas' WHEN 'tommy' THEN 'thomas'
  WHEN 'chuck' THEN 'charles' WHEN 'jack' THEN 'john' WHEN 'hank' THEN 'henry' WHEN 'joe' THEN 'joseph' WHEN 'tony' THEN 'anthony'
  WHEN 'larry' THEN 'lawrence' WHEN 'harry' THEN 'harold' WHEN 'jerry' THEN 'gerald' WHEN 'sandy' THEN 'sandra' WHEN 'kathy' THEN 'katherine'
  ELSE given END AS given_canon
FROM named
