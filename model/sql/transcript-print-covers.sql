-- DM 7.5, ct-isnv (owner, 2026-11-11: filter the transcript words together, label each document as
-- what it is). A document a committee calls a transcript ('transcript'; the House name's
-- 'committee-transcript' is the committee's own) whose saved text opens with a GPO printed hearing's
-- cover (page signals kind print_cover: the hearing number and the GPO imprint) is that printed
-- hearing; the normalized step tags it published-hearing. Only HTML, XML and JSON bodies are read
-- (page_facts), so a PDF labelled transcript keeps its label. The candidates, a few hundred, build.
SELECT DISTINCT n.doc_key FROM (
 SELECT doc_key,arrow_cast(decode(body_hex,'hex'),'FixedSizeBinary(32)') AS body_sha FROM base_normalized
 WHERE array_has(document_kind,'transcript') AND NOT array_has(document_kind,'committee-transcript') AND body_hex IS NOT NULL
) n JOIN page_facts f ON f.body_sha=n.body_sha AND f.status='completed'
JOIN (SELECT pattern FROM page_signals WHERE kind='print_cover') p ON regexp_like(f.text_head,p.pattern)
