-- Only the display fold reads raw field names; typed lookup keys come from columns.
WITH fields AS (
 SELECT source_id,unnest(fields) AS fact FROM source_filename_readings WHERE status='completed'
), filtered AS (
 SELECT source_id,fact['field'] AS field,fact['value'] AS value FROM fields
 WHERE fact['field'] IN ('document_kind','document_family','committee_code','congress','measure_references','date_token_candidates')
), kept AS (
 SELECT DISTINCT source_id,field,CASE WHEN field='date_token_candidates' THEN
 coalesce(cast(coalesce(try_cast(value AS DATE),try_cast(regexp_replace(value,
 '^([0-9]{4})([0-9]{2})([0-9]{2})$','$1-$2-$3') AS DATE)) AS VARCHAR),value)
 ELSE value END AS value FROM filtered
)
SELECT source_id,array_agg(named_struct('field',field,'value',value) ORDER BY field,value) AS facts
FROM kept GROUP BY source_id
