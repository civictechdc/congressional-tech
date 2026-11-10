-- DM 7.5 saved-file order chooses the saved body; among that body's source
-- files a named one comes first, then one with an address or a member path (a
-- ZIP member, whose source has no address of its own, is a first-class copy; a
-- source with neither never leads one that has either, so the published address
-- never goes blank), then by name standing (saved-name-standing.sql): an
-- official name no committee name contradicts, then a committee name that
-- states a kind beside an official name (ct-h8dr, ct-yuf0), then one whose
-- capture stored these bytes: a file whose captures only found the archive
-- already holding them (body_stored false, a later fetch of the same bytes at
-- another address) cannot rename the document or replace what its name says
-- (ct-f7hp). Otherwise saved-file order holds. The flag is the capture
-- writer's: every fetch before 2026-10-30 says stored, so among those copies
-- the newest still leads. The body cannot change, only these rows' places.
-- Running windows only, so the plan streams (no whole-partition WindowAggExec).
WITH ranked AS (
 SELECT m.*,row_number() OVER w AS base_rank,first_value(m.body_sha) OVER w AS saved_body
 FROM formats p RIGHT JOIN (SELECT * FROM document_members WHERE is_real_file) m
  ON p.kind='preference' AND p.value=m.format
 WINDOW w AS (PARTITION BY m.component ORDER BY coalesce(p.rank,2147483647),
 CASE WHEN p.rank IS NULL THEN m.format ELSE '' END,coalesce(m.exact_bytes,false) DESC,
 m.first_fetched DESC NULLS LAST,m.body_sha,m.source_id)
)
SELECT * EXCLUDE(base_rank,saved_body,is_saved_body,body_stored,name_standing),row_number() OVER(PARTITION BY component
 ORDER BY is_saved_body DESC,is_saved_body AND coalesce(filename,'')='',
  is_saved_body AND source_url IS NULL AND NOT coalesce(archive_member,false),
  CASE WHEN is_saved_body THEN name_standing ELSE 0 END,
  is_saved_body AND NOT body_stored,base_rank) AS saved_rank
FROM (SELECT r.*,r.body_sha IS NOT DISTINCT FROM r.saved_body AS is_saved_body,coalesce(n.standing,2) AS name_standing
 FROM saved_name_standing n RIGHT JOIN ranked r ON n.source_id=r.source_id)
