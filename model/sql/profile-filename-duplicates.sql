SELECT count(*) AS cnt FROM (
 SELECT filename,source_url,catalog_version FROM filename_readings
 GROUP BY filename,source_url,catalog_version HAVING count(*)>1
)
