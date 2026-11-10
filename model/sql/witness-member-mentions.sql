-- ct-kw85: what a candidate or seat row (witness_member_rows) says about places, one row per witness row: the states
-- it names ('from (the State of) X', 'State of X', "X's 2nd District", 'Nth District of X', 'District, X', a field that
-- is the state, '(D-XX)', '(XX-3)', '(XX-At Large)'), whether it names a state legislature ('Utah House of
-- Representatives', 'MN House'), whether every field speaks of Congress or a place (a stated state beside someone
-- else's employer is not the Member's), and the House seats it states as 'XX-n' (witness_member_seats): a district
-- of a state ('3d District, Utah', "Utah's 3d District", '12th District | FL', 'Utah, District 3', '(AR-2)'), 0 for
-- a state at large ('(ND-At Large)') or a territory's Delegate or Resident Commissioner ('a Delegate from Guam').
-- The row's own facts ride along for the steps after. The state list has its one owner here.
WITH states(name,code,territory) AS (VALUES ('alabama','AL',false),('alaska','AK',false),('arizona','AZ',false),('arkansas','AR',false),('california','CA',false),('colorado','CO',false),('connecticut','CT',false),('delaware','DE',false),('florida','FL',false),('georgia','GA',false),('hawaii','HI',false),('idaho','ID',false),('illinois','IL',false),('indiana','IN',false),('iowa','IA',false),('kansas','KS',false),('kentucky','KY',false),('louisiana','LA',false),('maine','ME',false),('maryland','MD',false),('massachusetts','MA',false),('michigan','MI',false),('minnesota','MN',false),('mississippi','MS',false),('missouri','MO',false),('montana','MT',false),('nebraska','NE',false),('nevada','NV',false),('new hampshire','NH',false),('new jersey','NJ',false),('new mexico','NM',false),('new york','NY',false),('north carolina','NC',false),('north dakota','ND',false),('ohio','OH',false),('oklahoma','OK',false),('oregon','OR',false),('pennsylvania','PA',false),('rhode island','RI',false),('south carolina','SC',false),('south dakota','SD',false),('tennessee','TN',false),('texas','TX',false),('utah','UT',false),('vermont','VT',false),('virginia','VA',false),('washington','WA',false),('west virginia','WV',false),('wisconsin','WI',false),('wyoming','WY',false),('american samoa','AS',true),('district of columbia','DC',true),('guam','GU',true),('northern mariana islands','MP',true),('puerto rico','PR',true),('virgin islands','VI',true)
), named AS (
 SELECT r.witness_key,s.code,
  regexp_like(r.full_text,'\bfrom\s+(the\s+)?((state|commonwealth|territory)\s+of\s+)?'||s.name||'\b|\b(state|commonwealth|territory)\s+of\s+'||s.name
   ||'\b|\b'||s.name||'(''s|’s)?,?\s+(\w+\s+){0,2}(congressional\s+)?district\b|\b(at[- ]large|\w+) (congressional )?district of '||s.name
   ||'\b|\bdistrict[,;]?\s+'||s.name||'\b|(^|\|)\s*(of (the (state|commonwealth|territory) of )?)?'||s.name||'[\s.,;:]*($|\|)')
   OR regexp_like(r.raw_text,'\b[DRI]\s*[-–]\s*'||s.code||'\b|\('||s.code||'-(\d+|AL|At[- ]Large)\)') AS stated,
  regexp_like(r.full_text,'\b'||s.name||' (state )?(house of representatives|house of delegates|senate|legislature|general assembly|assembly)\b')
   OR regexp_like(r.raw_text,'\b'||s.code||' (State )?(House|Senate|Legislature|General Assembly|Assembly)\b') AS legislature,
  CASE WHEN s.territory AND regexp_like(r.full_text,'\b(delegate|resident commissioner)\b[^|]*?\b(from|of|for)\s+(the\s+)?((territory|commonwealth) of\s+)?'
    ||s.name||'\b') THEN 0
   WHEN regexp_like(r.full_text,'\('||lower(s.code)||'[- ](al|at[- ]large)\)|\b'||s.name||'\b[^|]*\bat[- ]large\b') THEN 0
   ELSE cast(coalesce((regexp_match(r.full_text,'\('||lower(s.code)||'[- ](\d+)\)'))[1],
    (regexp_match(r.full_text,'\b(\d+)(?:st|nd|rd|th|d)? (?:congressional )?district[,;]?\s*(?:\|\s*)?(?:of\s+)?(?:the\s+)?(?:state of\s+)?'||s.name||'\b'))[1],
    (regexp_match(r.full_text,'\b'||s.name||'(?:''s|’s)?,?\s*(?:\|\s*)?(\d+)(?:st|nd|rd|th|d)? (?:congressional )?district\b'))[1],
    (regexp_match(r.full_text,'\b(\d+)(?:st|nd|rd|th|d)? (?:congressional )?district\s*\|\s*'||lower(s.code)||'\s*(?:$|\|)'))[1],
    (regexp_match(r.full_text,'\b'||s.name||',? district (\d+)\b'))[1]) AS SMALLINT) END AS district
 FROM states s JOIN witness_member_rows r ON strpos(r.full_text,s.name)>0 OR strpos(r.raw_text,s.code)>0
), segments AS (
 SELECT witness_key,unnest(string_to_array(field_text,'|')) AS segment FROM witness_member_rows
), placed_segments AS (
 SELECT g.witness_key,g.segment,bool_or(s.code IS NOT NULL) AS placed
 FROM states s RIGHT JOIN segments g ON strpos(g.segment,s.name)>0
 WHERE regexp_like(g.segment,'\S') GROUP BY g.witness_key,g.segment
), about_congress AS (
 SELECT witness_key,bool_and(placed OR regexp_like(segment,'congress|senat|house|representative|delegate|commissioner|member|committee|caucus|chair|ranking|district|statement|leader|whip|speaker|majority|minority|conference|subcommittee|delegation|panel|introduc|sponsor|testimony|honorable|\bhon\b')) AS about_congress
 FROM placed_segments GROUP BY witness_key
), mentions AS (
 SELECT witness_key,array_agg(code) FILTER (WHERE stated) AS states,bool_or(legislature) AS legislature,
  array_agg(code||'-'||cast(district AS VARCHAR)) FILTER (WHERE district IS NOT NULL) AS seats
 FROM named GROUP BY witness_key
)
SELECT r.witness_key,r.person,r.chamber,r.says_role,r.says_nominee,r.seat_words,r.dates,
 coalesce(m.states,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS states,
 coalesce(m.legislature,false) AS names_legislature,coalesce(a.about_congress,true) AS about_congress,
 coalesce(m.seats,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS seats
FROM about_congress a RIGHT JOIN (mentions m RIGHT JOIN witness_member_rows r ON m.witness_key=r.witness_key) ON a.witness_key=r.witness_key
