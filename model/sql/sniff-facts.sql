SELECT o.body_sha,max(o.format) AS format,bool_or(o.intact) AS intact,max(o.error_type) AS error_type,
 CASE WHEN bool_or(o.intact IS NOT NULL AND o.intact_basis='read') THEN 'read' ELSE 'capture' END AS intact_basis
FROM sniff_observations o WHERE NOT EXISTS(SELECT 1 FROM sniff_conflicts c WHERE c.body_sha=o.body_sha)
GROUP BY o.body_sha
