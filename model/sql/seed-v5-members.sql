SELECT m.* FROM seed_all_members m JOIN seed_document_admission d USING(legacy_document_id)
WHERE d.exclusion_reason IS NULL
