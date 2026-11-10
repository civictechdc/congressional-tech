-- DM 7.5, ct-yuf0: documents whose saved body carries names that state different kinds. One row per
-- document whose leading name states a kind another named, addressed copy of the same bytes does not
-- share (the families each copy would give the document), recomputed from the saved files pairwise,
-- not from the name standing. The three flags after official_leads describe the other names.
-- official_slot with committee_speaks and no committee_agrees is the case the rule forbids
-- (invariant contradicted_official_saved_names = 0): a House meeting-document slot name leading
-- against the committee's. official_leads without committee_speaks is two official names of
-- different kinds, which only a reading of the bytes can settle.
WITH said AS (
 SELECT s.component,s.source_id,s.saved_rank,coalesce(f.valid,false) AS official,f.document_family AS family
 FROM (SELECT component,body_sha FROM saved_files WHERE saved_rank=1) k
 JOIN saved_files s ON s.component=k.component AND s.body_sha=k.body_sha
 JOIN source_filename_readings f ON f.source_id=s.source_id
 WHERE coalesce(s.filename,'')<>'' AND (s.source_url IS NOT NULL OR coalesce(s.archive_member,false))
  AND f.document_family_status='completed' AND coalesce(array_length(f.document_family),0)>0
)
SELECT l.component,bool_or(l.official) AS official_leads,
 bool_or(l.official AND array_has_any(l.family,make_array('biography','disclosure','statement','supporting-material'))) AS official_slot,
 bool_or(NOT o.official) AS committee_speaks,
 bool_or(NOT o.official AND array_has_any(l.family,o.family)) AS committee_agrees
FROM (SELECT * FROM said WHERE saved_rank=1) l JOIN said o ON o.component=l.component AND o.saved_rank>1
GROUP BY l.component HAVING bool_or(NOT array_has_any(l.family,o.family))
