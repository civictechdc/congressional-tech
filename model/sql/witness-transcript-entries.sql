-- ct-sfra: the transcript entries (transcript_headings) of the prints witness_transcript_rows names. A body is bound to
-- its print by the address it was fetched from: the print's HTML at its own address or as a ZIP member
-- ({{TRANSCRIPT_CAPTURE}}, the producer's own predicate). Each body a print has (direct fetches differ byte for byte,
-- Cloudflare rewrites an address per fetch) keeps its entries: a fact any of them states holds.
-- The candidate prints are joined to captures, and those bodies to the entries, before anything is read whole.
WITH prints AS (
 SELECT DISTINCT package_id FROM witness_transcript_rows WHERE candidate
), addressed AS (
 SELECT c.sha256,(regexp_match({{TRANSCRIPT_ADDRESS}},'(?i)(?:^|/)html/(CHRG-[0-9]+[hsj]hrg[0-9]+)[.]htm$'))[1] AS package_id
 FROM captures c WHERE {{GOOD_FETCH}} AND {{TRANSCRIPT_CAPTURE}}
), bodies AS (
 SELECT DISTINCT a.sha256,p.package_id FROM prints p JOIN addressed a ON lower(a.package_id)=lower(p.package_id)
)
SELECT package_id,e['kind'] AS kind,e['family'] AS family,e['given'] AS given,e['style'] AS style
FROM (SELECT b.package_id,unnest(t.entries) AS e FROM bodies b JOIN selected_transcript_headings t ON t.record_sha=b.sha256
 WHERE t.status='completed')
