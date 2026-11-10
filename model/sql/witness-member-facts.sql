-- ct-kw85: the facts witness_members weighs, one row per named witness row that is not a record entry and one per
-- Member, with both names read by the same rule so the two sides compare: accents folded, parentheticals and
-- everything after the first comma dropped ('Bill Cassidy, M.D.'), honorifics, ranks and suffixes dropped as words,
-- trailing initials dropped ('M.D.'), repeats kept once. A witness row also carries its hearing dates (the meeting's
-- date, else the print's heldDates), its hearing title and what its own words say: former or a closed span of years,
-- a state legislature, a House or Senate officer or staffer, the person's own nomination ('to be ...', 'Nominee for'),
-- the chamber ('U.S. Senator', 'Representative in Congress', 'Member of Congress') and a committee role.
-- Its own step: witness_members reads these rows in several joins.
WITH witness_rows AS (
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
 SELECT 'witness' AS side,witness_key AS id,person,publisher_id,name AS raw,fields,name_lines,field_lines,dates,title FROM witness_rows
 UNION ALL
 SELECT 'member' AS side,bioguide_id AS id,cast(NULL AS VARCHAR) AS person,cast(NULL AS VARCHAR) AS publisher_id,
  trim(coalesce(name_first,'')||' '||coalesce(name_last,'')) AS raw,cast(NULL AS VARCHAR) AS fields,cast(NULL AS VARCHAR) AS name_lines,
  cast(NULL AS VARCHAR) AS field_lines,arrow_cast(NULL,'List(Utf8)') AS dates,cast(NULL AS VARCHAR) AS title
 FROM spicy_members WHERE bioguide_id IS NOT NULL
), cleaned AS (
 SELECT *,regexp_replace(translate(regexp_replace(regexp_replace(split_part(regexp_replace(
   translate(lower(raw),''áàâäãåāăąéèêëēėęěíìîïīįóòôöõøōőúùûüūůűñńçćčýÿšśžźżłđ'',''aaaaaaaaaeeeeeeeeiiiiiioooooooouuuuuuunncccyysszzzld''),'\([^)]*\)',' ','g'),',',1),'[''’`]','','g'),'[^a-z .\-]+',' ','g'),'.-','  '),
   '(\s+[a-z]){2,}\s*$','') AS cleaned_name,
  translate(lower(raw||' | '||fields),''áàâäãåāăąéèêëēėęěíìîïīįóòôöõøōőúùûüūůűñńçćčýÿšśžźżłđ'',''aaaaaaaaaeeeeeeeeiiiiiioooooooouuuuuuunncccyysszzzld'') AS full_text,
  translate(lower(fields),''áàâäãåāăąéèêëēėęěíìîïīįóòôöõøōőúùûüūůűñńçćčýÿšśžźżłđ'',''aaaaaaaaaeeeeeeeeiiiiiioooooooouuuuuuunncccyysszzzld'') AS field_text
 FROM named
), tokened AS (
 SELECT *,array_except(string_to_array(regexp_replace(trim(cleaned_name),'\s+',' ','g'),' '),
  make_array('','mr','mrs','ms','miss','mx','dr','hon','honorable','the','rev','reverend','sen','senator','rep','representative','gen','general','lt','lieutenant','col','colonel','maj','major','adm','admiral','vadm','radm','ltg','mg','bg','vice','rear','capt','captain','sgt','sergeant','brigadier','chief','ambassador','secretary','judge','governor','mayor','professor','prof','commissioner','chairman','chairwoman','chair','ranking','member','congressman','congresswoman','delegate','jr','sr','ii','iii','iv','phd','md','mph','jd','rn','mba','dvm','esq','cpa','edd','dds','mpa','mpp','msw','ret','usa','usn','usaf','usmc','uscg','ussf')) AS toks
 FROM cleaned
)
SELECT side,id,person,publisher_id,toks,
 CASE WHEN cardinality(toks)>=2 THEN toks[1] END AS given1,
 CASE WHEN cardinality(toks)>=3 AND length(toks[1])=1 THEN toks[2] END AS given2,
 CASE WHEN cardinality(toks)>=2 THEN toks[cardinality(toks)] END AS family,
 dates,full_text,field_text,raw||' | '||fields AS raw_text,
 regexp_like(full_text,'\b(former|retired|ex-)\b|\b(19|20)\d\d\s*[-–]\s*(19|20)\d\d\b') AS says_former,
 regexp_like(full_text,'\bstate (senator|senate|representative|house|legislat\w*|assembl\w*)\b|\bassembly(man|woman|member)\b|\bstatehood (senator|representative)\b|\bshadow (senator|representative)\b|\b(senator|representative|senate|house),? (\w+ ){0,2}(legislature|general assembly)\b|\b(northern mariana islands|district of columbia|american samoa|north carolina|south carolina|virgin islands|massachusetts|new hampshire|west virginia|north dakota|pennsylvania|rhode island|south dakota|connecticut|mississippi|puerto rico|california|new jersey|new mexico|washington|louisiana|minnesota|tennessee|wisconsin|arkansas|colorado|delaware|illinois|kentucky|maryland|michigan|missouri|nebraska|new york|oklahoma|virginia|alabama|arizona|florida|georgia|indiana|montana|vermont|wyoming|alaska|hawaii|kansas|nevada|oregon|idaho|maine|texas|guam|iowa|ohio|utah) (state )?(house of representatives|house of delegates|senate|legislature|general assembly|assembly)\b|\blegislative district\b')
  OR regexp_like(raw||' | '||fields,'\b(AK|AL|AR|AS|AZ|CA|CO|CT|DC|DE|FL|GA|GU|HI|IA|ID|IL|IN|KS|KY|LA|MA|MD|ME|MI|MN|MO|MP|MS|MT|NC|ND|NE|NH|NJ|NM|NV|NY|OH|OK|OR|PA|PR|RI|SC|SD|TN|TX|UT|VA|VI|VT|WA|WI|WV|WY) (State )?(House|Senate|Legislature|General Assembly|Assembly)\b') AS says_state_legislature,
 regexp_like(field_text,'\b(clerk|chief administrative officer|sergeant at arms|doorkeeper|parliamentarian|legislative counsel|law revision counsel|inspector general|chaplain|historian|secretary of the senate|staff\w*|counsel|office of (the )?(senator|representative|congress\w*))\b') AS says_officer,
 regexp_like(field_text,'(^|\|\s*)(nominee (to be|for)\b|(of [a-z .]+, )?to be\b)')
  OR (regexp_like(title,'nominat','i') AND cardinality(toks)>=2
   AND strpos(' '||regexp_replace(translate(lower(title),''áàâäãåāăąéèêëēėęěíìîïīįóòôöõøōőúùûüūůűñńçćčýÿšśžźżłđ'',''aaaaaaaaaeeeeeeeeiiiiiioooooooouuuuuuunncccyysszzzld''),'[^a-z]+',' ','g')||' ',' '||toks[cardinality(toks)]||' ')>0) AS says_nominee,
 CASE WHEN regexp_like(full_text,'\bsenator\b|\bunited states senate\b|\bu\.\s?s\.\s?senate\b') THEN 'senate'
  WHEN regexp_like(translate(lower(name_lines),''áàâäãåāăąéèêëēėęěíìîïīįóòôöõøōőúùûüūůűñńçćčýÿšśžźżłđ'',''aaaaaaaaaeeeeeeeeiiiiiioooooooouuuuuuunncccyysszzzld''),'(?m)\brepresentative in congress\b|\b(u\.\s?s\.|united states|us)\s+(house of )?representatives?\b|\bcongress(wo)?man\b|\bdelegate (in|to|from|of|for)\b|\bresident commissioner\b|^\W*representative\b|\brepresentative\s*(\(|from\b)|\bcongressional district\b') THEN 'house'
  WHEN regexp_like(full_text,'\b(member of (the )?(united states |u\.\s?s\.\s?)?congress|members? of congress)\b') THEN 'either' END AS chamber,
 regexp_like(translate(lower(field_lines),''áàâäãåāăąéèêëēėęěíìîïīįóòôöõøōőúùûüūůűñńçćčýÿšśžźżłđ'',''aaaaaaaaaeeeeeeeeiiiiiioooooooouuuuuuunncccyysszzzld''),'(?m)^\W*(chair(man|woman|person)?|ranking (minority )?member|vice[- ]chair\w*|co-?chair\w*)\b[^|]*?(\|[^|]*?)?\b(committee|subcommittee|caucus|commission)\b|\bmember of the (house |senate )?(permanent |special )?(select |joint )?committee\b|\b(speaker of the house|majority leader|minority leader|majority whip|minority whip|democratic leader|republican leader)\b') AS says_role
FROM tokened
