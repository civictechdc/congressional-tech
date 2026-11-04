SELECT DISTINCT component FROM document_packages WHERE regexp_like(package_id,'(?i)^CHRG-')
UNION
SELECT DISTINCT m.component FROM document_members m
JOIN (SELECT source_id FROM source_annotations WHERE regexp_like(package_id,'(?i)^CHRG-')
 -- A printed hearing's addendum (CHRG-116hhrg43625-add2.pdf) names no GovInfo package but is still the print's.
 UNION SELECT source_id FROM source_filename_readings WHERE status='completed' AND regexp_like(package_id,'(?i)^CHRG-')) a USING(source_id)
