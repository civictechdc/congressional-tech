-- Only the display fold reads raw field names; typed lookup keys come from columns.
WITH fields AS (
 SELECT source_id,unnest(fields) AS fact FROM source_filename_readings WHERE status='completed'
), filtered AS (
 SELECT source_id,
 named_struct('field',fact['field'],'value',CASE WHEN fact['field']='date_token_candidates' THEN
 coalesce(cast(coalesce(try_cast(fact['value'] AS DATE),try_cast(regexp_replace(fact['value'],
 '^([0-9]{4})([0-9]{2})([0-9]{2})$','$1-$2-$3') AS DATE)) AS VARCHAR),fact['value'])
 ELSE fact['value'] END) AS fact
 FROM fields
 WHERE fact['field'] IN ('document_kind','document_family','committee_code','congress','measure_references','date_token_candidates')
)
SELECT source_id,array_agg(DISTINCT fact ORDER BY fact) AS facts
FROM filtered GROUP BY source_id
