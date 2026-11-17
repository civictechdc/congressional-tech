---
id: ct-1qr7
status: closed
deps: []
links: []
created: 2026-11-17T18:18:49Z
type: task
priority: 2
assignee: mikewolfd
tags: [capture, queue]
---
# Do not fetch again an address that is already saved under another spelling

Root cause 6 of the 2026-11-17 RCA. The fetch queue held https://transportation.house.gov/calendar/EventSingle.aspx?EventID=409450 beside the saved eventsingle.aspx form; the capture fetched the page again, its bytes differed only in a news sidebar, and its link key changed. The recapture proof handles the symptom; the queue should not ask for it.

## Acceptance Criteria

A queued address whose normalized form is already saved is not fetched as new. Measured before and after on a published release: how many queued addresses were duplicates of saved ones.

## Notes

**2026-11-17: closed with no code change; the premise was wrong**

Measured on releases 95f4e73e859d and 2ec7ae83a852 (scripts and outputs in `.cache/archive-release/investigations/saved-address-requeue-20261117/`):

- Queued addresses (`attempts=0`) that share a `url_key` with a saved or fetched address: **0** of 39,811 and **0** of 44,583. The queue and documents both key by `url_key` (`model/sql/url-normalized.sql`, `url-keys.sql`; the capture gets the same SQL in `capture_profile.json`). The root-cause analysis said the queue keys by requested address; it does not.
- The only near-duplicates differ in path letter case (`EventSingle.aspx` beside a saved `eventsingle.aspx`): 1 on 95f4 (transportation.house.gov), 26 on 2ec7 (edworkforce 16, democrats-financialservices 10). Trailing slash, query order, scheme, host case, `www.`, fragment, encoding: 0 each. Counted two ways that agree: a deliberately broad fold that lowercases everything, and the capture's own key steps run in the pinned engine over every queued address.
- Keeping path case is a decision (data model 7.2; design review 2026-10-24), and the data backs it: `www.congress.gov/.../BILLS-116HR4299ih.pdf` (67,113 bytes) and `.../BILLS-116hr4299ih.pdf` (230,259 bytes) are different files.
- Size of the effect on 2026-11-17: 1 of 1,775 fetches went to a page already saved under another spelling. The site redirects mixed case to lower case, which is only visible after the fetch (the receipt's `requested_url` against `url`).

Why nothing changes: folding case before the fetch would be a second definition of an address and would lose real files; a case rule in `url-rules.json` is in the model definition, would move every House key with capitals and stop a night for a record; and the gate side is already handled, because the recapture proof (pull request 187) passes a page captured again at its own address under an unchanged title.

Left as is, on purpose: once a case variant has been fetched, both spellings keep their own recheck schedule (324 pairs on 2ec7, 324 extra scheduled rows of 1.17 million). If that ever matters, the designed path is a provenance `url_variants` record or a model rule that stops rechecking a row whose last fetch redirected to another row's address; either needs a cause record.
