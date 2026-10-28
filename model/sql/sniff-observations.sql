SELECT body_sha,format,intact,error_type,'read' AS intact_basis
FROM pinned_readings WHERE parser='sniff' AND status='completed'
UNION ALL
SELECT c.sha256 AS body_sha,c.sniffed_format AS format,c.intact,cast(NULL AS VARCHAR) AS error_type,'capture' AS intact_basis
FROM captures c JOIN parser_versions v ON v.parser='sniff' AND c.sniff_version=v.version
WHERE c.sha256 IS NOT NULL AND c.sniffed_format IS NOT NULL
