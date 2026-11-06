-- Reviewed identity applies only to the selected exact PDF, with an observed
-- source locator for those same bytes. A mention or another rendition cannot
-- adjudicate this document. This small result is reused by selection and checks.
-- Withholding remains in force even if a package address arrives later: a new
-- independently established edition requires revising the reviewed decision.
SELECT DISTINCT chosen.component,e.id,e.pdf_sha,e.source_urls,e.rejected_package_ids,
 e.excluded_measure_keys,e.supported_measure_keys,e.evidence,true AS package_withheld
FROM bill_package_evidence e
JOIN saved_files anchor ON e.pdf_sha=anchor.body_sha AND anchor.format='pdf'
JOIN saved_files chosen ON chosen.component=anchor.component AND chosen.body_sha=anchor.body_sha
 AND chosen.saved_rank=1 AND chosen.format='pdf'
WHERE e.package_disposition='withhold' AND array_has(e.source_urls,anchor.source_url)
