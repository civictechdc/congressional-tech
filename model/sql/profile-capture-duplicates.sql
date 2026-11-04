SELECT count(*) AS cnt FROM (
 SELECT receipt_key,receipt_line,capture_index FROM captures
 GROUP BY receipt_key,receipt_line,capture_index HAVING count(*)>1
)
