SELECT document_id,source_id,filename,source_url,body_key,source_page_url,source_link_label,source_document_type,source_document_added_at,format,body_format,media_type,response_format,CASE
 WHEN coalesce(array_has(recovered_filename,filename),false) OR coalesce(array_has(filename_origins,'recovery'),false) THEN 0
 WHEN coalesce(array_has(filename_origins,'archive_member'),false) THEN 1
 WHEN coalesce(array_has(filename_origins,'content_disposition'),false) THEN 2
 WHEN coalesce(array_has(filename_origins,'url_query'),false) THEN 3
 WHEN coalesce(array_has(filename_origins,'url_path'),false) THEN 4
 ELSE 5 END AS name_priority
FROM v5_filenames f
