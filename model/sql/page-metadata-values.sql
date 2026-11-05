-- One row per declared string fact: field `fact:<name> <JSON Pointer>` = the literal value.
-- Dates follow adapters/common.reported_time: the stated local date, no zone conversion,
-- date-only stays day precision; anything else (20250401, RFC 2822, day 30 of February) has no date.
WITH entries AS (
 SELECT body_sha,body_hex,unnest(fields) AS f FROM html_metadata_readings
), facts AS (
 SELECT body_sha,body_hex,substr(f['field'],6) AS named,f['value'] AS value FROM entries WHERE starts_with(f['field'],'fact:')
), parsed AS (
 -- The engine's regexp_match omits groups that did not take part, so each part is read on its own.
 SELECT body_sha,body_hex,split_part(named,' ',1) AS field,substr(named,strpos(named,' ')+1) AS path,value,
  trim(value) AS v FROM facts
), shaped AS (
 SELECT *,regexp_like(v,'^[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:[.][0-9]+)?)?(?:Z|[+-][0-9]{2}(?::?[0-9]{2})?)?)?$') AS shaped,
  length(v)>10 AS clock,regexp_like(v,'^.{10}[T ][0-9]{2}:[0-9]{2}:[0-9]{2}') AS seconds
 FROM parsed
), dated AS (
 -- The shape fixes two-digit parts, so they compare as text: no cast (the engine evaluates
 -- casts on rows a CASE would skip).
 SELECT *,CASE WHEN shaped AND field IN ('published_time','modified_time')
   AND (NOT clock OR (substr(v,12,2)<'24' AND substr(v,15,2)<'60' AND (NOT seconds OR substr(v,18,2)<'60')
     AND NOT regexp_like(substr(v,17),'[+-](?:2[4-9]|[3-9][0-9])(?::?[0-9]{2})?$')))
   THEN try_cast(substr(v,1,10) AS DATE) END AS stated_date
 FROM shaped
)
SELECT body_sha,body_hex,field,value,path,
 CASE WHEN starts_with(path,'/formats/') THEN split_part(path,'/',3) ELSE split_part(path,'/',2) END AS format,
 stated_date AS date,
 CASE WHEN stated_date IS NULL THEN NULL WHEN NOT clock THEN 'day' WHEN seconds THEN 'second' ELSE 'minute' END AS precision
FROM dated
