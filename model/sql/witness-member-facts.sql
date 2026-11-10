-- ct-kw85: what witness_members weighs, read once. One row per named witness row that is not a record entry
-- (part 'name'), and per Member two rows: the family name (part 'family', from name_last) and the first names (part
-- 'given': name_first, a nickname it holds in parentheses, and the members data's own name_nickname). Every name is
-- read by the same rule: accents folded, a parenthetical and everything after the first comma dropped ('Bill
-- Cassidy, M.D.'), honorifics, ranks and suffixes dropped as words, trailing initials dropped ('M.D.'), repeats kept
-- once. A Member's first name written as an abbreviation ('Wm.') is marked so it can be read in order.
-- A witness row also carries its hearing dates (the meeting's date, else the print's heldDates), its title and what
-- its own words say: former or a closed span of years, a state legislature, a House or Senate officer or staffer,
-- the person's own nomination ('to be ...', 'Nominee for', or a nomination hearing whose title names both of their
-- names), the chamber ('U.S. Senator', 'Representative in Congress', '(NM-01)', 'Rep.' alone, 'Member of
-- Congress'), and a committee role. 'Representative of' or 'for' an organization is not the House.
-- Its own step: the candidate, mention and decision steps read these rows several times.
WITH fold(accented,plain) AS (
 -- The one accent table the Member appearance steps fold names and words with.
 VALUES ('áàâäãåāăąéèêëēėęěíìîïīįóòôöõøōőúùûüūůűñńçćčýÿšśžźżłđ','aaaaaaaaaeeeeeeeeiiiiiioooooooouuuuuuunncccyysszzzld')
), witness_rows AS (
 SELECT r.witness_key,coalesce(p.superseded_by,r.witness_key) AS person,r.bioguide_id AS publisher_id,r.name,
  concat_ws(' | ',r.position,r.organization,r.on_behalf_of,r.location) AS fields,
  concat_ws(chr(10),r.name,r.position,r.organization,r.on_behalf_of,r.location) AS name_lines,
  concat_ws(chr(10),r.position,r.organization,r.on_behalf_of,r.location) AS field_lines,
  CASE WHEN m.meeting_date IS NOT NULL THEN make_array(cast(m.meeting_date AS VARCHAR)) ELSE f.held_dates END AS dates,
  coalesce(m.title,f.title) AS title
 FROM package_mods_facts f RIGHT JOIN (meetings_resolved m RIGHT JOIN (witness_precedence p RIGHT JOIN appearance_records_resolved r
  ON p.witness_key=r.witness_key) ON m.event_id=r.event_id) ON f.package_id=r.package_id
 WHERE r.name IS NOT NULL AND coalesce(r.witness_type,'') NOT IN ('statement_for_record','member_statement','record_material')
), named AS (
 SELECT 'witness' AS side,'name' AS part,witness_key AS id,person,publisher_id,name AS raw,fields,name_lines,field_lines,dates,title,
  false AS abbreviated
 FROM witness_rows
 UNION ALL
 SELECT 'member' AS side,'family' AS part,bioguide_id AS id,cast(NULL AS VARCHAR) AS person,cast(NULL AS VARCHAR) AS publisher_id,
  name_last AS raw,cast(NULL AS VARCHAR) AS fields,cast(NULL AS VARCHAR) AS name_lines,cast(NULL AS VARCHAR) AS field_lines,
  arrow_cast(NULL,'List(Utf8)') AS dates,cast(NULL AS VARCHAR) AS title,false AS abbreviated
 FROM spicy_members WHERE bioguide_id IS NOT NULL
 UNION ALL
 SELECT 'member' AS side,'given' AS part,bioguide_id AS id,cast(NULL AS VARCHAR) AS person,cast(NULL AS VARCHAR) AS publisher_id,
  regexp_replace(coalesce(name_first,''),'[()]',' ','g')||' '||coalesce(name_nickname,'') AS raw,cast(NULL AS VARCHAR) AS fields,
  cast(NULL AS VARCHAR) AS name_lines,cast(NULL AS VARCHAR) AS field_lines,arrow_cast(NULL,'List(Utf8)') AS dates,
  cast(NULL AS VARCHAR) AS title,coalesce(regexp_like(name_first,'^\s*[A-Za-z]{2,4}\.\s*$'),false) AS abbreviated
 FROM spicy_members WHERE bioguide_id IS NOT NULL
), folded AS (
 SELECT n.*,translate(lower(n.raw),f.accented,f.plain) AS raw_folded,
  translate(lower(n.raw||' | '||n.fields),f.accented,f.plain) AS full_text,
  translate(lower(n.fields),f.accented,f.plain) AS field_text,
  translate(lower(n.name_lines),f.accented,f.plain) AS name_lines_folded,
  translate(lower(n.field_lines),f.accented,f.plain) AS field_lines_folded,
  ' '||regexp_replace(translate(lower(n.title),f.accented,f.plain),'[^a-z]+',' ','g')||' ' AS title_words
 FROM named n CROSS JOIN fold f
), tokened AS (
 SELECT *,array_except(string_to_array(regexp_replace(trim(regexp_replace(translate(regexp_replace(regexp_replace(
   split_part(regexp_replace(raw_folded,'\([^)]*\)',' ','g'),',',1),'[''’`]','','g'),'[^a-z .\-]+',' ','g'),'.-','  '),
   '(\s+[a-z]){2,}\s*$','')),'\s+',' ','g'),' '),
  make_array('','mr','mrs','ms','miss','mx','dr','hon','honorable','the','rev','reverend','sen','senator','rep','representative','gen','general','lt','lieutenant','col','colonel','maj','major','adm','admiral','vadm','radm','ltg','mg','bg','vice','rear','capt','captain','sgt','sergeant','brigadier','chief','ambassador','secretary','judge','governor','mayor','professor','prof','commissioner','chairman','chairwoman','chair','ranking','member','congressman','congresswoman','delegate','jr','sr','ii','iii','iv','phd','md','mph','jd','rn','mba','dvm','esq','cpa','edd','dds','mpa','mpp','msw','ret','usa','usn','usaf','usmc','uscg','ussf')) AS toks
 FROM folded
)
SELECT side,part,id,person,publisher_id,toks,abbreviated,
 CASE WHEN part='name' AND cardinality(toks)>=2 THEN toks[cast(cardinality(toks) AS BIGINT)] END AS family,
 CASE WHEN part='name' AND cardinality(toks)>=2 THEN array_slice(toks,1,cast(cardinality(toks) AS BIGINT)-1) END AS givens,
 dates,full_text,field_text,raw||' | '||fields AS raw_text,
 regexp_like(full_text,'\b(former|retired|ex-)\b|\b(19|20)\d\d\s*[-–]\s*(19|20)\d\d\b') AS says_former,
 -- A legislature named by its state ('Utah House of Representatives') is read with the states in witness_member_mentions.
 regexp_like(full_text,'\bstate (senator|senate|representative|house|legislat\w*|assembl\w*)\b|\bassembly(man|woman|member)\b|\bstatehood (senator|representative)\b|\bshadow (senator|representative)\b|\b(senator|representative|senate|house),? (\w+ ){0,2}(legislature|general assembly)\b|\blegislative district\b') AS says_state_legislature,
 regexp_like(field_text,'\b(clerk|chief administrative officer|sergeant at arms|doorkeeper|parliamentarian|legislative counsel|law revision counsel|inspector general|chaplain|historian|secretary of the senate|staff\w*|counsel|office of (the )?(senator|representative|congress\w*))\b') AS says_officer,
 regexp_like(field_text,'(^|\|\s*)(nominee (to be|for)\b|(of [a-z .]+, )?to be\b)')
  OR (regexp_like(title,'nominat','i') AND cardinality(toks)>=2
   -- The nomination hearing names this person, given and family name: a Member introducing a namesake is not it.
   AND strpos(title_words,' '||toks[cast(cardinality(toks) AS BIGINT)]||' ')>0
   AND cardinality(array_except(array_slice(toks,1,cast(cardinality(toks) AS BIGINT)-1),
    string_to_array(trim(title_words),' ')))<cardinality(toks)-1) AS says_nominee,
 CASE WHEN regexp_like(full_text,'\bsenator\b|\bunited states senate\b|\bu\.\s?s\.\s?senate\b')
   OR regexp_like(field_lines_folded,'(?m)^\W*sen\.?\W*$') THEN 'senate'
  WHEN regexp_like(name_lines_folded,'(?m)\brepresentative in congress\b|\b(u\.\s?s\.|united states|us)\s+(house of )?representatives?\b|\bcongress(wo)?man\b|\bdelegate (in|to|from|of|for)\b|\bresident commissioner\b|^\W*representative\s*($|,|\(|from\b|in\b)|\brepresentative\s*(\(|from\b)|\bcongressional district\b|^\W*rep\.?\W*$|\([a-z]{2}-(\d+|al|at[- ]large)\)') THEN 'house'
  WHEN regexp_like(full_text,'\b(member of (the )?(united states |u\.\s?s\.\s?)?congress|members? of congress)\b') THEN 'either' END AS chamber,
 -- A congressional role opening a field, with a full first name (witness_member_tiers): chair or ranking member of a
 -- committee, subcommittee, caucus, conference or congressional commission; a committee member; a leadership office.
 regexp_like(field_lines_folded,'(?m)^\W*(chair(man|woman|person)?|ranking (minority )?member|vice[- ]chair\w*|co-?chair\w*)\b[^|]*?(\|[^|]*?)?(\b(committee|subcommittee|caucus|conference)\b|\bcongressional[- ](\w+ )?commission\b)|\bmember of the (house |senate )?(permanent |special )?(select |joint )?committee\b|\b(speaker of the house|majority leader|minority leader|majority whip|minority whip|democratic leader|republican leader)\b') AS says_role
FROM tokened
