SELECT DISTINCT m.component,m.source_id,c.context_url AS url,c.member_path,m.first_fetched
FROM document_members m JOIN capture_source_contexts c ON m.source_id=c.source_id
WHERE m.is_real_file AND c.outcome NOT IN ('reference','saved-record') AND c.context_url IS NOT NULL
UNION
-- A recovered copy's original link is another address of the document it copies (DM 7.5), with
-- its own first try and the publisher links that list it.
SELECT DISTINCT m.component,m.source_id,m.source_url AS url,cast(NULL AS VARCHAR) AS member_path,m.first_fetched
FROM document_members m JOIN recovered_copy_members r ON r.source_id=m.source_id
UNION
-- A landing page's address is another address of the document named for it (DM 7.3, ct-m878), never
-- its saved one, with the page's own first fetch and the links that list it.
SELECT DISTINCT l.component,l.source_id,c.context_url AS url,c.member_path,l.first_fetched
FROM landing_pages l JOIN capture_source_contexts c ON c.source_id=l.source_id
WHERE l.component IS NOT NULL AND c.outcome NOT IN ('reference','saved-record') AND c.context_url IS NOT NULL
