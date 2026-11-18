---
id: ct-k7j4
status: open
deps: []
links: []
created: 2026-11-18T14:39:04Z
type: bug
priority: 2
assignee: mikewolfd
tags: [model, recordings]
---
# Senate page matcher has the same one-address-per-date weakness

Follow-up to ct-mwod, named by both independent analyses on 2026-11-18 (Codex gpt-6.2-astra with greybeard and etl-workflow; an Opus review). The House rule dropped a correct video-to-meeting match when the same page was stored from a second address. The Senate rules compare literal addresses the same way in three places: model/sql/senate-page-candidates.sql:129-130 (single_url_on_date), model/sql/senate-page-meeting-links.sql:39 (the fallback that needs it) and :72 (the tie rule between pages competing for one event). model/sql/appearance-observations.sql:140 reads those links for Senate witness attribution, so a dropped link there can move witnesses, not only recordings.

No Senate match is known to have been dropped; this is exposure, not an observed loss. Senate hosts carry no party prefix, so the alias forms to look for are www against bare host, http against https, a trailing slash, and query-order or tracking parameters.

First measure: in the live release's sources and url_state, count Senate committee pages held under more than one address with the same path and query. Fix only if the count is not zero, with the same shape as ct-mwod (count pages, not addresses) and a test that adds a mirror to an existing match and keeps its key.

## Acceptance Criteria

The count is recorded here; if not zero, the Senate rules count pages and a test covers a mirrored address.

