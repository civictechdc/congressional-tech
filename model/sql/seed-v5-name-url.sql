WITH names AS (
 SELECT body_key,source_url,filename,min(name_priority) AS priority FROM seed_file_values
 WHERE body_key IS NOT NULL AND filename IS NOT NULL AND trim(filename)<>'' GROUP BY body_key,source_url,filename
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY body_key,source_url ORDER BY priority,filename) AS preference,
 count(*) OVER(PARTITION BY body_key,source_url) AS candidates FROM names
)
SELECT body_key,source_url,filename,candidates FROM ranked WHERE preference=1
