-- ct-sfra (owner decision 2026-11-11, 'Transcripts decide in the rule'): the rows whose type the print's own transcript
-- decides (candidate), and beside them every untyped named row of any source at an occasion where a MODS record entry
-- is a candidate (to tell whether that person is listed there already), each once, with the name key transcript
-- entries are matched by. A candidate is a MODS row of a print that is
--  says_statement  untyped, and its words name a statement ('prepared statement', 'Statement of', 'Written Statement')
--                  and say neither opening statement (the committee rule's, witness_member_committees) nor testimony,
--                  testified or oral (the line's own word that the person testified is trusted);
--  says_opening    untyped, and its words say opening statement: before the rosters the print's roster page seats a
--                  committee member;
--  a record entry  typed statement_for_record: a testimony the transcript heads makes it a witness.
-- The name key is the transcript reader's own (parsers.gpo_headings.name_key) read from the row's name: accents folded
-- (name_fold), nicknames in quotes or parentheses and apostrophes dropped, suffix words dropped; family is the last word,
-- initials the first letters of the others ('statement for the record. Dona Abbott': abbott, sftrd). words keeps the
-- row's own text, for the roster page's state. Its own step: the entries and facts steps read it.
WITH rows AS (
 SELECT r.witness_key,coalesce(p.superseded_by,r.witness_key) AS person,r.occasion,r.source,r.package_id,r.witness_type,
  translate(lower(concat_ws(' | ',r.name,r.position,r.organization,r.on_behalf_of,r.location)),f.accented,f.plain) AS words,
  translate(lower(r.name),f.accented,f.plain) AS folded_name
 FROM name_fold f CROSS JOIN (witness_precedence p RIGHT JOIN appearance_records_resolved r ON p.witness_key=r.witness_key)
 WHERE r.name IS NOT NULL
), classed AS (
 -- 'opening statement' is read as witness_member_facts reads it (says_opening there).
 SELECT *,regexp_like(words,'\bopening statement') AS says_opening,
  regexp_like(words,'\bstatements?\b')
   AND NOT regexp_like(words,'\bopening statement|\btestimony\b|\btestified\b|\boral\b') AS says_statement,
  source='mods' AND package_id IS NOT NULL AND witness_type='statement_for_record' AS record_entry
 FROM rows
), scoped AS (
 SELECT *,record_entry OR (source='mods' AND package_id IS NOT NULL AND witness_type IS NULL AND (says_statement OR says_opening))
   AS candidate,
  bool_or(record_entry) OVER (PARTITION BY occasion) AS entry_occasion
 FROM classed
 ), tokened AS (
 SELECT *,string_to_array(trim(regexp_replace(regexp_replace(regexp_replace(regexp_replace(regexp_replace(regexp_replace(folded_name,
   '``[^'']*''''|"[^"]*"|\([^)]*\)',' ','g'),'[''’`]','','g'),'[^a-z]+',' ','g'),
   '(^| )(jr|sr|ii|iii|iv|md|phd|esq|ret)( |$)',' ','g'),'(^| )(jr|sr|ii|iii|iv|md|phd|esq|ret)( |$)',' ','g'),'\s+',' ','g')),' ') AS name_words
 FROM scoped
 WHERE candidate OR (entry_occasion AND coalesce(witness_type,'') NOT IN ('statement_for_record','member_statement','record_material'))
)
SELECT witness_key,person,occasion,source,package_id,witness_type,candidate,
 candidate AND witness_type IS NULL AND says_statement AS says_statement,candidate AND witness_type IS NULL AND says_opening AS says_opening,
 words,nullif(name_words[cast(cardinality(name_words) AS BIGINT)],'') AS family,
 CASE WHEN cardinality(name_words)>1 THEN regexp_replace(array_to_string(array_slice(name_words,1,cast(cardinality(name_words) AS BIGINT)-1),' '),
  '([a-z])[a-z]*\s*','$1','g') ELSE '' END AS initials
FROM tokened
