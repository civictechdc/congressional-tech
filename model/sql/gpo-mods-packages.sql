-- Package-level GovInfo MODS preferredCitation read via parsers/gpo.py (ct-n131).
SELECT package_id,max(preferred_citation) AS print_number FROM (
 SELECT max(CASE WHEN field='package_id' THEN value END) AS package_id,
  max(CASE WHEN field='preferred_citation' THEN value END) AS preferred_citation
 FROM gpo_mods_fields WHERE field IN ('package_id','preferred_citation')
 GROUP BY body_sha
) WHERE package_id IS NOT NULL AND preferred_citation IS NOT NULL
GROUP BY package_id
