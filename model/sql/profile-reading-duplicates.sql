SELECT count(*) AS cnt FROM (
 SELECT body_sha,parser,parser_version FROM readings
 GROUP BY body_sha,parser,parser_version HAVING count(*)>1
)
