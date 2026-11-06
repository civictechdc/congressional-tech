SELECT DISTINCT d.doc_key,c.context_url
FROM page_metadata_documents d JOIN (SELECT DISTINCT body_sha FROM page_metadata_values WHERE field='declared_url') declared
ON declared.body_sha=d.body_sha
JOIN document_identities i ON d.doc_key=i.document_id
JOIN document_members m ON m.component=i.component AND m.body_sha=d.body_hex
JOIN capture_sources c ON c.source_id=m.source_id AND c.body_sha=m.body_sha
WHERE c.is_real_file AND c.outcome NOT IN ('reference','saved-record') AND c.context_url IS NOT NULL
