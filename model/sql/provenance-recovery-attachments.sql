SELECT r.*,CASE WHEN c.components=1 THEN c.component ELSE o.component END AS component
FROM model_recovery_rows r LEFT JOIN recovery_original_keys k ON r.recovery_id=k.recovery_id
LEFT JOIN recovery_copy_components c ON k.url_key=c.url_key
LEFT JOIN recovery_original_components o ON r.recovery_id=o.recovery_id
WHERE CASE WHEN c.components=1 THEN c.component ELSE o.component END IS NOT NULL
