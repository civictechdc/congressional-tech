# Congressional Document Archive: Phase-2 Annex

**Note, 2026-10-28.** What phase 2 adds: hearings, witnesses, recordings and the spicy-regs entities. Its rules were moved here unchanged from [[DATA-MODEL]] (§1–3, formerly DM §6.4, §6.5, §6.7, §7.11 and the entity rows of §8.1) and [[IMPLEMENTATION-PLAN]] (§4), so phase 1 can be built without reading them. §1–3 are normative as [[DATA-MODEL]] §2 says, from phase 2 on.

**Accepted review corrections, 2026-10-30.** §1–3 now specify context-free
appearance readings, explicit collection state and source-occurrence identity.
These are target rules awaiting implementation and versioned schema migration,
not descriptions of the currently published witness data. §4.7 maps all five
blind-review findings to existing or focused follow-up tickets and required checks.

## 1. Lake and Reference Inputs

### 1.1 Reference Inputs

Committees, members, terms, current rosters, bills, CBO estimates, floor votes and nominations come from spicy-regs, which owns their raw records and provenance. They are not lake tables: each publish pins each family's current immutable generation as spicy-regs' index `data.spicygov.ai/publication.v2.json` names it (the older `publication.json` names pruned generations), and the model reads the files that index lists for each table, `generations/<family>/<digest>/<table>.parquet`.

| spicy-regs table | Columns the model reads | Gives |
|---|---|---|
| `committees` | `system_code`, `chamber`, `name`, `committee_type`, `parent_system_code`, `history` (official names with start and end dates), `website_url`, `is_current` | Every committee and subcommittee of every Congress, named for any date |
| `members` | `bioguide_id`, `name_first`, `name_last`, `lis_id`, `fec_ids`, `opensecrets_id`, `govtrack_id`, `icpsr_id`, `wikidata_id` | Every member since 1789, with identifiers in other datasets |
| `member_terms` | `bioguide_id`, `term_type`, `term_state`, `term_district`, `term_party`, `term_start`, `term_end` | Every term |
| `committee_assignments` | `congress`, `system_code`, `bioguide_id`, `position`, `rank`, `party` | Current-Congress seats from the House Clerk's and the Senate's files |
| `congress_bills` | `bill_id`, `title`, `short_title`, `sponsor_bioguide_id`, `introduced_date`, `latest_action_date`, `latest_action_text`, `stage`, `policy_area` | 422,011 measures from the 6th Congress, keyed by `bill_id`, an opaque string: `{congress}-{type}-{number}` with the type lowercase, as `measure_keys` writes it |
| `bill_committees` | `bill_id`, `system_code` | The committees each bill was referred to: 286,721 rows over 167,162 bills of the 108th–119th Congresses |
| `amendments` | `amendment_id`, `purpose`, `sponsor_bioguide_id`, `latest_action_date`, `latest_action_text`, `amended_bill_id`, `amended_amendment_id` (all strings) | Amendments to a bill or to another amendment; the 119th Congress only until spicy-regs backfills |
| `bill_committee_activities` | `bill_id`, `system_code`, `activity_name`, `activity_date` (a UTC instant), `occurrence` | What each committee did on a bill and when (referred, hearings, markup, reported), as BILLSTATUS lists it; filling Congress by Congress |
| `cbo_cost_estimates` | `bill_id`, `publication_id`, `pub_date`, `description` | CBO cost estimates from the 108th Congress, 913–1,666 a Congress |
| `roll_call_votes` | `vote_id`, `chamber`, `vote_day`, `question`, `result`, `yea`, `nay`, `bill_id`, `documents` | Floor roll-call votes, House from the 101st Congress and Senate from the 108th, keyed `{congress}-{chamber}-{session}-{roll_number}`; a Senate vote's `documents` entry with `type = 'PN'` names a nomination by `number` `{number}[-{part}]`, in the vote's own Congress when the entry's is null |
| `bill_vote_references` | `bill_id`, `congress`, `chamber`, `session`, `roll_number` | Floor votes a bill's actions name, joined to `roll_call_votes` by building that `vote_id` (19,766 of 19,766) |
| `nominations` | `citation`, `congress`, `description`, `organization`, `received_date`, `latest_action_date`, `latest_action_text`, `committees_json` (committee codes and activities), `hearings_json` (printed hearings by jacket) | Nominations; the 119th Congress only until spicy-regs backfills |

A change in these columns fails the model at its next publish rather than reading wrong values; the model SQL moves with the generation. Spicy-regs keeps each family's last three generations and every generation a consumer pins; the archive pins those of every release it keeps ([[ARCHITECTURE]] §10.3.7).

### 1.2 `meeting_records`

One row per input and parser version: a Congress.gov meeting record, inline in a receipt line or a response body, or a House `committee-meeting` XML record, with the meetings it gives in `meetings`.

| Column | Type | Notes |
|---|---|---|
| `record_sha` | fixed[32] | The body's SHA-256, or an inline record's `record_sha` ([[DATA-MODEL]] §6.1). |
| `parser_version` | string | — |
| `status`, `error_type` | string | [[DATA-MODEL]] §6. |
| `source` | string | `congress_gov` or `house_xml`. |
| `meetings` | list<struct> | One element per meeting the input gives, usually one; empty when it gives none. Fields below. |

