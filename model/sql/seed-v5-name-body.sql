WITH names AS (
 SELECT body_key,filename,min(name_priority) AS priority FROM seed_file_values
 WHERE body_key IS NOT NULL AND filename IS NOT NULL AND trim(filename)<>'' GROUP BY body_key,filename
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY body_key ORDER BY priority,filename) AS preference,
 count(*) OVER(PARTITION BY body_key) AS candidates FROM names
)
SELECT body_key,filename,candidates FROM ranked WHERE preference=1
