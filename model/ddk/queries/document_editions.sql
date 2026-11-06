SELECT DISTINCT other.list_row,other.filename,other.document_date
FROM "list" selected JOIN "list" other ON list_has_any(selected.version_keys,other.version_keys)
WHERE selected.list_row=? AND other.list_row<>selected.list_row ORDER BY other.list_row LIMIT 100