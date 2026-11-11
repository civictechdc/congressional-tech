-- DM 7.5, ct-egoo (owner, 2026-11-11: keep the hearing number). The title a landing page states for the
-- document named for it, when it prints the hearing's official number: page signals kind landing_title,
-- group 1 of a GovInfo Content Details page's title ("S. Hrg. 111-774 - EXAMINING THE CAUSES ..."; the
-- package's MODS states the number as preferredCitation, which the model does not read). A page that
-- prints only GovInfo's "House Hearing, 111th Congress" label states none. Of a document's pages, the
-- package page before its same-named granule page. The normalized step lets it fill a title that is
-- empty or starts "- ", GovInfo's text title with the number left out.
SELECT component,title FROM (
 SELECT p.component,(regexp_match(a.reading_title,t.pattern))[1] AS title,
  row_number() OVER(PARTITION BY p.component ORDER BY p.page_url) AS pick
 FROM landing_page_picks p JOIN source_annotations a ON a.source_id=p.source_id
 JOIN (SELECT pattern FROM page_signals WHERE kind='landing_title') t ON regexp_like(a.reading_title,t.pattern)
 WHERE p.component IS NOT NULL
) WHERE pick=1