Each `meetings` element (the types below are the meanings; the lake struct stores `event_id`, `updated`, `meeting_date` and each sitting's `start` and `end` as the source's literal strings, and the model casts them, as in `meeting-records-current.sql`; each `committees` element also keeps the source's `name` and `chamber`):

| Field | Type | Notes |
|---|---|---|
| `event_id` | long | The meeting key ([[DATA-MODEL]] §3). A House XML `meeting-id` drops its four-letter prefix (HHRG, HMKP, HMTG). |
| `chamber` | string, nullable | [[DATA-MODEL]] §3. |
| `congress` | int, nullable | — |
| `session` | int, nullable | The Congress's session. |
| `updated` | timestamptz, nullable | Congress.gov's `updateDate`. |
| `title` | string, nullable | — |
| `meeting_date` | date, nullable | — |
| `meeting_type` | string, nullable | Hearing, markup, meeting, … |
| `status` | string, nullable | As the source states it: scheduled, postponed, cancelled, rescheduled, … |
| `sittings` | list<struct<start timestamptz, end timestamptz, room string, building string, address string>> | Each sitting with its place; most meetings have one. |
| `committees` | list<struct<system_code string, role string>> | Congress.gov system codes; `role` is host, joint or the source's own word. |
| `subject_keys` | list<string> | What the meeting covers: bills as `measure_keys` writes them, nominations as `nomination_id` (§2, from a zero-padded `part`), treaties `{congress}-treaty-{number}`. |
| `transcript_jackets` | list<long> | GPO jacket numbers of the printed hearing, from `hearingTranscript[].jacketNumber` (§2). |
| `videos` | list<struct<name string, url string, video_key string>> | Recording links the source gives. `video_key` is `youtube:{id}` for a YouTube watch link and `senate:{filename}` for a senate.gov player link, else null; the recordings are not captured. |

- **Sources:** Congress.gov meeting records for both chambers (18,140 meetings, about 11 identical inline copies each, which `record_sha` collapses) and House `committee-meeting` XML. Senate committee pages carry no meeting ID; they give documents and appearances (§1.3).
- **Work list:** good-fetched bodies and inline records whose URL matches the meeting-source registry ([[DATA-MODEL]] §7.1) with no row at the pinned version. Inline records are read once from the four `congress/meetings` receipt files (77 MB, 199,156 lines) by their `captures` pointers, and `record_sha` is computed then.
- **PK:** `(record_sha, source, parser_version)`, since parser versions are source-scoped (ct-h1nd); tens of thousands of rows. The model unnests `meetings`.
- **Current records:** first filter the selected source/parser versions; then, per `(event_id, source)`, choose the latest by `(updated desc nulls last, latest good fetch's retrieved_at desc nulls last, record_sha)`. Each replacement field comes from the current `house_xml` record when that explicitly states it, else its current `congress_gov` record. Replacement collections carry `present`, `empty`, `absent` or `unrecognized` state: an explicitly empty higher-precedence list replaces the old list and is not filled from another source. Only an absent declaration permits normal fallback; failed or unrecognized extraction remains an explicit coverage problem. **Sittings differ:** `sittings` come from the current `congress_gov` record when it states any, else from `house_xml`, whose times convert from Eastern local to an instant. Congress.gov states instants and places; House XML states unzoned local times and its parsed sittings carry no place. An explicit `empty` or `unrecognized` House state still replaces the list without fallback. Fields deliberately combining assertions, such as `subject_keys` under `ct-h1nd`, keep their separately stated union policy and provenance.

### 1.3 `appearance_records`

One row per input body/inline record, source kind and selected parser version,
with source occurrences in `appearances`. Parsing reads body facts once; it does
not select a capture URL or resolve relative links. The model binds each eligible
source context afterward, using the same principle as page-link resolution.
An appearance is a source observation, not a person identified by normalized name.

| Column | Type | Notes |
|---|---|---|
| `record_sha` | fixed[32] | The body's SHA-256, or an inline record's ([[DATA-MODEL]] §6.1). |
| `parser_version` | string | — |
| `status`, `error_type` | string | [[DATA-MODEL]] §6. |
| `source` | string | `house_xml`, `congress_gov`, `senate_page` or `mods`. |
| `event_id`, `package_id` | long nullable, string nullable | Subject identifiers stated in the input, outside the list so an empty observation retains its subject. Identifiers derivable only from a URL are assigned in the contextual model step. |
| `declared_base` | string, nullable | Literal base address declared by the body, if any; resolve it per source context, never against an arbitrary selected capture URL. |
| `collection_state` | string, nullable | `present` for a recognized nonempty collection; `empty` for a recognized explicit zero; `absent` when the supported input makes no collection declaration; `unrecognized` when its collection layout cannot be interpreted. Failed reads retain their `status`/`error_type`, not an invented empty list. |
| `appearances` | list<struct> | One element per source occurrence in source order, including repeated names. Empty lists do not erase subject identity or collection state. Fields below. |
| `held_dates`, `title` | list<string> nullable, string nullable | For a MODS record: its `heldDate` values and title, which decide whether a print records a meeting ([[DATA-MODEL]] §7.11 Packages). |
| `created` | string, nullable | For a House witness list: its `create-date`, so an empty list made before its hearing reads as a placeholder, not as no one testifying. |

Each `appearances` element:

| Field | Type | Notes |
|---|---|---|
| `source_locator` | string | A deterministic locator of this occurrence in the retained input: a publisher-supplied occurrence ID where unique, otherwise a source-node selector under a versioned locator rule. It is not the entry's position in a filtered output list or a normalized name. |
| `name_key` | string, nullable | The recorded name, NFKC, casefolded, punctuation dropped, whitespace collapsed; null when unnamed. A grouping/diagnostic attribute, never sufficient evidence to merge two observations. |
| `name` | string, nullable | As recorded. |
| `honorific`, `given`, `middle`, `family`, `suffix` | string, nullable | When the source splits the name (House XML). |
| `position`, `organization`, `on_behalf_of`, `location` | string, nullable | As recorded. |
| `panel` | string, nullable | The panel's label. |
| `panel_order`, `display_order` | int, nullable | Source order. |
| `witness_type` | string, nullable | As recorded. |
| `testified` | boolean, nullable | Whether the source marks the witness as having testified. |
| `bioguide_id` | string, nullable | Given by the source for a member witness; never inferred. |
| `document_links` | list<string> | The witness occurrence's literal document links, including relative addresses. The model resolves these into `document_urls` against each eligible source context and declared base using DATA-MODEL §7.2. Missing context remains unresolved, not guessed. Empty where the source supplies no links. |

- **Sources:**
  - House `witness-list` XML, beside the meeting's `committee-meeting` record: split names, panels, witness documents and member bioguide IDs;
  - Congress.gov meeting records: name, position and organization; they list no Senate witnesses (0 of 4,575 Senate events);
  - Senate committee hearing pages, whose layout puts each witness's links inside that witness's card: 90.7% of senate.gov testimony files;
  - GovInfo MODS records already in raw, which list a printed hearing's witnesses for both chambers, at granule level too.
- **Work list:** eligible witness lists, Congress.gov records, MODS records and Senate hearing pages matching the meeting-source registry, for every applicable source kind with no reading or valid unreadable disposition at its selected version. Reuse body parsing across capture addresses; do not choose one source or URL by `max()` when several contexts exist.
- **PK:** `(record_sha, source, parser_version)`. The row remains even with no appearances. Source classification and parser identity are inputs to reuse; neither may be lost in a body-only anti-join.
- **Context binding:** the model joins readings to every eligible capture/inline context, assigns URL-derived subject facts and `page_url`, and resolves literal links. `context_key` is the lowercase hex SHA-256 of compact JSON `[source_url, member_path]` for that context (null members retained); the referenced input and raw locator remain available. Repeated captures of the same body at the same context reuse one observation. A new context adds observations without re-parsing unchanged bytes. Current-record ordering uses retrieval evidence for that subject/context; a later capture of the same body elsewhere must not refresh an older observation at this address.
- **Replacement:** choose the current record for each source/subject/context before unnesting. A current explicit empty list suppresses that source's older list. An absent declaration may use the documented lower-precedence source; unrecognized/failed extraction produces an explicit unresolved state, not silent stale fallback. Preserve candidates and reasons in evidence even when they are not selected for display.

### 1.4 `video_records`

One row per body, source and parser version: a retained YouTube channel cache (`source = youtube_cache`, the newest good fetch of each `pipeline-data` `youtube/youtube_<n>.json`) or a retained YouTube Data API `videoListResponse` body (`youtube_api`). Upstream API JSON stays in the body, which `record_sha` references (about 231 MB of 267 MB); it is evidence, not a queryable fact.

| Column | Type | Notes |
|---|---|---|
| `record_sha`, `parser_version`, `source`, `status`, `error_type` | — | As §1.2. |
| `channels` | list<struct<handle, channel_id, title, custom_url string; uploads_scan_complete bool>> | The cache's channel rows. |
| `videos` | list<struct<handle, video_id, channel_id, channel_title, title, description, published_at, video_published_at string; duration_seconds int; available, has_caption bool; details_checked_at string; stated_event_ids list<long>>> | One per upload; `stated_event_ids` are event IDs the video's own text names, which are claims, since committees mistag. Times are the source's literal strings. |

- **PK:** `(record_sha, source, parser_version)`. **Work list:** `youtube-cache-bodies.sql` and `youtube-api-bodies.sql` candidates with no row at the pinned version.
- **Release:** `videos.parquet`, and with the curated channel directory (`youtube-accounts.csv`, the one authority `youtube-fetch` also reads) `channels.parquet`; with meeting records and provenance `recording_decisions`, `recording_matches.parquet` (§3).

### 1.5 `committee_records`

One row per House `committee-meeting` XML body and parser version: the amendment and committee-vote document links the record lists, as the publisher lists them, never ballots or tallies.

| Column | Type | Notes |
|---|---|---|
| `record_sha`, `parser_version`, `source` (`house_xml`), `status`, `error_type` | — | As §1.2. |
| `event_id`, `updated` | string, nullable | The record's meeting ID (prefix dropped) and update date, literally. |
| `records` | list<struct<ordinal int; kind string (amendment or vote); bill, number, sponsor_bioguide, amendment_type, enbloc, description, url string>> | In record order; `ordinal` keeps duplicate links distinct. |

- **PK:** `(record_sha, source, parser_version)`. **Work list:** good-fetched House meeting XML with no row at the pinned version.
- **Release:** `committee_records.parquet` (§3).

## 2. Hearings, Witnesses and Reference Entities

Hearings, witnesses, members, committees, bills and nominations are the entities a reader explores beside documents: a hearing's transcript, recording and witnesses and what each submitted, a member's committees and hearings, a bill's committees, cost and votes, a nomination's hearings and votes. Every relationship is one a publisher states; none is matched by name.

```
transcripts    := per meeting, every transcript the archive holds, each labelled by source
                  (ct-1i4q), as (source, package_id, list_row, formats, video_key, language, production):
                  printed_hearing: one entry per package whose package_id parses as
                    CHRG-{c}{h|s|j}hrg{digits}, linked by a transcript jacket (int({digits}),
                    {c} the meeting's congress, the chamber's letter when it has one; jackets
                    match as integers: 49104057 is CHRG-118shrg049104057) or by the print's own
                    MODS eventId, and only when the print records the meeting (DATA-MODEL 7.11:
                    held that day, the same witnesses or an agreeing title); a package with no
                    MODS keeps its jacket link; list_row is the package's listed document whose
                    saved format ranks first, then lowest row, and formats are the distinct saved
                    and alternate formats of its listed documents in preference order (invariant
                    duplicate_transcript_packages = 0)
                  committee_transcript: a listed document linked to the meeting whose filename is
                    H{HRG|MKP|MTG}-{congress}-{committee}-Transcript-{yyyymmdd}[-{part}].pdf
                    with {yyyymmdd} the meeting's date (the committee's own transcript)
                  captions: a retained complete caption body (vtt, srt, ttml) or subtitle media
                    playlist (m3u8) with a body, of a
                    recording linked to the meeting; a vtt beside a playlist of the same
                    production is a stream segment, never a track (ct-9s7b)
                  Transcript coverage is present when any source is held, and its reason names
                  the sources; unresolved and unknown keep their meanings
occasion       := 'meeting:{event_id}' for a House witness list or Congress.gov record;
                  for a MODS appearance, the meeting whose transcripts hold its package
                  when exactly one does, else 'package:{package_id}'; for a Senate page
                  that lists witnesses and states or links to a meeting,
                  'meeting:{event_id}', else 'page:' and the hex of the first 8 bytes
                  of sha256(url_key(page_url))
witness_key    := the lowercase hex of the first 8 bytes of the SHA-256 of compact JSON
                  ["witness-occurrence-v2", occasion, source, record_sha_hex,
                   source_locator, context_key]; an observation key, not a person key
witnesses      := filter pinned source/parser versions; select each source's current
                  subject/context observation in §1.2 order before unnesting; apply
                  House, Congress.gov, then MODS precedence to explicit collection
                  states (a page is its own occasion); retain every selected occurrence
witness_keys   := per document, the witness_key of every appearance one of whose
                  document_urls matches one of its document members (DATA-MODEL §7.2
                  matching); a printed hearing's witnesses are the transcript's, through
                  its package_id, never documents they submitted
members        := per bioguide_id, the pinned members row, named "{name_first}
                  {name_last}", and its member_terms, latest first, term_type mapped
                  (DATA-MODEL §3)
rosters        := the pinned committee_assignments, rank as an integer when it is one:
                  current-Congress seats only, because spicy-regs keeps no roster history
committees     := the pinned committees, each with its official names from history as
                  half-open date intervals (DATA-MODEL §4), latest start first, then name
                  bytewise; a label for a date is the first name whose interval holds it,
                  else the current name
bills          := the pinned congress_bills row of every bill_id a listed document's
                  measure_keys or a meeting's subject_keys names, with its committees of
                  referral (bill_committees), its CBO estimates, and its floor votes once
                  each: votes whose bill_id is it (basis vote_record), then votes its
                  actions name (bill_vote_references, basis bill_action); its amendments,
                  by amended_bill_id or through amended_amendment_id to the bill the
                  chain reaches; and its committee activities, dated by DATA-MODEL §4
recordings     := per video_key a meeting's videos names, the caption, subtitle and
                  playlist bodies whose URLs the recording-source registry ties to it,
                  one per (format, language, production), from its latest good fetch;
                  a streamed track's segment files are not tracks: a segment is a URI a
                  held playlist lists (`playlist_records`, resolved against each address
                  the playlist was fetched from), and a placeholder body is never a track
                  (native check `segment_tracks`, ct-9s7b); a playlist body is a
                  track; an empty body (the SHA-256 of empty input) is not a track, and a
                  native check refuses one (ct-fh62); an MP2T stream segment has role
                  media and is never a track
nomination_id  := '{congress}-pn-{number}', plus '-{int(part)}' unless the part is 0:
                  spicy-regs' citation form (PN730-2 is 119-pn-730-2)
nominations    := per nomination_id a meeting's subject_keys names, the pinned row whose
                  citation gives it, its referral committees, the packages its printed
                  hearings' jackets name (as transcripts parse them), and every Senate vote
                  whose documents name it, by (vote_day, vote_id)
```

- No person is matched across source occurrences by name. A later person-identity table may relate supported observations; its identity is separate from `witness_key`.
- Equal names with different panels, roles, organizations or documents remain distinct observations. Presentation may group demonstrably equivalent observations only while retaining all contributing keys, locators and evidence; uniqueness obtained by discarding unequal observations is not preservation.
- A name or role a later reading supplies, such as a structured transcript from captions, subtitles or `pdf_text`, is an attribute of the appearance and never part of `witness_key`, so links survive it.
- The v2 key is stable for the same retained input, locator and context; a changed source record is a new observation. This replaces the old name-derived identity rule. Keep old releases readable with their original keys and version the new release schema/relationship definitions. Any old-to-new mapping must preserve one-to-many and unresolved cases; never redirect an ambiguous old key to an arbitrary occurrence.
- The model reports appearances whose `name_key` differs only by a title or initial within one occasion, as input for that table, and Senate page cards with no links.
- Release 448651e7 changed every `witness_key`. Owner decision, 2026-11-02: no old-to-new mapping is published; the release notes say witness IDs changed and that old `?witness=` links no longer resolve (ct-ktfe).
- Live 448651e7 publishes a single VTT segment as the caption track of 773 Senate recordings (1,538 track rows; 667 recordings point at one 57-byte segment), against the segment rule above (ct-9s7b).

## 3. Entity Release Files

These files join [[DATA-MODEL]] §8.1's table, with its shared writer settings and profiles.

These definitions specify the target release, including the accepted witness
corrections awaiting implementation under §4.7. The migration requirements in
§4.6 identify additional retained facts to expose. Typed schema changes must land
with the native producer and release registry; this document does not claim the
currently published release already contains them.

`meetings.parquet` ([[DATA-MODEL]] §8.1) gains `congress`, `congress_gov_updated`,
`house_xml_updated`, `congress_gov_meeting_type`, `access`, `access_basis`, `not_held`,
`rescheduled_to` and `rescheduled_basis`, its `transcripts` carry their source, and each
sitting gains `room`, `building` and `address`. Publisher updates remain distinct from
hearing dates and capture times; `congress` is null when no record states it. Each
file's column meanings are in the release's `schema.json`, from the release-schema registry.

| File | Columns | Order | Writer settings | Size |
|---|---|---|---|---|
| `witnesses.parquet` | `witness_key` string (v2 source-occurrence identity), `occasion` dict, `source` dict, `record_sha` fsb(32), `source_locator`, `context_key` strings, `event_id` int64 nullable, `package_id` string nullable, `page_url` string nullable, `name` string nullable, `position`, `organization`, `on_behalf_of`, `location`, `panel` (strings, nullable), `panel_order`, `display_order` int16 nullable, `witness_type` dict nullable, `testified` bool nullable, `bioguide_id` dict nullable, `superseded_by` string nullable (the `witness_key` of the same person stated on the same meeting by a higher-ranked source, [[DATA-MODEL]] §7.11; null on the row to show) | `(occasion, panel_order, display_order, witness_key)` | Whole | Re-measure after occurrence preservation; historical few-MB estimate is not an acceptance bound |
| `recordings.parquet` | `video_key` string, `event_ids` List<int64>, `tracks` List<Struct<body fsb(32), suffix dict, format dict, language dict nullable, production dict nullable>> | `video_key` | Whole | *est.*, measured with S2 |
| `caption_resources.parquet` | `video_key` string, `track_body` fsb(32), `ordinal` int64, `source_url` string, `declared_uri` string nullable, `body` fsb(32) nullable, `suffix`, `format` dict nullable, `parser_version` string nullable, `status` dict | `(video_key, track_body, ordinal)` | Whole | Selected roots and declared children only; missing children remain rows |
| `committees.parquet` | `system_code` string, `name` string, `chamber` dict, `committee_type` dict nullable, `parent_system_code` dict nullable, `names` List<Struct<name string, start date32, end date32>>, `website` string nullable, `is_current` bool nullable | `system_code` | Whole | Under 1 MB |
| `members.parquet` | `bioguide_id` string, `name` string, `terms` List<Struct<chamber dict, state dict, district int16, party dict, start date32, end date32>>, latest first, `cross_ids` Struct<lis, opensecrets, govtrack, icpsr, wikidata string; fec List<string>> | `bioguide_id` | Whole | *est.* about 2 MB |
| `rosters.parquet` | `congress` int16, `system_code` dict, `bioguide_id` dict, `title` dict nullable, `rank` int16 nullable, `party` dict nullable | `(congress, system_code, rank, bioguide_id)` | Whole | Under 1 MB |
| `bills.parquet` | `bill_id` string, `title` string nullable, `short_title` string nullable, `sponsor_bioguide_id` dict nullable, `introduced`, `latest_action_date` date32 nullable, `latest_action_text` string nullable, `stage` dict nullable, `policy_area` dict nullable, `public_law_number` string nullable (when enacted), `cosponsor_count` int32 nullable, `related_bills` List<Struct<bill_id string, title string, relationship_types List<dict>>>, `committees` List<dict> (system codes), `cbo_estimates` List<Struct<publication_id string, date date32, description string>>, `floor_votes` List<Struct<vote_id string, basis dict, chamber dict, date date32, question string, result string, yea int16, nay int16>>, `amendments` List<Struct<amendment_id string, purpose string, sponsor_bioguide_id dict, latest_action_date date32, latest_action_text string>>, `committee_activities` List<Struct<system_code dict, activity dict, date date32>> | `bill_id` | Whole | *est.* a few MB |
| `nominations.parquet` | `nomination_id` string, `description` string nullable (military promotion lists have none upstream; ct-tk10 gate 4, 2026-11-02), `organization` string nullable, `received` date32 nullable, `latest_action_date` date32 nullable, `latest_action_text` string nullable (the outcome, such as a voice vote), `committees` List<dict>, `committee_activities` nullable List<Struct<system_code string, activities nullable List<Struct<name string, date string>>>> in source order, `transcripts` List<string> (package IDs), `floor_votes` List<Struct<vote_id string, date date32, question string, result string, yea int16, nay int16>> (cloture, then confirmation, as cast) | `nomination_id` | Whole | Under 1 MB |
| `videos.parquet` | `video_key` string (`youtube:{id}`), `handle` dict, `channel_id` string nullable, `system_code` dict nullable (the curated channel's committee; membership does not make a video a hearing), `title`, `source_description` strings nullable, `published_at`, `video_published_at` ts nullable, `duration_seconds` int32 nullable, `available`, `has_caption` bool nullable, `details_checked_at` ts nullable, `stated_event_ids` List<int64> (claims), `record_sha` fsb(32) (§1.4) | `video_key` | Whole | 8.6 MB (67,391 rows, e4538f00) |
| `channels.parquet` | `handle` string, `channel_id` string nullable, `system_code` dict, `committee_label` string, `role` dict (`primary`, `secondary`, `member`), `title`, `custom_url` strings nullable, `uploads_scan_complete` bool nullable, `mapping_basis` dict (`curated_directory`), `record_sha` fsb(32) nullable | `handle` | Whole | Under 1 MB |
| `recording_matches.parquet` | `match_id` string (hex SHA-256 of `[subject_kind, subject_id, video ref, basis]`), `subject_kind` dict (`event`, `package`), `subject_id` string, `event_id` int64 nullable, `package_id` string nullable, `video_key` string nullable, `url` string nullable, `basis` dict (`publisher_link`, `video_states_event_id`, `curated`), `decision` dict, `score` int16 nullable (100 publisher link, 95 stated event ID), `recording_scope` dict, `status` dict (`asserted`, `claimed`, `decided`, `conflicting`, `unresolved`), `note`, `source_ref` strings, `meeting_links` List<Struct<event_id int64, basis dict, scope dict>> | `match_id` | Whole | 2.2 MB |
| `committee_records.parquet` | `record_key` string (hex SHA-256 of `[record_sha hex, ordinal]`), `event_id` int64, `kind` dict (`amendment`, `vote`), `bill`, `number` strings nullable, `sponsor_bioguide` dict nullable, `amendment_type` dict nullable, `enbloc`, `source_description`, `url` strings nullable, `record_sha` fsb(32), `ordinal` int32 (§1.5) | `record_key` | Whole | 1.5 MB |
| `meeting_coverage.parquet` | `event_id` int64, `aspect` dict (`recording`, `transcript`, `documents`, `witnesses`, `captions`), `state` dict (ranked as [[DATA-MODEL]] §7.11 Coverage; states never merge), `basis` dict, `count` int32 nullable, `reason` dict nullable | `(event_id, aspect)` | Whole | Under 1 MB |

The `meetings.parquet` field `document_references` keeps Congress.gov's links in their original meeting or witness document collection, with a zero-based occurrence and the supplied role, format, description, and name. The publisher format describes the link. Readers can use the existing document address lookup to find a saved copy and its independently recorded format. A null list means the metadata is unavailable or unstated. An empty list means a supplied collection contained no links.

Recording associations use `direct_event` evidence for an event subject and `print_agreement` for a related package. `package_context` can link to several meetings without establishing presence or absence for any one sitting. An empty `meeting_links` list means no supported link. Earlier releases can omit the field and still carry their original observations.

## 4. Plan Items

### 4.1 Phase-2 Exit Checklist

Phase 2 is done when, beyond [[IMPLEMENTATION-PLAN]] §6.6's phase-1 checklist:
- the accepted review corrections and transition fixtures in §4.7 pass; prior shape/count/query checks do not substitute for their semantic checks;
- the PDF-copy job (B13) and full re-hash (B10) do not gate this exit (owner decisions, 2026-11-01 and 2026-11-04): both are post-switch work with no date, recorded on `cef-96wc`. When they run, a damaged PDF they find leaves the list in a following release;
- the actual production jobs use lake meeting/witness records and pinned SpicyRegs inputs, and all retained Explorer field families have the destinations and parity evidence required by §4.6 (`ct-gi01`, F3);
- site entity browsing and Congress MCP consume the shared release; `/dashboard/` is replaced/redirected or serves only Coverage/Gaps from that release (`ct-t915`, `ct-m104`);
- after the replacement is verified live, the separate Explorer publishing route and `pipeline-data/committee-explorer/public` staging are retired (`ct-5kto`) right after live acceptance, with no overlap period (owner decision, 2026-11-02); preservation and rollback references remain; old dashboard links that name a record by UUID show a removal notice, with no ID mapping;
- every publish passes the five gates (`ct-tk10`, owner decision 2026-11-02): a key-by-key comparison with the live release in which every difference has a recorded cause; the link rule, under which a published link key never vanishes: it redirects only to a document holding the same body or the same text fingerprint, and otherwise shows a removal notice listing the address's current versions; one end-to-end test from receipts to release; refusal at write of a missing required field; and a producer version on every input row;
- after the fixed release, the daily job publishes without a person only when every difference from the live release is an added row traced to receipts newer than it; any changed or removed value waits for a reviewed cause record (`ct-ud0b`). It runs on the owner's Mac on a schedule, not a hosted runner (owner decision, 2026-11-04), discovers new receipts in raw by family, and appends each night only the oldest receipts whose new bodies fit its readings budget;
- spicy-regs' retention plan keeps every generation a kept release pins (F4);
- the weekly meeting job is gone (removed 2026-11-04 by owner decision, without waiting for B14's first run; `ct-klyz`); the weekly GPO match and committee refresh read the last saved meeting inventory;
- C3's export is byte-identical across threads, batch sizes and a forced spill, so the profile no longer pins the runner class;
- the native relationship metadata and consumer checks in §4.4 pass. This is follow-through added on 2026-10-30 after the first phase 2 entity deployment.

### 4.2 Uncertainties

As in [[IMPLEMENTATION-PLAN]] §8, each row closes only with its measurement.

| Uncertainty | Settled by | Decides |
|---|---|---|
| Roster history: spicy-regs keeps the current Congress only | A spicy-regs change publishing its captured rosters as dated history | Rosters show current seats until then |
| How often one printed hearing covers several meetings, leaving its MODS witnesses on the package | **Settled by D4 full-corpus measurement:** among **10,723** `CHRG-*` packages linked to meetings in `meetings.parquet`, **6,917 (64.5%)** link to **1 meeting** (`meeting:{event_id}`) and **3,806 (35.5%)** link to **>1 meetings** (`package:{package_id}`); across all **34,559** parsed `CHRG-*` MODS records (**107,272** deduplicated appearances), **6,882** packages (**22,501** witnesses) resolve to 1 meeting, **3,796** packages (**12,162** witnesses) resolve to 2–15 meetings, and **23,881** packages (**72,609** witnesses, mostly pre-113th Congress) have 0 meeting records | Keep `'package:{package_id}'` when `count(event_id) != 1`; no per-day rule needed in Phase 2 |
| Senate card coverage by committee site (judiciary 98.6%, hsgac 64.8%, indian 54.8%, jec 0%) | **Settled by D4 full-corpus measurement** across **6,685** candidate `senate_page` captures (**5,030** non-empty pages, **17,687** witnesses, **16,496** card links) and **8,946** listed Senate testimony documents: **5,638 / 8,946 (63.0%)** match strictly under current `url_key`; stripping ColdFusion `[?&]download=1` suffixes on `banking`, `finance`, `appropriations`, `aging`, `budget` and `veterans` raises coverage to **8,096 / 8,946 (90.5%)** | Normalize `[?&]download=1` on ColdFusion `/download/` URLs; second page layouts only needed for `environment`, `intelligence` and `jec` |
| Event IDs never name two chambers (observed on 18,140, not promised by the publishers) | Invariant 15 at every publish (**0** multi-chamber `event_id`s across all **18,140** Congress.gov + **6,164** House XML `meeting_records`, **18,225** resolved meetings) | The meeting key, if one ever does |
| Nominations before the 119th Congress | spicy-stack ss-vhi2's backfill | How far back nomination pages reach |
| Repeated names, panels and source occurrences | **Historical lossy baseline:** first-name dedup dropped 534 MODS, 478 Congress.gov and 23 House XML occurrences; 138 / 28,392 occasions also had distinct name keys sharing surname/initial. These counts describe the old output, not proof of equivalent people or observations. | `ct-30fp` preserves occurrences and compares the changed rows/evidence; name-only uniqueness no longer establishes acceptance |

#### 4.2.1 D4 Measurement Details

The measurements below describe the earlier parser/name-deduplication model.
Retain them as a comparison baseline. Accepted §4.7 corrections can change row
counts and witness keys; zero duplicate name-derived keys is not proof of
preservation. No corrected full-corpus result is claimed here.

1. **Multi-meeting MODS packages (`meeting_records` = 24,304 rows; `appearance_records` = 62,782 rows including 34,559 `mods` rows):**
   - **Meeting count distribution across the 10,723 linked `CHRG-*` packages in `meetings.parquet`:** `1 meeting: 6,917 (64.5%)`, `2: 2,696 (25.1%)`, `3: 750 (7.0%)`, `4: 199 (1.9%)`, `5: 52`, `6: 48`, `7: 14`, `8: 19`, `9: 8`, `10: 5`, `11: 3`, `12: 1`, `13: 5`, `14: 5`, `15: 1` (total `>1 meetings`: **3,806 / 10,723 = 35.5%**).
   - **Examples of multi-meeting packages:** `CHRG-112hhrg64725` (`event_id`s `103896, 103897`), `CHRG-112hhrg72254` (`100083, 100180`), `CHRG-113hhrg78631` (`100222, 100223, 100225`), `CHRG-113hhrg79435` (`100220, 100221, 101129`).
   - **MODS witness assignment across all 34,559 parsed `CHRG-*` packages (22,498 with `>=1` witness; 107,272 deduplicated appearances):**
     - `1 meeting` (`occasion = 'meeting:{event_id}'`): **6,882** packages (**4,798** with witnesses, **22,501** appearances; **3,053** overridden by higher-precedence `house_xml` or `congress_gov`, **1,745** winning in `witnesses.parquet` with **6,213** witnesses).
     - `>1 meetings` (`occasion = 'package:{package_id}'`): **3,796** packages (**2,256** with witnesses, **12,162** appearances: `2 meetings: 2,690 pkgs / 9,255 witnesses`, `3 meetings: 747 pkgs / 2,397 witnesses`, `4 meetings: 199 pkgs / 417 witnesses`, `5–15 meetings: 160 pkgs / 93 witnesses`).
     - `0 meetings` (`occasion = 'package:{package_id}'`): **23,881** packages (**15,444** with witnesses, **72,609** appearances).

2. **Senate card coverage by committee site (6,685 candidate pages, 5,030 with cards, 8,946 listed Senate testimony documents):**

| Committee site | Candidate pages | Non-empty pages | Witnesses | Listed testimony docs | Strict `url_key` match | Match stripping `[?&]download=1` |
|---|---:|---:|---:|---:|---:|---:|
| `judiciary.senate.gov` | 645 | 602 | 2,424 | 2,265 | 2,235 (**98.7%**) | 2,235 (**98.7%**) |
| `commerce.senate.gov` | 482 | 463 | 1,688 | 1,039 | 1,014 (**97.6%**) | 1,014 (**97.6%**) |
| `banking.senate.gov` | 460 | 440 | 1,354 | 892 | 0 (**0.0%**) | 860 (**96.4%**) |
| `finance.senate.gov` | 405 | 350 | 1,210 | 826 | 0 (**0.0%**) | 804 (**97.3%**) |
| `appropriations.senate.gov` | 538 | 369 | 1,735 | 632 | 0 (**0.0%**) | 451 (**71.4%**) |
| `epw.senate.gov` | 365 | 258 | 936 | 626 | 533 (**85.1%**) | 533 (**85.1%**) |
| `hsgac.senate.gov` | 599 | 458 | 1,458 | 499 | 327 (**65.5%**) | 327 (**65.5%**) |
| `energy.senate.gov` | 360 | 269 | 957 | 460 | 388 (**84.3%**) | 388 (**84.3%**) |
| `foreign.senate.gov` | 540 | 382 | 1,019 | 347 | 308 (**88.8%**) | 308 (**88.8%**) |
| `indian.senate.gov` | 249 | 184 | 825 | 316 | 174 (**55.1%**) | 174 (**55.1%**) |
| `help.senate.gov` | 249 | 217 | 784 | 265 | 250 (**94.3%**) | 250 (**94.3%**) |
| `aging.senate.gov` | 150 | 132 | 476 | 242 | 0 (**0.0%**) | 242 (**100.0%**) |
| `armed-services.senate.gov` | 296 | 218 | 661 | 169 | 166 (**98.2%**) | 166 (**98.2%**) |
| `agriculture.senate.gov` | 177 | 138 | 548 | 123 | 102 (**82.9%**) | 102 (**82.9%**) |
| `sbc.senate.gov` | 145 | 101 | 375 | 85 | 69 (**81.2%**) | 69 (**81.2%**) |
| `budget.senate.gov` | 191 | 153 | 523 | 81 | 0 (**0.0%**) | 79 (**97.5%**) |
| `intelligence.senate.gov` | 436 | 133 | 298 | 49 | 25 (**51.0%**) | 25 (**51.0%**) |
| `environment.senate.gov` | 192 | 48 | 139 | 20 | 3 (**15.0%**) | 3 (**15.0%**) |
| `veterans.senate.gov` | 127 | 115 | 266 | 9 | 0 (**0.0%**) | 8 (**88.9%**) |
| `jec.senate.gov` | 56 | 0 | 0 | 1 | 0 (**0.0%**) | 0 (**0.0%**) |
| **Total (all Senate hosts)** | **6,685** | **5,030** | **17,687** | **8,946** | **5,638 (63.0%)** | **8,096 (90.5%)** |

3. **Duplicate witness keys per occasion:**
   - **Before deduplication (within a single source record):** `mods` has **220 / 34,559 (0.64%)** records with repeated `name_key`s (**107,806** raw -> **107,272** deduplicated, **534** dropped, e.g., multi-panel or multi-day appearances in `CHRG-117shrg46099`); `congress_gov` has **110 / 18,140 (0.61%)** records (**35,964** raw -> **35,486** deduplicated, **478** dropped); `house_xml` has **15 / 3,398 (0.44%)** records (**15,112** raw -> **15,089** deduplicated, **23** dropped).
   - **After deduplication (`appearance-records-resolved.sql` / `witnesses.parquet`):** **0** duplicate `(occasion, witness_key)` rows across all **109,572** resolved witnesses (**28,392** occasions).
   - **Near-collision variants within one occasion:** **652 / 28,392 (2.30%)** occasions (**945** pairs) contain distinct `name_key`s sharing a last token; **138 / 28,392 (0.49%)** occasions (**152** pairs) share both surname and first initial (**49** honorific/title prefix differences such as `dr`/`mr`/`hon`, plus middle-initial and `jr`/`sr`/`ii`/`iii` suffix variants).

### 4.3 MCP Coverage

Congress MCP reads the native release and its schema. It does not own extraction,
entity resolution or a second congressional model. The earlier coverage proposal
is historical; current work and closure criteria are assigned below and in §4.6.
Generic access to every published column proves access to that release, not
coverage of every retained source or upstream table.

| Coverage | Existing owner and remaining requirement |
|---|---|
| Identifiers, relationships and coverage | §4.4 and `ct-m103` supply native discovery; `ct-m104` verifies actual data availability and limits, including the additions in §4.6. |
| Participants, ownership, sittings and versions | D4 and §2 remain the model; `ct-gi01` accounts for old Explorer records, conflicts and evidence without matching identities by name. |
| Legislative records and reference history | SpicyRegs remains upstream owner (`ct-u01c` / `ss-vhi2`). `ct-gi01` maps the retained committee records and identifies exactly which upstream detail is published or externally pinned; summary fields are not full histories or ballots. |
| Recordings, channels and research evidence | `ct-gi01` maps retained channel/video metadata, matching decisions, tracks and completeness into the shared release or stable evidence references; `ct-m104` checks their discoverability and queryability. |
| Other retained reference data | `ct-gi01` inventories archive routes, session dates and chamber control alongside the old reference inputs. No unassigned omission is treated as completed migration. |
| HTML dates, descriptions and labels | `ct-082q` owns extraction, source mapping, native publication, site/MCP presentation and shared verification. Its checklist preserves the accepted requirements of the absorbed stage tickets. These add selected metadata; the broader migration retains its own scope. |
| Replay, rebuild and production acceptance | `ct-gi01` supplies preservation/parity evidence, `ct-m104` verifies the shared release, `cef-96wc` records the live switch, and `ct-5kto` retires the old route. |

### 4.4 Native relationship metadata — execution order

Added 2026-10-30. The producer owns the meaning and keys of congressional data.
The public release must explain its relationships to every reader: the site,
Congress MCP, SpicyRegs consumers and direct SQL users. The MCP exposes this
published information; it must not become a second owner of congressional joins.

Reuse `model/registries/release-schema.json`, the existing `_release_schema()` and
release writer in `viewer_publication/archive_format.py`, the model invariants,
and the phase 2 test fixtures. Derive table inventories, reverse relationship
listings, availability and the human join reference from those files. Author
relationship meaning explicitly from DATA-MODEL §9 and this annex §2; do not infer
foreign keys or witness identity from similar column names, names or SQL text.

1. **P2R1 — Define the native metadata.** Extend the existing schema registry with
   table purpose and row meaning, validated identities (including compound keys
   and release-local row positions), relationship endpoints, one/many behavior,
   optional/unresolved references, scope, and meaning. Cover all published tables
   and nested reference fields. Distinguish submitted witness documents from
   transcript appearances, editions from alternate formats, and local entities
   from external identifiers and embedded facts. Keep keys separate from sort
   order. Update DATA-MODEL §8–9 to make this part of the native release interface.
2. **P2R2 — Build and publish from the existing registry.** Extend the existing
   schema publication path, preserving immutable release identity and all current
   file types. Determine availability from the actual release files; an omitted
   entity table is unavailable, not empty. Keep semantic definitions portable;
   label engine-specific query examples by dialect. Do not add a parallel MCP
   registry, a graph database, a query language, or a full-corpus rebuild.
3. **P2R3 — Generate the reader reference and query examples.** Generate the human
   table/key/relationship reference from the same registry, with a drift check.
   Include bounded, parameterized recipes for bills/hearings/witnesses/documents,
   committee rosters/members, nominations/transcripts/votes, recordings/tracks and
   document versions. Explain the result row meaning, optional joins, nested-list
   multiplication, relevant casts and scope. Keep exact URL lookup hashing distinct
   from the capture profile's URL normalization rules.
4. **P2R4 — Validate at the producer boundary.** Check metadata field paths,
   identities, relationship endpoints, declared uniqueness and required references
   using existing producer checks where possible. Add meaningful negative fixtures
   for bad keys/types, nulls, absent targets, nested lists and duplicate-producing
   joins. Validate recipe SQL against maintained small fixtures; do not execute
   catalog SQL automatically when serving or add repeated whole-release scans.
5. **P2R5 — Consume through the existing MCP.** Extend `get_dataset_info` to expose
   table identities, incoming/outgoing relationships, scope and focused relation
   or recipe details from the selected release's schema. Keep the existing six
   tools, direct SQL and resource limits. Definitions from future releases should
   appear without hardcoded MCP relationship additions. The site already exposes
   schema JSON; preserve that shared publication path without a separate UI rewrite.
6. **P2R6 — Verify and document delivery.** Exercise publication, generated-doc
   drift checks, representative producer fixtures and actual MCP discovery/query
   calls. Record local completion separately from deployment; do not overwrite a
   live release or deploy merely to validate metadata. The acceptance outcome is
   that an agent using only MCP discovery can obtain correct joins and meanings
   without reading this repository or guessing identifiers.

### 4.5 Local execution result — 2026-10-30

P2R1–P2R6 are implemented and verified locally. The existing registry now owns
16 table descriptions, 59 relationships and 10 DuckDB recipes. The native writer
publishes their actual-file availability, validates identity/reference paths
against output footers, and reuses native construction checks plus focused
entity-key/reference checks. The generated [relationship reference](../release-relationships.md)
has a drift check. The MCP retains six tools and consumes the published metadata
through `get_dataset_info` selectors.

The focused producer runner passed 21 tests; the MCP runner passed 44 tests. An
independent stdio check read the newly produced native phase 2 fixture and
inspected every table and relationship and executed every recipe. See
[`apps/explorer_mcp/VERIFICATION.md`](../../apps/explorer_mcp/VERIFICATION.md)
for exact commands, the fixture release ID, response size and historical-check
boundaries. This is local completion. No release was deployed or republished;
older releases accurately report that relationship metadata was not published.

**Later result, 2026-10-30:** `ct-m104` records the subsequent metadata-only
publication and production measurements in
[`congress-mcp-production-20261030.md`](../measurements/congress-mcp-production-20261030.md).
That release exposed the 16 table identities, 59 relationships and 10 recipes
without changing the Parquet data. Those counts describe that release; they are
not a ceiling on future coverage or proof that the Explorer migration is done.
`ct-m104` is open again for the data-coverage acceptance below.

### 4.6 Explorer migration and data coverage

**Reconciled 2026-10-30; implementation remains incomplete.** The target is one
maintained congressional-tech native model and publication path, consumed by
the site and Congress MCP. A separate Coverage/Gaps page is allowed; a separate
Explorer data model or publication is not the end state. SpicyRegs remains an
independently owned, pinned upstream source. The old weekly-mirror approach is
superseded; its data-preservation requirement survives.

Current evidence: `publish-explorer.yml` still reads JSON/CSV source state and
writes `pipeline-data/committee-explorer/public`; `deploy-pages.yml` stages that
directory; `dashboard.astro` loads `/data/explorer/CURRENT.json` for full entity
browsing. `ct-gi01` added optional lake inputs, but the workflow does not select
them. These are remaining acceptance gaps, not reasons to discard prior work.

#### Required field inventory

`ct-gi01` MUST record the exact input snapshot, row meaning, identifiers, fields,
provenance, date precision, conflicts and missingness for each family below.
Each retained field gets a destination: a typed native release field/relation,
an explicitly described pinned upstream relation, or a stable evidence reference
when it is too large or is provenance rather than a queryable fact. An unavailable
or intentionally deferred field remains visible in coverage metadata with its
reason and owner. Deferral of existing user-facing data requires an explicit
scope decision; it cannot silently satisfy migration acceptance.

| Family and retained input | Required destination and meaning | Existing owner |
|---|---|---|
| Committee channel directory: `packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv` | Typed committee/channel relationships with source URLs and evidence for the committee mapping; account for historical or unresolved mappings. Channel membership is not evidence that every video is a hearing. | `ct-gi01`; MCP checks `ct-m104` |
| Collected video inventory and metadata: retained YouTube caches and meeting video references | Recording/video identity, original/watch URL, channel, supplied title/description, dates, duration and availability where retained. Preserve collected videos without a resolved meeting; do not limit the inventory to successfully matched recordings. | `ct-gi01` |
| Recording matches: `gpo_hearing_videos.csv`, `meeting_recordings_found.csv` and retained match evidence under `apps/committee_youtube/data/` | Typed links and decisions with their basis, score where present, full-recording/excerpt distinction, unresolved/conflicting status and source references. Preserve observations and adjudication history; old derived matches are a parity oracle, not silently promoted to publisher assertions. | `ct-gi01` |
| Hearing completeness: `apps/committee_youtube/data/meeting_completeness.csv`, Explorer issues and coverage | Typed coverage/issue facts with scope, denominator, date and reason. Unknown, missing, unresolved and confirmed absent remain distinct. Coverage/Gaps and MCP read these same meanings. Owner decision, 2026-11-02: where evidence is held but not yet linked, coverage is unknown, never not_stated, and every present value has a link the user can open. A Senate meeting with no linked document or witness is unknown until Senate committee-page links land; old page decisions are not imported (DATA-MODEL §7.11). | `ct-gi01`, `ct-t915`, `ct-m104` |
| Retained committee amendments/votes: `apps/committee_youtube/data/house_amendments_found.csv` and source records | Preserve the actual record kind, meeting/document references, outcome and evidence where supplied. Document links and vote records must not be described as complete member ballots or tallies. New acquisition/reconstruction remains deferred. | `ct-gi01` |
| Meeting attributes already read internally, including `congress` and source `updated` | Carry useful attributes into typed release fields with origin and date meaning. Keep hearing dates, publisher updates and capture times distinct; reconcile overlapping HTML date work. | `ct-gi01`, `ct-082q` |
| Full bill action histories, cosponsors, member votes, historical nominations/amendments/rosters | Inventory the exact available SpicyRegs tables, columns and generation pins. Identify local summaries separately from accessible detailed upstream records; expose supported relationships and access limits in discovery. Do not mirror all upstream tables or infer that a vote summary contains ballots. | `ct-gi01`, `ct-m104`; upstream `ct-u01c` / `ss-vhi2` |
| HTML descriptions, dates, classifications and source evidence | Publish the selected typed fields through the maintained model, with stable evidence references and field meanings shared by site and MCP. | `ct-082q` |
| Remaining old Explorer fields and reference inputs | Inventory all six old entity/research tables and their source inputs, including archive routes, session dates and chamber control where retained. The named rows above are a minimum, not an exhaustive field list. | `ct-gi01` |

The exact additions are pending implementation: §3 includes accepted target
corrections, and `model/registries/release-schema.json` must change
together with producer SQL and checks. Do not publish invented rows, missing
values as empty tables, or a second MCP schema to conceal a producer gap.
Full-text search, new source acquisition and speaker-turn reconstruction remain
separate deferred work; preserving existing caption/text references is required.

The frozen-input comparison and field inventory evidence is in
[`explorer-native-comparison-20261101.md`](../measurements/explorer-native-comparison-20261101.md).

#### Closure evidence and order

1. **Native data and jobs — `ct-gi01`.** Complete the inventory, preserve facts
   held only in derived files, define typed mappings and versioned schemas, and
   compare the native output with the frozen old inputs. Account for every
   excluded, unresolved or changed row by reason. Prove the actual workflow uses
   pinned lake/SpicyRegs inputs and native exports without legacy full-corpus
   JSON/CSV assembly. Record runtime, memory and work performed on the selected
   input; optional flags and fixture tests alone do not close the ticket.
2. **Site — `ct-t915`.** Replace/redirect the old dashboard or keep only
   Coverage/Gaps backed by the same native release. Verify entity navigation,
   recording links and evidence without a second publication pointer.
3. **MCP — `ct-m104`.** Exercise the actual produced release over stdio and the
   site against the same identity. For every inventory family, check discovery,
   representative queries, missingness and evidence links; demonstrate any
   supported external pinned access and state what is unavailable. Retain the
   earlier performance/recovery evidence and repeat affected checks as needed.
   Selected HTML metadata qualification is part of `ct-082q` and is reused here.
4. **Live switch — `cef-96wc`.** Record exact production job bindings, release
   identity, live site/MCP readback, and previous-release rollback references.
   Local success and merged code remain separate from live acceptance.
5. **Retirement — `ct-5kto`.** Right after the replacement is live and accepted, with no overlap period, remove
   the old writer, pointer consumption and workflow staging. Check active callers
   and preserve raw/provenance records and recovery references. Completed archive
   deletion groups remain completed; they do not substitute for this retirement.

`ct-7uit`, `ct-98sm`, `ct-8kl2` and `ct-77zb` must reflect these unfinished
children. DocSpec's superseded `ss-55jg` does not prove consumer adoption;
`ss-oxg1` owns only generic engine gaps demonstrated by this work. Reuse existing
native job/table/export operations and link a specific engine gap if one is found.

### 4.7 Accepted blind-review corrections — 2026-10-30

The independent greybeard review used ETL workflow and data-intensive systems
lenses against the whole current model, producer SQL and fixtures. The parent
verified the cited paths. All five findings are accepted.

Status, 2026-11-03: implemented, tested across the full `production-offline`
lane (`release-train`), and live in release
`e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd` (replacing
`448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419` after passing
Gates 1–5, contract, and live canary). Their tickets are closed, and the tests
that execute each case are named in `model/fixtures/manifest.md`.

| Finding | Required correction and acceptance case | Owner |
|---|---|---|
| GB1, P1: final fetch facts promote a prior incomplete/error body | DATA-MODEL §6.1/§7.3/§7.7: preserve narrow attempt-specific eligibility and separate final scheduling state. Exercise prior 206/incomplete or 403 followed by final success, valid prior followed by final failure, and unknown prior facts. | `ct-sh4j` |
| GB2, P1: body-only appearance reuse omits context | §1.3: parse context-free facts keyed by body/source/version, bind every eligible context in SQL, and retain literal links/locators. An A-then-B capture of identical bytes must match a clean rebuild and preserve both contexts. | `ct-30fp`; coordinate source versions with `ct-h1nd` |
| GB3, P1: version selection and expected-candidate completeness are lost before publication | Carry all selected versions from daily production through admission; filter before interpretation and anti-join expected candidates against selected-version results/dispositions. Cover mixed versions, a missing reading, empty expected/nonempty expected sets, and the early-skip path. | `ct-yymr` handoff; `ct-kw9b` admission; `ct-vpo2` schemas/invariants |
| GB4, P2: empty current lists revive old witnesses | §1.2–1.3: subject/context identity and collection state survive outside lists; select current observations before unnesting. Verify nonempty → empty, absent declaration, unrecognized layout and extraction failure with explicit fallback outcomes. | `ct-30fp` |
| GB5, P2: name-only dedup removes unequal observations | §1.3/§2: preserve source occurrences and evidence; version public key changes. Verify repeated names across panels/organizations/documents, unchanged-input replay, and ambiguous old-key mappings. | `ct-30fp` |

Existing fixtures that bless incomplete-to-complete promotion or dropping unequal
same-name entries must change with the implementation. The required cases are in
`model/fixtures/manifest.md`; listing a case there does not mean it already runs.
`ct-kw9b` and `ct-yymr` are reopened rather than replaced by duplicate tickets;
the earlier completeness note on `ct-vpo2` now points to those concrete owners.

Implementation order: settle these semantics and small transition fixtures;
update the maintained schemas, producers, selection/admission and consumers;
reuse unchanged completions and recompute affected derived versions; then perform
the §4.6 shared-release and live-switch checks. Preserve raw evidence, selected
releases and previous keys. Do not expand affected production backfills or close
data-preservation acceptance using only table availability, counts or runnable
SQL recipes. No new engine, separate MCP data model or full-corpus replay is
required merely to resolve the design.

## References

**[ARCHITECTURE]**
: *Congressional Document Archive: Architecture.* Editor's Draft, 2026-10-24. `docs/engine-first-architecture.md`.

**[DATA-MODEL]**
: *Congressional Document Archive: Data Model.* Editor's Draft, 2026-10-24. `docs/engine-first-data-model.md`.

**[IMPLEMENTATION-PLAN]**
: *Congressional Document Archive: Implementation Plan.* Note, 2026-10-24. `docs/plans/simplification-plan-20261024.md`.
