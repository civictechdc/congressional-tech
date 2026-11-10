-- ct-kw85: what a witness row with a sitting candidate says about places, one row per witness row: the states it
-- names ('from (the State of) X', 'State of X', "X's 2nd District", 'Nth District of X', 'District, X', a field that
-- is the state, '(D-XX)', '(XX-3)', '(XX-At Large)'), whether it names a state legislature ('Utah House of
-- Representatives', 'MN House'), and whether every field speaks of Congress or a place (a stated state beside
-- someone else's employer is not the Member's). The state list has its one owner here; its own step so the regex
-- join over the states runs once.
WITH states(name,code) AS (VALUES ('alabama','AL'),('alaska','AK'),('arizona','AZ'),('arkansas','AR'),('california','CA'),('colorado','CO'),('connecticut','CT'),('delaware','DE'),('florida','FL'),('georgia','GA'),('hawaii','HI'),('idaho','ID'),('illinois','IL'),('indiana','IN'),('iowa','IA'),('kansas','KS'),('kentucky','KY'),('louisiana','LA'),('maine','ME'),('maryland','MD'),('massachusetts','MA'),('michigan','MI'),('minnesota','MN'),('mississippi','MS'),('missouri','MO'),('montana','MT'),('nebraska','NE'),('nevada','NV'),('new hampshire','NH'),('new jersey','NJ'),('new mexico','NM'),('new york','NY'),('north carolina','NC'),('north dakota','ND'),('ohio','OH'),('oklahoma','OK'),('oregon','OR'),('pennsylvania','PA'),('rhode island','RI'),('south carolina','SC'),('south dakota','SD'),('tennessee','TN'),('texas','TX'),('utah','UT'),('vermont','VT'),('virginia','VA'),('washington','WA'),('west virginia','WV'),('wisconsin','WI'),('wyoming','WY'),('american samoa','AS'),('district of columbia','DC'),('guam','GU'),('northern mariana islands','MP'),('puerto rico','PR'),('virgin islands','VI')), covered AS (
 SELECT f.id AS witness_key,f.full_text,f.field_text,f.raw_text
 FROM (SELECT DISTINCT witness_key FROM witness_member_candidates) c JOIN witness_member_facts f ON f.id=c.witness_key AND f.side='witness'
), named AS (
 SELECT r.witness_key,s.code,
  regexp_like(r.full_text,'\bfrom\s+(the\s+)?((state|commonwealth|territory)\s+of\s+)?'||s.name||'\b|\b(state|commonwealth|territory)\s+of\s+'||s.name
   ||'\b|\b'||s.name||'(''s|’s)?,?\s+(\w+\s+){0,2}(congressional\s+)?district\b|\b(at[- ]large|\w+) (congressional )?district of '||s.name
   ||'\b|\bdistrict[,;]?\s+'||s.name||'\b|(^|\|)\s*(of (the (state|commonwealth|territory) of )?)?'||s.name||'[\s.,;:]*($|\|)')
   OR regexp_like(r.raw_text,'\b[DRI]\s*[-–]\s*'||s.code||'\b|\('||s.code||'-(\d+|AL|At[- ]Large)\)') AS stated,
  regexp_like(r.full_text,'\b'||s.name||' (state )?(house of representatives|house of delegates|senate|legislature|general assembly|assembly)\b')
   OR regexp_like(r.raw_text,'\b'||s.code||' (State )?(House|Senate|Legislature|General Assembly|Assembly)\b') AS legislature
 FROM states s JOIN covered r ON strpos(r.full_text,s.name)>0 OR strpos(r.raw_text,s.code)>0
), segments AS (
 SELECT witness_key,unnest(string_to_array(field_text,'|')) AS segment FROM covered
), placed_segments AS (
 SELECT DISTINCT g.witness_key,g.segment FROM states s JOIN segments g ON strpos(g.segment,s.name)>0
), about_congress AS (
 SELECT g.witness_key,bool_and(p.segment IS NOT NULL OR regexp_like(g.segment,'congress|senat|house|representative|delegate|commissioner|member|committee|caucus|chair|ranking|district|statement|leader|whip|speaker|majority|minority|conference|subcommittee|delegation|panel|introduc|sponsor|testimony|honorable|\bhon\b')) AS about_congress
 FROM placed_segments p RIGHT JOIN segments g ON p.witness_key=g.witness_key AND p.segment=g.segment
 WHERE regexp_like(g.segment,'\S') GROUP BY g.witness_key
), mentions AS (
 SELECT witness_key,array_agg(code) FILTER (WHERE stated) AS states,bool_or(legislature) AS legislature FROM named GROUP BY witness_key
)
SELECT r.witness_key,coalesce(m.states,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS states,
 coalesce(m.legislature,false) AS names_legislature,coalesce(a.about_congress,true) AS about_congress
FROM about_congress a RIGHT JOIN (mentions m RIGHT JOIN covered r ON m.witness_key=r.witness_key) ON a.witness_key=r.witness_key
