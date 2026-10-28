-- Several mirrors in one component count as one listed document.
SELECT k.url_key,count(DISTINCT l.component) AS components,min(l.component) AS component
FROM copy_url_keys k JOIN source_files f ON k.source_id=f.source_id AND f.is_real_file
JOIN source_labels l ON f.source_id=l.source_id WHERE k.url_key IS NOT NULL GROUP BY k.url_key
