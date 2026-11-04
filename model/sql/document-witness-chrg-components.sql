SELECT DISTINCT component FROM document_packages WHERE regexp_like(package_id,'(?i)^CHRG-')
UNION
SELECT DISTINCT m.component FROM document_members m
JOIN (SELECT source_id FROM source_annotations WHERE regexp_like(package_id,'(?i)^CHRG-')) a USING(source_id)
