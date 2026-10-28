SELECT f.source_id,f.code FROM source_annotation_codes f
WHERE NOT EXISTS (SELECT 1 FROM committee_codes c WHERE c.code=f.code)
