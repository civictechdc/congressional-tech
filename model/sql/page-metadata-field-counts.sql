SELECT body_sha,field,count(*) AS field_count
FROM page_metadata_values GROUP BY body_sha,field
