# docs.house.gov meeting XML: fetch route and what it adds over the Congress.gov API

Exploratory analysis, 2026-09-27. Question: can the committee-meeting XML at
docs.house.gov be fetched systematically from API metadata alone, and does it
add anything over the Congress.gov API records already mirrored in
`pipeline-data/congress_meetings.jsonl.gz`?

## TL;DR

- Yes, the XML is fetchable at scale by URL construction from API fields — no
  postback needed. docs.house.gov rate-limits aggressively, so pace it.
- The XML's document list is a **strict superset** of the API's
  `meetingDocuments` (0 exceptions in 739 meetings compared). The files the API
  drops are witness lists, member statements, member rosters, vote records,
  committee reports, and bill texts.
- Transcripts and witness names are already covered by the API
  (`hearingTranscript`, `witnesses`, `witnessDocuments`) — no gain there.
- Witness *panel structure* exists only in the ByEvent.aspx HTML.

## Fetch routes

### The postback (works for old events, fragile)

The "Download Meeting XML (.xml)" link is an ASP.NET `__doPostBack`, not a
href. Replay requires the page's hidden fields:

```bash
URL="https://docs.house.gov/Committee/Calendar/ByEvent.aspx?EventID=100269"
curl -s -c jar.txt "$URL" -o page.html
# extract all <input type="hidden"> name/value pairs, then:
curl -s -b jar.txt -X POST "$URL" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data "__EVENTTARGET=ctl00$MainContent$LinkButtonDownloadMtgXML&__EVENTARGUMENT=&<hidden fields>" \
  -o HMTG-113-AG00-20130213.xml
```

A bare `curl -X POST` with no body gets HTTP 411 (missing `Content-Length`).
On 2026-era events the replayed postback re-rendered the page instead of
returning the attachment — do not rely on this route.

### The predictable URL (reliable)

XML files live at a path built entirely from API fields:

```
https://docs.house.gov/meetings/{C}/{Cnn}/{YYYYMMDD}/{eventId}/{PREFIX}-{congress}-{Cnn}-{YYYYMMDD}.xml
```

- `{Cnn}` = committee code = `systemCode` minus the `hs` prefix, uppercased
  (`hsag00` → `AG00`, `hsii24` → `II24`); `{C}` = first two characters (`AG`).
- `{YYYYMMDD}` = the meeting's calendar date.
- `{PREFIX}` = `HHRG` for hearings, `HMTG` for other meetings. When the API
  record has ≥1 document whose URL contains an `HMTG-113-AG00-20130213-…`
  stem, read prefix/code/date from that stem directly — it never disagrees.
  For zero-doc meetings, guess from `type` (`Hearing` → `HHRG`, else `HMTG`)
  and fall back to the other prefix on 404.

Static files, plain GET, no cookies.

## Canonical EventID list

- **Congress.gov API** `/v3/committee-meeting/{congress}/house` lists every
  event with its `eventId`. The same endpoint serves the Senate
  (`/committee-meeting/{congress}/senate`, separate ID space, e.g. 336461 in
  the 118th = 1,135 events). The API also serves `format=xml` if XML
  serialization is wanted.
- The repo already mirrors both: `pipeline-data/congress_meetings.jsonl.gz`
  = 18,139 records, 112th–119th — 13,398 House (8,292 with `witnesses`),
  4,575 Senate (1,674 with `meetingDocuments`, **zero** with witnesses — the
  API never carries Senate witnesses), 166 NoChamber.
- Fallback: `ByDay.aspx?DayID=MMDDYYYY` works for any date back to 2011; a
  date walk re-derives all House IDs. (The month view ignores query params —
  it is postback-only.)

## The Senate has no docs.house.gov equivalent

- No central Senate event repository or per-event XML exists. senate.gov has
  no hearings XML feed (candidate URLs are Akamai-walled soft-404s), and
  event-time documents live on ~20 committee sites in six layouts — which is
  what `senate-meeting-records` scrapes. That scraper is the only route to
  Senate witnesses at event time.
- The only structured Senate witness XML is post-hoc: GPO govinfo's CHRG
  collection (published S.Hrg. prints). MODS per package carries
  `<name type="witness">Name, position, organization</name>` plus committee
  and dateIssued, at `www.govinfo.gov/metadata/pkg/{id}/mods.xml` (no key
  needed). `congress_api.gpo.fetch.mods_witnesses()` already parses it.
  Publication lags the hearing by 1–3 years and many hearings are never
  printed.

Validated against four independent sources (2026-09-27):

