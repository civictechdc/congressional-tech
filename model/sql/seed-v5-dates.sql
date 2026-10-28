SELECT document_id AS legacy_document_id,
 min(cast(to_char(arrow_cast(try_cast(stamp AS TIMESTAMP),'Timestamp(Microsecond, Some("UTC"))')
 AT TIME ZONE 'America/New_York','%Y-%m-%d') AS DATE)) AS first_captured
FROM (SELECT document_id,unnest(state_retrieved_at) AS stamp FROM v5_documents) GROUP BY document_id
