-- Group only scalar byte counts; never retain the complete metadata rows in a window.
SELECT doc_key,sum(literal_bytes+address_bytes) AS expanded_bytes,
 sum(CASE WHEN literal_position=1 THEN literal_bytes ELSE 0 END) AS base_bytes,
 sum(CASE WHEN literal_position=1 AND selected THEN literal_bytes ELSE 0 END) AS selected_bytes
FROM document_page_metadata_entries GROUP BY doc_key
