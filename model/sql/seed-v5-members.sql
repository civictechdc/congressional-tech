SELECT m.* FROM seed_document_admission d RIGHT JOIN seed_all_members m
ON (d.legacy_document_id IS NOT DISTINCT FROM m.legacy_document_id)
WHERE d.legacy_document_id IS NOT NULL AND d.exclusion_reason IS NULL AND m.filename IS NOT NULL AND trim(m.filename)<>''
