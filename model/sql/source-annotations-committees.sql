WITH mapped AS (
 SELECT DISTINCT f.source_id,c.system_code,c.chamber FROM committee_codes c JOIN source_annotation_codes f ON f.code=c.code
)
SELECT source_id,array_sort(array_distinct(array_agg(system_code))) AS committee_keys,
 array_sort(array_distinct(array_agg(chamber))) AS chambers FROM mapped GROUP BY source_id
