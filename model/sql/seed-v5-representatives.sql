SELECT document_id,min(legacy_document_id) AS legacy_document_id FROM seed_identities GROUP BY document_id
