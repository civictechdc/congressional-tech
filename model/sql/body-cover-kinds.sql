-- Resolve verified Tier-1 body cover kinds onto documents lacking a kind or uploaded into
-- ambiguous Clerk / committee filename slots (-Bio-, -SD-, -Wstate-) where witnesses and staff
-- routinely place Truth-in-Testimony disclosures, questionnaires, CRS/GAO reports, or CBO estimates.
SELECT n.doc_key,
 make_array(bs.cover_document_kind) AS cover_document_kind,
 make_array(CASE bs.cover_document_kind
  WHEN 'testimony-disclosure' THEN 'disclosure'
  WHEN 'questionnaire' THEN 'questions-and-answers'
  WHEN 'witness-list' THEN 'list'
  WHEN 'meeting-notice' THEN 'notice'
  ELSE bs.cover_document_kind
 END) AS cover_document_family
FROM (
 SELECT body_sha,cover_document_kind
 FROM (
  SELECT body_sha,status,error_response,cover_document_kind FROM body_signals
  UNION ALL
  SELECT body_sha,status,error_response,cover_document_kind FROM pdf_cover_signals
 )
 WHERE status='completed' AND NOT error_response AND cover_document_kind IS NOT NULL
) bs
JOIN (
 SELECT doc_key,filename,document_kind,arrow_cast(decode(body_hex,'hex'),'FixedSizeBinary(32)') AS body_sha
 FROM base_normalized
 WHERE body_hex IS NOT NULL
) n ON bs.body_sha=n.body_sha
WHERE coalesce(array_length(n.document_kind),0)=0
 OR regexp_like(coalesce(n.filename,''),'(?i)-(?:Bio|SD|Wstate)(?:[0-9]*)(?:[-_.]|$)')
 OR (
  array_length(n.document_kind)=1
  AND n.document_kind[1] IN ('witness-biography','biography','support-document','supporting-material','witness-support','meeting-support')
  AND bs.cover_document_kind<>n.document_kind[1]
 )
