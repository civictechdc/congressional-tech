-- Constituent granule print citations from GovInfo MODS relatedItem[@type="constituent"] (ct-n131).
SELECT substr(field,9) AS granule_id,max(value) AS print_number
FROM gpo_mods_fields WHERE starts_with(field,'granule:') AND length(field)>8
GROUP BY 1
