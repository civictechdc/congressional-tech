SELECT DISTINCT m.component,m.source_id,c.context_url AS url,c.member_path,m.first_fetched
FROM document_members m JOIN capture_sources c ON m.source_id=c.source_id
WHERE m.is_real_file AND c.outcome NOT IN ('reference','saved-record')
