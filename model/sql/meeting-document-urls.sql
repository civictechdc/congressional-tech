-- The files a publisher's meeting record lists (House XML <file doc-url>, Congress.gov
-- meetingDocuments/witnessDocuments), plus Congress.gov URLs retained as no_longer_listed (ct-960v)
-- so document-to-meeting links never break when Congress.gov drops a file on a re-fetch.
SELECT DISTINCT event_id,trim(url) AS url FROM (
 SELECT event_id,unnest(document_urls) AS url FROM meeting_records_current WHERE coalesce(array_length(document_urls),0)>0
 UNION ALL
 SELECT event_id,unnest(retained_document_urls) AS url FROM congress_gov_retained_items WHERE coalesce(array_length(retained_document_urls),0)>0
) WHERE url IS NOT NULL AND trim(url)<>''
