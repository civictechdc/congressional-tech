SELECT o.body_sha,max(o.format) AS format,bool_or(o.intact) AS intact,max(o.error_type) AS error_type,
 CASE WHEN bool_or(o.intact IS NOT NULL AND o.intact_basis='read') THEN 'read' ELSE 'capture' END AS intact_basis
FROM sniff_conflicts c RIGHT ANTI JOIN sniff_observations o ON c.body_sha=o.body_sha
GROUP BY o.body_sha
