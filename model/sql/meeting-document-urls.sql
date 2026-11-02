-- The files a publisher's current meeting record lists (House XML <file doc-url>, Congress.gov
-- meetingDocuments/witnessDocuments). Current records only, so a file a newer version removed does not link.
SELECT DISTINCT event_id,trim(url) AS url FROM (
 SELECT event_id,unnest(document_urls) AS url FROM meeting_records_current WHERE coalesce(array_length(document_urls),0)>0
) WHERE url IS NOT NULL AND trim(url)<>''
