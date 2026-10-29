-- Only the display fold reads raw field names; typed lookup keys come from columns.
WITH fields AS (
 SELECT source_id,unnest(fields) AS fact FROM source_filename_readings WHERE status='completed'
), values AS (
 SELECT f.source_id,f.fact['field'] AS field,f.fact['value'] AS value
 FROM display_facts d JOIN fields f ON f.fact['field']=d.field
), kept AS (
 SELECT DISTINCT source_id,field,CASE WHEN field='date_token_candidates' THEN
 coalesce(cast(coalesce(try_cast(value AS DATE),try_cast(regexp_replace(value,
 '^([0-9]{4})([0-9]{2})([0-9]{2})$','$1-$2-$3') AS DATE)) AS VARCHAR),value)
 ELSE value END AS value FROM values
)
SELECT source_id,array_agg(named_struct('field',field,'value',value) ORDER BY field,value) AS facts
FROM kept GROUP BY source_id
