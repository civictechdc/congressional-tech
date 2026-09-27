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
  event with its `eventId` (House only; the Senate has no equivalent). The API
  also serves `format=xml` if XML serialization is wanted.
- The repo already mirrors all of it: `pipeline-data/congress_meetings.jsonl.gz`
  = 18,139 records, 112th–119th, including `witnesses` (8,293 records) and
  `witnessDocuments` (7,831).
- Fallback: `ByDay.aspx?DayID=MMDDYYYY` works for any date back to 2011; a
  date walk re-derives all IDs. (The month view ignores query params — it is
  postback-only.)

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
  (token in `~/Work/spicy-stack/RefSpec/.env`, same pattern as
  `as_run/web.py`) sidesteps it.
- Congress.gov API detail adds `videos[]` and `relatedItems.bills[]` that the
  XML does not have.

## Implications for this pipeline

- `house_event_pages.py` scrapes the ByEvent HTML for document links and
  witness panels. The XML route would replace the document-link half of that
  (witness lists, member statements, rosters, votes — the classes it
  regex-hunts) with structured data, but the witness-panel structure
  (`witPanelHeader`) remains HTML-only.
- ~9k meetings had witness info in HTML that the API record lacked; that gap
  is only partially closed by the XML (witness-list PDFs yes, panel structure
  no) — verify against the jsonl before retiring the HTML scraper.
- The XML's other unique value is provenance (version/update history, publish
  dates) and amendment attribution (`bioguideID`, `amdt-num`, `enbloc-num`),
  which is rare (2/739 meetings here) because most amendments flow through
  `BILLS-*` files instead of `CA` documents.

## Artifacts

Scratch dir (not in the repo): `/var/folders/g8/10vdwk2n07z85vqn_vlv2lfc0000gn/T/opencode/xmlscale/`

- `cache/{eventId}.xml` — 739 fetched XMLs (empty file = 404 on both prefixes)
- `rows.json` — per-meeting diff records
- `sample.json` — the 1,514-meeting stratified sample; 117th–119th underfetched
  (retry was cut short), resumable by re-running against the cache
