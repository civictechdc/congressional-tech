-- ct-sfra: what the print's own transcript says of each candidate row (witness_transcript_rows), the one place the
-- archive reads it. An entry, or another row, names the row's person when its family word is the row's and, when both
-- print one, a given initial agrees (the entry's is among the row's initials; another row shares one).
--  transcript      the print has a transcript read that heads someone (a stub page or a print whose headings the
--                  reader cannot see decides nothing);
--  roster_listed   the print's roster page lists the person (in the state the row says 'from', when it says one);
--  testified       a testimony heading names the person, or names them at the table ('ACCOMPANIED BY'), and the
--                  roster page does not list them: a committee member's own heading is not testimony;
--  appeared        testified, or the proceedings name them 'Also present' (a Member introducing a nominee or sitting in
--                  by consent) and the roster page does not list them;
--  promote         a record entry (statement_for_record) of a person who testified, matched cleanly (the heading's
--                  given initial is the first of the row's name: 'Letter from Ann Webb' takes no Ann Webb), whom no
--                  other appearance at the occasion names: a witness, read by witness_member_facts so a sitting Member
--                  is a Member appearance (being present at the hearing is no testimony);
--  statement_only  an untyped row whose words name a statement, of a person who did not appear: a sitting Member's is
--                  published as a Member statement (archive_model.WITNESSES_SQL).
-- Every join reads the small candidate rows first; the aggregates run over matched rows only.
WITH candidates AS (
 SELECT * FROM witness_transcript_rows WHERE candidate
), headed_prints AS (
 SELECT DISTINCT package_id FROM witness_transcript_entries WHERE kind IN ('statement','opening','prepared','accompanying')
), matched AS (
 SELECT r.witness_key,
  bool_or(e.kind IN ('statement','accompanying')) AS headed,bool_or(e.kind='present') AS present,
  bool_or(e.kind IN ('statement','accompanying') AND e.given<>'' AND e.given=substr(r.initials,1,1)) AS headed_clean,
  bool_or(e.kind='roster' AND (NOT regexp_like(r.words,'\bfrom\b') OR e.style IS NULL
   OR strpos(r.words,lower(split_part(e.style,',',1)))>0)) AS roster_listed
 FROM candidates r JOIN witness_transcript_entries e ON e.package_id=r.package_id AND e.family=r.family
 WHERE e.given='' OR r.initials='' OR strpos(r.initials,e.given)>0
 GROUP BY r.witness_key
), elsewhere AS (
 SELECT b.witness_key
 FROM (SELECT witness_key,person,occasion,family,initials FROM candidates WHERE witness_type='statement_for_record') b
 JOIN (SELECT person,occasion,family,initials FROM witness_transcript_rows
  WHERE coalesce(witness_type,'') NOT IN ('statement_for_record','member_statement','record_material')) o
  ON o.occasion=b.occasion AND o.family=b.family AND o.person<>b.person
 WHERE b.initials='' OR o.initials='' OR regexp_like(o.initials,'['||b.initials||']')
 GROUP BY b.witness_key
), facts AS (
 SELECT r.witness_key,r.person,r.package_id,r.witness_type,r.says_statement,r.says_opening,
  s.package_id IS NOT NULL AS transcript,coalesce(m.roster_listed,false) AS roster_listed,
  coalesce(m.headed AND NOT m.roster_listed,false) AS testified,coalesce(m.headed_clean AND NOT m.roster_listed,false) AS testified_clean,
  coalesce((m.headed OR m.present) AND NOT m.roster_listed,false) AS appeared,o.witness_key IS NOT NULL AS listed_elsewhere
 FROM elsewhere o RIGHT JOIN (matched m RIGHT JOIN (headed_prints s RIGHT JOIN candidates r ON s.package_id=r.package_id)
  ON m.witness_key=r.witness_key) ON o.witness_key=r.witness_key
)
SELECT witness_key,person,package_id,witness_type,says_statement,says_opening,transcript,roster_listed,testified,appeared,
 listed_elsewhere,witness_type='statement_for_record' AND testified_clean AND NOT listed_elsewhere AS promote,
 says_statement AND transcript AND NOT appeared AS statement_only
FROM facts