- `docs.house.gov/committee/Help.aspx` — the repository exists "in accordance
  with the rules of the House of Representatives and standards adopted by the
  Committee on House Administration"; its scope is House floor text and House
  committee meeting documents. A House-rule institution with no Senate
  counterpart.
- Georgetown Law Library, Legislative History Research Guide (updated
  2026-08-25) — committee transcripts are "some of the most elusive
  Congressional documents"; for Senate materials it directs researchers to
  individual committee websites, and names docs.house.gov only for House
  miscellaneous documents. A librarian guide would name a Senate equivalent
  if one existed.
- govinfo CHRG help (GPO) — "To find hearings not available on GovInfo, try
  visiting the committee's website"; "Whether or not a hearing is
  disseminated on GovInfo depends on the committee"; hearings "can be
  published two months to two years after they are held."
- senate.gov's central Committee Hearing/Meeting Schedule page — schedule
  only (times, rooms, nomination hearings); no documents, no feeds.
- The Library of Congress itself: congress.gov *is* the LoC (the API already
  mirrored). The Law Library's own guidance for finding hearing materials
  (`guides.loc.gov/legislative-history/unpublished-congressional-hearings`,
  updated 2026-08-05) lists as its free resources: Congress.gov committee
  landing pages (which link out to committee websites), C-SPAN, and the House
  Committee Repository (docs.house.gov) — it names no Senate repository,
  because their librarians know of none. The Law Library's 75,000 printed
  hearing volumes are historical physical stock (a Google digitization pilot
  put up a few topical PDF groups); for old unpublished Senate hearings their
  pointer is NARA's Center for Legislative Archives (20-year closure), or
  subscription ProQuest/CIS (coverage to 1824).

## At-scale comparison (739 meetings, stratified sample across 112th–116th+)

XML document set vs the API record's `meetingDocuments`:

| Measure | Result |
|---|---|
| Meetings where API had a file the XML lacked | 0 / 739 |
| Meetings where XML had files the API lacked | 80 (10.8%), 459 files |
| Meetings with docs version/update > 1 | 33.7% |
| Meetings with multi-date publish history | 92.3% |
| Documents removed after publish (`remove-date`) | 0 — dead field in practice |
| `<notes>` free-text element | 50 meetings (6.8%) |
| Structured witness section in XML | never |

Files the API's `meetingDocuments` omits, by category:

| Category | Files | Notes |
|---|---|---|
| Bill texts | 143 | includes XML-format bills (`h1549_ih.xml`) |
| Other SD docs | 116 | mostly legacy `.doc`/`.docx` |
| Member statements | 54 | bioguide ID in filename (`MState-D000600`) |
| Committee reports | 25 | `CRPT-*` |
| Transcripts | 19 | **all** already in API `hearingTranscript` |
| Witness lists | 18 | **not** in API `witnessDocuments` (that field carries only Bio/TTF/Wstate) |
| Member rosters | 9 | `MbrRoster` |
| Vote records | 4 | PNG |

## Operational notes

- docs.house.gov 403-bans after ~250 rapid requests. Working settings: 2
  workers, ~0.4s spacing, pause 45s on a 403. Full 18k corpus ≈ 3–4 hours at
  that pace.
- The DEMO_KEY rate limit on api.congress.gov is per-IP; routing through Zyte
  (token supplied as `ZYTE_TOKEN`, shared with `as_run/web.py`) sidesteps it.
- Congress.gov API detail adds `videos[]` and `relatedItems.bills[]` that the
  XML does not have.

## Production follow-up

`house-meeting-records` now reads both the meeting XML and the separate witness-list XML, with a page fallback. The later 5,594-page audit found the same 15,012 witnesses in XML and HTML, including panel structure. This early probe examined the meeting XML alone; its former claim that witness panels were HTML-only was superseded by that audit. See [the current findings](../findings.md#what-each-meeting-has-on-the-record).

The XML also supplies amendment attribution (`bioguideID`, `amdt-num`, `enbloc-num`) and update markers. Those parsed results are now retained in compact pipeline state, while the original probe artifacts below remain research evidence.

## Artifacts

Scratch dir (not in the repo): `/var/folders/g8/10vdwk2n07z85vqn_vlv2lfc0000gn/T/opencode/xmlscale/`

- `cache/{eventId}.xml` — 739 fetched XMLs (empty file = 404 on both prefixes)
- `rows.json` — per-meeting diff records
- `sample.json` — the 1,514-meeting stratified sample; 117th–119th underfetched
  (retry was cut short), resumable by re-running against the cache
