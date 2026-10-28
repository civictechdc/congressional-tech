WITH ranked AS (
 SELECT s.*,row_number() OVER(PARTITION BY component,format ORDER BY saved_rank) AS format_rank
 FROM saved_files s
)
SELECT a.component,array_agg(named_struct('format',a.format,'body',arrow_cast(decode(a.body_sha,'hex'),'FixedSizeBinary(32)'),
 'suffix',b.suffix,'size',b.original_size) ORDER BY a.saved_rank) AS alternates
FROM ranked a JOIN saved_files s ON a.component=s.component AND s.saved_rank=1
JOIN body_evidence b ON a.body_sha=b.body_sha
WHERE a.format<>s.format AND a.format_rank=1 GROUP BY a.component
