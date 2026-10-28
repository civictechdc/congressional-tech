-- The shared line-level predicate; imports qualify as fetches, but not as capture dates.
SELECT * FROM capture_evidence WHERE mode='fetch' AND complete
 AND outcome IN ('stored','unchanged') AND http_status BETWEEN 200 AND 299
