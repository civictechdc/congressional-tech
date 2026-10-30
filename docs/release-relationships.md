# Published Congress data: keys and relationships

<!-- Generated from model/registries/release-schema.json; do not edit. -->

Regenerate with `.venv/bin/python -m viewer_publication.archive_schema`; use `--check` to detect drift.

The producer publishes this metadata in each immutable release’s `schema.json`. The core archive schema remains version 1; relationship metadata has its own version 1. Older releases can lack this metadata. Availability describes tables actually published, not whether a reference resolves or whether external files can be fetched.

Paths use `[]` for list elements. Cardinality describes the relationship across source and target rows, including all list elements. Nullable references can be absent. `unresolved_allowed` means that bounded or incomplete source coverage can leave an identifier without a local row. A null is unknown; an absent table is unavailable; a published empty table has zero rows.

SQL examples use DuckDB and positional `?` parameters. They are guidance, never executed during discovery. Add `list_row` from zero-based physical position to list/detail, including shard offsets. Predicates such as `list_contains` preserve document grain; unnest only needed lists, and deduplicate before counting across multiple relationships.

## `list` — Searchable documents

One document edition in this release.

Identity: `list_row` (row_position; release).

list_row is virtual: zero-based physical row position, continued across manifest shard row ranges. Never reuse it across releases.

| Field | Published type | Meaning |
| --- | --- | --- |
| `filename` | `string` | Displayed filename |
| `title` | `string` | Document or publisher title when known |
| `document_kind` | `list<dict>` | Document kinds |
| `document_family` | `list<dict>` | Filename document families |
| `committee_keys` | `list<dict>` | Congress.gov committee system codes |
| `chambers` | `list<dict>` | Chambers associated with the document |
| `congress` | `int16` | Congress number when unambiguous |
| `format` | `dict` | Original file format |
| `document_date` | `date32` | Date of the document |
| `first_captured` | `date32` | First good fetch date |
| `date_kind` | `dict` | Basis of the archive date |
| `saved_kind` | `dict` | Original file or recovery |
| `hidden` | `boolean` | Excluded from search by review; public links still resolve |
| `meeting_keys` | `list<dict>` | Decimal event IDs |
| `measure_keys` | `list<dict>` | Bill and nomination identifiers |
| `bioguide_ids` | `list<dict>` | Member Bioguide identifiers |
| `witness_keys` | `list<dict>` | Witness appearance identifiers |
| `version_keys` | `list<dict>` | Hex endpoint keys shared by editions |

- `version_keys[]`: Shared lowercase hexadecimal endpoint keys identify different editions, not alternate formats of one document. A document can have several keys.
- `document_kind[]`: Embedded classification values, not foreign keys.
- `document_family[]`: Embedded filename classification values.
- `chambers[]`: Embedded chamber labels.

Outgoing: `document_detail`, `document_meetings`, `document_committees`, `document_bills`, `document_nominations`, `document_members`, `witness_submitted_documents`, `document_editions`.

Incoming: `links_document`, `urls_document`, `sources_document`, `recoveries_document`, `document_editions`, `meeting_transcript_documents`.

## `detail` — Document files and metadata

One document edition, in exactly the same order as list.

Identity: `list_row` (row_position; release).

list_row is virtual: zero-based physical row position, continued across manifest shard row ranges. Never reuse it across releases.

| Field | Published type | Meaning |
| --- | --- | --- |
| `link_key` | `fixed[8]` | Stable public body or original-link key |
| `saved_body` | `fixed[32]` | SHA-256 of original bytes |
| `saved_suffix` | `dict` | Recorded physical object suffix |
| `saved_media_type` | `dict` | Media type of the saved file |
| `saved_bytes` | `int64` | Size of original bytes before storage compression |
| `document_date_source` | `dict` | Filename, content or meeting date basis |
| `in_archive_since` | `date32` | Earliest known archive import date |
| `removed_on` | `date32` | Date the publisher removed the document |
| `review_note` | `string` | Review explanation |
| `review_decided_at` | `date32` | Date of the applying review |
| `src_start` | `int32` | First source row for this document |
| `src_len` | `int32` | Number of source rows for this document |
| `rec_start` | `int32` | First recovery row for this document |
| `rec_len` | `int32` | Number of recovery rows for this document |
| `alternates` | `list<struct<format dict,body fixed[32],suffix dict,size int64>>` | One saved file per other format |
| `package_id` | `string` | GovInfo package identifier |
| `facts` | `list<struct<field dict,value string>>` | Selected filename facts, one value per entry |

- `alternates[]`: Other formats of the same document; each has its own body and suffix.
- `facts[]`: Embedded selected filename field/value observations; not a generic entity join.
- `src_start`: Zero-based physical sources row offset; src_len is the contiguous row count.
- `rec_start`: Zero-based physical recoveries row offset; rec_len is the contiguous row count.

Outgoing: `document_public_link`, `document_body`, `alternate_bodies`, `document_package`.

Incoming: `document_detail`, `witness_transcript_documents`, `nomination_transcript_documents`.

## `links` — Public document link lookup

One stable link key mapped to one release-local document row.

Identity: `link_key` (primary_key; published identifier).

| Field | Published type | Meaning |
| --- | --- | --- |
| `link_key` | `fixed[8]` | Stable public body or original-link key |
| `list_row` | `int32` | Zero-based row in list.parquet |

- `link_key`: First 8 body SHA-256 bytes, or first 8 SHA-256 bytes of url: plus exact original URL for recovery links. Binary key; hex is a display encoding.

Outgoing: `links_document`.

Incoming: `document_public_link`.

## `urls` — Normalized source address lookup

One lookup key and document row pair; an address can identify several editions.

Identity: `lookup_key, list_row` (primary_key; release).

| Field | Published type | Meaning |
| --- | --- | --- |
| `lookup_key` | `fixed[8]` | Fixed normalized address lookup key |
| `list_row` | `int32` | Zero-based row in list.parquet |

- `lookup_key`: First 8 SHA-256 bytes of lookup: plus fixed lookup_url(u): remove scheme, leading www, default port, fragment and one trailing path slash; lowercase host; preserve query bytes. This is not capture-profile url_key.

Outgoing: `urls_document`.

Incoming: none.

## `sources` — Publisher addresses and listing context

One source address/context occurrence within a document.

Identity: `list_row, ordinal` (primary_key; release).

| Field | Published type | Meaning |
| --- | --- | --- |
| `list_row` | `int32` | Zero-based row in list.parquet |
| `ordinal` | `int32` | Order within a document |
| `url` | `string` | Source address |
| `member_path` | `string` | Path inside an archive container |
| `is_saved` | `boolean` | Whether this source names the saved file |
| `first_seen` | `date32` | First observed date of this source |
| `listed_on` | `string` | Publisher page listing the source |
| `link_text` | `string` | Publisher link label |
| `doc_type` | `string` | Publisher document type |
| `posted` | `date32` | Publisher link posting date |

- `member_path`: Path inside a captured archive container. Interpret together with the source URL; not a document key.

Outgoing: `sources_document`, `source_address`, `source_listing_page`.

Incoming: none.

## `recoveries` — Recovered document files

One recovered file occurrence within a document.

Identity: `list_row, ordinal` (primary_key; release).

| Field | Published type | Meaning |
| --- | --- | --- |
| `list_row` | `int32` | Zero-based row in list.parquet |
| `ordinal` | `int32` | Order within a document |
| `kind` | `dict` | Recovery display kind |
| `body` | `fixed[32]` | SHA-256 of original recovered bytes |
| `suffix` | `dict` | Physical recovered body suffix |
| `bytes` | `int64` | Original recovered byte count |
| `imported_at` | `date32` | Recovery import date; unknown when the input has no import record, as in the v5 seed |
| `recovered_url` | `string` | Address where the recovered copy was found |
| `identity_note` | `string` | Explanation identifying the recovery |


Outgoing: `recoveries_document`, `recovery_body`, `recovery_address`.

Incoming: none.

## `meetings` — Congressional meetings and hearings

One event, shared House/Senate event ID namespace.

Identity: `event_id` (primary_key; published identifier).

| Field | Published type | Meaning |
| --- | --- | --- |
| `event_id` | `int64` | Congressional meeting event ID |
| `chamber` | `dict` | House, Senate or joint |
| `title` | `string` | Document or publisher title when known |
| `meeting_date` | `date32` | Meeting date |
| `meeting_type` | `dict` | Publisher meeting category |
| `session` | `int16` | Congress session number |
| `status` | `dict` | Current meeting status |
| `sittings` | `list<struct<start timestamp,end timestamp,place string>>` | Scheduled times and locations |
| `committees` | `list<struct<system_code dict,role dict>>` | Host committee codes and roles |
| `subject_keys` | `list<dict>` | Bill, nomination and treaty subjects |
| `transcripts` | `list<struct<package_id string,list_row int32>>` | Official hearing transcripts |
| `videos` | `list<struct<name string,url string,video_key string>>` | Recorded meeting links |

- `sittings[]`: Embedded scheduled intervals and places. Times retain published precision; do not invent a Congress from the session number.
- `committees[]`: Host/participant roles belong to this meeting-committee association.
- `transcripts[]`: Package identifier and release-local document row identify the same retained hearing transcript.
- `videos[]`: Publisher recording links; video_key joins retained recordings when available.

Outgoing: `meeting_bills`, `meeting_nominations`, `meeting_committees`, `meeting_transcript_documents`, `meeting_recordings`, `meeting_transcript_packages`, `meeting_video_address`, `meeting_treaties`.

Incoming: `document_meetings`, `recording_meetings`, `witness_meeting`.

## `witnesses` — Witness appearances

One named witness appearance at a meeting, package, or page; not a deduplicated person.

Identity: `witness_key` (primary_key; published identifier).

| Field | Published type | Meaning |
| --- | --- | --- |
| `witness_key` | `string` | Lowercase hex of first 8 bytes of SHA-256 of ["witness", occasion, name_key] |
| `occasion` | `dict` | Appearance occasion key (meeting:{event_id}, package:{package_id}, or page:{sha256_prefix}) |
| `event_id` | `int64` | Meeting event ID when occasion is a meeting |
| `package_id` | `string` | GovInfo CHRG package ID when occasion is a package or matched transcript |
| `page_url` | `string` | Senate hearing page URL when occasion is a page |
| `name` | `string` | Display name of the witness |
| `position` | `string` | Witness title or position |
| `organization` | `string` | Witness organization or affiliation |
| `on_behalf_of` | `string` | Represented entity when distinct from organization |
| `location` | `string` | Witness locality or state |
| `panel` | `string` | Panel heading or label |
| `panel_order` | `int16` | 1-based panel order within the occasion |
| `display_order` | `int16` | 1-based witness display order within the occasion or panel |
| `witness_type` | `dict` | Source witness classification |
| `testified` | `boolean` | Whether the witness testified |
| `bioguide_id` | `dict` | Bioguide identifier when the witness is a Member of Congress |

- `occasion`: meeting:{event_id}, package:{package_id}, or page:{sha256_prefix}. Witness keys hash the occasion and normalized name; names alone never join appearances.

Outgoing: `witness_meeting`, `witness_transcript_documents`, `witness_member`, `witness_package`, `witness_page`.

Incoming: `witness_submitted_documents`.

## `recordings` — Meeting recordings and captured tracks

One provider-prefixed recording.

Identity: `video_key` (primary_key; published identifier).

| Field | Published type | Meaning |
| --- | --- | --- |
| `video_key` | `string` | Provider-prefixed recording identifier |
| `event_ids` | `list<int64>` | Sorted meeting event IDs associated with this recording |
| `tracks` | `list<struct<body fixed[32],suffix dict,format dict,language dict,production dict>>` | Captured caption, subtitle, and playlist tracks from their latest good fetch |

- `tracks[]`: Embedded captured caption/subtitle/playlist files. Language and production describe each track; these are not document-list rows.

Outgoing: `recording_meetings`, `recording_tracks`.

Incoming: `meeting_recordings`.

## `committees` — Current and historical committees

One Congress.gov system code.

Identity: `system_code` (primary_key; published identifier).

| Field | Published type | Meaning |
| --- | --- | --- |
| `system_code` | `string` | Congress.gov committee system code |
| `name` | `string` | Official committee name |
| `chamber` | `dict` | House, Senate or joint |
| `committee_type` | `dict` | Committee category |
| `parent_system_code` | `dict` | Parent committee code |
| `names` | `list<struct<name string,start date32,end date32>>` | Dated committee names |
| `website` | `string` | Official committee website |
| `is_current` | `boolean` | Current committee record |

- `names[]`: Embedded names with half-open [start,end) dates, ordered latest start first. Null endpoints mean unknown or open-ended.

Outgoing: `committee_parent`, `committee_website`.

Incoming: `document_committees`, `meeting_committees`, `committee_parent`, `roster_committee`, `bill_activity_committee`, `bills_committees`, `nominations_committees`.

## `members` — Current and historical members

One Bioguide member.

Identity: `bioguide_id` (primary_key; published identifier).

| Field | Published type | Meaning |
| --- | --- | --- |
| `bioguide_id` | `string` | Bioguide member identifier |
| `name` | `string` | Member display name ({name_first} {name_last}) |
| `terms` | `list<struct<chamber dict,state dict,district int16,party dict,start date32,end date32>>` | Congressional service terms ordered latest first |
| `cross_ids` | `struct<lis string,opensecrets string,govtrack string,icpsr string,wikidata string,fec list<string>>` | Cross-walk identifiers across legislative datasets |

- `terms[]`: Embedded service terms with half-open [start,end) dates, latest first. Terms do not establish historical committee seats.
- `cross_ids`: External dataset identifiers; an identifier does not imply that dataset is included in this release.

Outgoing: `member_lis`, `member_opensecrets`, `member_govtrack`, `member_icpsr`, `member_wikidata`, `member_fec`.

Incoming: `document_members`, `witness_member`, `roster_member`, `bill_sponsor`, `amendment_sponsor`.

## `rosters` — Current-Congress committee seats

One member assignment to a committee in a Congress; no historical roster reconstruction.

Identity: `congress, system_code, bioguide_id` (primary_key; published identifier).

Coverage: Current-Congress seats only; spicy-regs keeps no roster history.

| Field | Published type | Meaning |
| --- | --- | --- |
| `congress` | `int16` | Congress number for the committee assignment |
| `system_code` | `dict` | Lowercase committee or subcommittee system code |
| `bioguide_id` | `dict` | Assigned member Bioguide identifier |
| `title` | `dict` | Committee leadership or seat position title |
| `rank` | `int16` | Numeric party rank on the committee |
| `party` | `dict` | Party caucus for the committee assignment |


Outgoing: `roster_committee`, `roster_member`.

Incoming: none.

## `bills` — Referenced bills and embedded legislative facts

One bill referenced by documents or meetings; bounded by upstream retained data.

Identity: `bill_id` (primary_key; published identifier).

Coverage: Amendments cover the 119th Congress only until spicy-regs backfills.

| Field | Published type | Meaning |
| --- | --- | --- |
| `bill_id` | `string` | Canonical bill identifier ({congress}-{type}-{number}) |
| `title` | `string` | Official or primary bill title |
| `short_title` | `string` | Short title when present |
| `sponsor_bioguide_id` | `dict` | Primary sponsor Bioguide identifier |
| `introduced` | `date32` | Date the measure was introduced |
| `latest_action_date` | `date32` | Date of the latest recorded action |
| `latest_action_text` | `string` | Text of the latest recorded action |
| `stage` | `dict` | Lifecycle stage derived by spicy-regs |
| `policy_area` | `dict` | CRS policy area |
| `committees` | `list<dict>` | Referred committee system codes |
| `cbo_estimates` | `list<struct<publication_id string,date date32,description string>>` | CBO cost estimates associated with the bill |
| `floor_votes` | `list<struct<vote_id string,basis dict,chamber dict,date date32,question string,result string,yea int16,nay int16>>` | Roll-call votes tied by vote record or bill action |
| `amendments` | `list<struct<amendment_id string,purpose string,sponsor_bioguide_id dict,latest_action_date date32,latest_action_text string>>` | Direct and chained amendments to the bill |
| `committee_activities` | `list<struct<system_code dict,activity dict,date date32>>` | Committee referral, markup, and report activities |

- `cbo_estimates[]`: Embedded publication IDs, dates and descriptions, not full CBO estimate text.
- `floor_votes[]`: One embedded vote per vote_id per bill; basis distinguishes vote_record from bill_action. Counts are vote totals, not member positions.
- `amendments[]`: Embedded direct/chained amendment summaries; 119th Congress coverage until upstream backfill.
- `committee_activities[]`: Embedded committee events; several activities can refer to the same committee.

Outgoing: `bill_sponsor`, `amendment_sponsor`, `bill_activity_committee`, `bills_committees`, `bills_votes`, `bill_cbo_publications`, `bill_amendments`.

Incoming: `document_bills`, `meeting_bills`.

## `nominations` — Referenced nominations and embedded legislative facts

One nomination including its part when present; bounded by upstream retained data.

Identity: `nomination_id` (primary_key; published identifier).

Coverage: Nominations cover the 119th Congress only until spicy-regs backfills.

| Field | Published type | Meaning |
| --- | --- | --- |
| `nomination_id` | `string` | Canonical nomination identifier ({congress}-pn-{number}[-{part}]) |
| `description` | `string` | Nomination description |
| `organization` | `string` | Executive or independent agency name |
| `received` | `date32` | Date received in the Senate |
| `latest_action_date` | `date32` | Date of latest action |
| `latest_action_text` | `string` | Text of latest action |
| `committees` | `list<dict>` | Referred Senate committee system codes |
| `transcripts` | `list<string>` | Printed hearing package IDs from nomination hearing references |
| `floor_votes` | `list<struct<vote_id string,date date32,question string,result string,yea int16,nay int16>>` | Senate roll-call votes on the nomination |

- `floor_votes[]`: Embedded Senate roll-call summaries; no individual member positions.
- `transcripts[]`: GovInfo CHRG package identifiers; a retained transcript can have multiple document formats or editions.

Outgoing: `nominations_committees`, `nominations_votes`, `nomination_transcript_documents`, `nomination_packages`.

Incoming: `document_nominations`, `meeting_nominations`.

## `url_state` — Capture scheduling state

One exact requested URL, including requests without a successful capture.

Identity: `requested_url` (primary_key; published identifier).

| Field | Published type | Meaning |
| --- | --- | --- |
| `requested_url` | `string` | Exact address scheduled for capture |
| `attempts` | `int32` | Number of fetch lines for the address |
| `last_attempt` | `timestamp<microsecond,UTC>` | Latest attempt time |
| `last_status` | `int16` | Latest attempt HTTP status |
| `last_outcome` | `dict` | Latest attempt outcome |
| `last_good_at` | `timestamp<microsecond,UTC>` | Latest good fetch time |
| `next_attempt_at` | `timestamp<microsecond,UTC>` | Next scheduled fetch time |

- `requested_url`: Exact scheduled address. Missing success is not missing publication; this is operational capture state, not an entity or document catalogue.

Outgoing: `capture_request_address`.

Incoming: none.

## `url_variants` — Active capture URL aliases

One canonical/variant URL pair used by capture policy.

Identity: `canonical_url, variant_url` (primary_key; published identifier).

| Field | Published type | Meaning |
| --- | --- | --- |
| `canonical_url` | `string` | Active canonical URL for capture joins |
| `variant_url` | `string` | Active alternate URL for capture joins |

- `canonical_url`: Capture-profile aliases only. Do not use this table to reproduce the fixed public URL lookup hash.

Outgoing: `capture_canonical_address`, `capture_variant_address`.

Incoming: none.

## `search` — SpicyEngine search layer

One searchable document, meeting or witness appearance in the column set SpicyEngine indexes.

Identity: `id` (primary_key; published identifier).

Coverage: Document bodies and source link text are not indexed; context holds titles, names and display facts only.

Coverage: A witness without a meeting (printed-hearing package or Senate page occasion) has no date or committee.

Coverage: meeting_type mixes Congress.gov words with unmapped docs.house.gov codes (HHRG, HMKP, HMTG).

| Field | Published type | Meaning |
| --- | --- | --- |
| `id` | `string` | SpicyEngine record ID: lowercase hex SHA-256 of the compact JSON [source_id, member_key] |
| `source_id` | `dict` | Source of the row: documents, meetings or witnesses |
| `member_key` | `string` | The row's key in its source: a document's link_key as lowercase hex, a meeting's event_id, or a witness_key |
| `source_occurrence_id` | `string` | Lowercase hex of the first 8 bytes of the SHA-256 of the row's other columns as compact JSON; it changes exactly when the row's content does |
| `title` | `string` | A document's title, else its filename, else 'Document {link_key}'; a meeting's title, else 'Meeting {event_id}'; a witness's name |
| `url` | `string` | The record's page on the public archive site |
| `context` | `string` | Searchable text joined from the record and its related records; empty when none |
| `identifiers` | `list<string>` | Exact identifiers matched as keywords |
| `metadata` | `string` | JSON object of display fields that are not columns of this file |
| `date` | `date32` | A document's date, a meeting's date, or a witness's meeting date |
| `first_captured` | `date32` | A document's first capture date; null for meetings and witnesses |
| `record_kind` | `list<dict>` | document, meeting or witness |
| `chamber` | `list<dict>` | A document's chambers, a meeting's chamber, or a witness's: its meeting's, else its GovInfo package letter's, else senate for a Senate hearing page |
| `committee` | `list<dict>` | Congress.gov committee system codes: a document's committee_keys, a meeting's committees, a witness's meeting committees |
| `committee_expanded` | `list<dict>` | committee plus the parent_system_code of each code from committees.parquet |
| `congress` | `list<dict>` | Congress number as text: a document's congress, a meeting record's congress, or a witness's meeting congress, else its CHRG package's |
| `document_kind` | `list<dict>` | Document kinds; documents only |
| `format` | `list<dict>` | Saved file format; documents only |
| `meeting_type` | `list<dict>` | Meeting type as published; meetings only |
| `status` | `list<dict>` | Meeting status; meetings only |
| `witness_type` | `list<dict>` | Source witness classification; witnesses only |
| `has_video` | `list<dict>` | true or false by whether a meeting with a current record lists a recording; empty without a record |
| `has_transcript` | `list<dict>` | true or false by whether a meeting with a current record has a matched printed transcript; empty without a record |

- `member_key`: Resolve by source_id: documents to detail.link_key (hex), meetings to meetings.event_id, witnesses to witnesses.witness_key. Hidden documents have no row.
- `context`: Documents: the filename when a title exists, linked meeting titles, linked witness names and organizations, and display-fact values. Meetings: committee names, witness names, positions and organizations, bill titles and linked document titles. Witnesses: position, organization, represented entity, panel and meeting title.
- `identifiers[]`: Documents: link_key, package_id, measure_keys and meeting_keys. Meetings: event_id, subject_keys, transcript package IDs and video keys. Witnesses: witness_key, bioguide_id, event_id and package_id.
- `record_kind[]`: Embedded record kinds. Like every list column here: sorted bytewise, distinct, without empty strings or nulls, and empty when its field does not apply to the row's source.
- `chamber[]`: Embedded chamber labels.
- `committee[]`: Embedded system codes; committees.parquet names them.
- `committee_expanded[]`: Holds committee, so a filter on a parent committee also matches its subcommittees.
- `congress[]`: Embedded Congress numbers, not keys.
- `document_kind[]`: Embedded classification values, not foreign keys.
- `format[]`: Embedded format labels.
- `meeting_type[]`: Embedded publisher values.
- `status[]`: Embedded publisher values.
- `witness_type[]`: Embedded publisher values.
- `has_video[]`: Unknown, not false, when the meeting has no current record.
- `has_transcript[]`: Unknown, not false, when the meeting has no current record.

SpicyEngine indexes this file under this `fields` block, published with it in `schema.json`:

```json
{
  "key": "id",
  "title": "title",
  "url": "url",
  "text": [
    "context"
  ],
  "identifiers": "identifiers",
  "metadata": "metadata",
  "date_default": "date",
  "descendants": {
    "committee": "committee_expanded"
  },
  "compact": [
    "record_kind",
    "chamber",
    "committee"
  ],
  "references": [
    "congress"
  ]
}
```

Outgoing: none.

Incoming: none.

## Relationships

### `document_detail`

`list.list_row` → `detail.list_row`. Same physical row position, including shard offsets.

one-to-one; match: `equal`; nullable: false; resolution: `required`. Scope: selected release.

### `document_public_link`

`detail.link_key` → `links.link_key`. Resolve the document’s primary public link to the canonical document row; the lookup key identifies one row even when several records reference the same body.

many-to-one; match: `equal`; nullable: true; resolution: `required`. Scope: selected release; stable public link identifier.

### `links_document`

`links.list_row` → `list.list_row`. Release-local document row.

many-to-one; match: `equal`; nullable: false; resolution: `required`. Scope: selected release.

### `urls_document`

`urls.list_row` → `list.list_row`. Release-local document row.

many-to-one; match: `equal`; nullable: false; resolution: `required`. Scope: selected release.

### `sources_document`

`sources.list_row` → `list.list_row`. Release-local document row.

many-to-one; match: `equal`; nullable: false; resolution: `required`. Scope: selected release.

### `recoveries_document`

`recoveries.list_row` → `list.list_row`. Release-local document row.

many-to-one; match: `equal`; nullable: false; resolution: `required`. Scope: selected release.

### `document_meetings`

`list.meeting_keys[]` → `meetings.event_id`. Meetings explicitly associated with the document.

many-to-many; match: `decimal_string_to_integer`; nullable: true; resolution: `required`. Scope: selected release.

### `document_committees`

`list.committee_keys[]` → `committees.system_code`. Committee attribution; does not imply authorship.

many-to-many; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `document_bills`

`list.measure_keys[]` → `bills.bill_id`. Exact typed measure identifiers; values for the other measure type do not match.

many-to-many; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `meeting_bills`

`meetings.subject_keys[]` → `bills.bill_id`. Measures explicitly named as meeting subjects.

many-to-many; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `document_nominations`

`list.measure_keys[]` → `nominations.nomination_id`. Exact typed measure identifiers; values for the other measure type do not match.

many-to-many; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `meeting_nominations`

`meetings.subject_keys[]` → `nominations.nomination_id`. Measures explicitly named as meeting subjects.

many-to-many; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `document_members`

`list.bioguide_ids[]` → `members.bioguide_id`. Members explicitly associated with the document; no role inferred.

many-to-many; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `witness_submitted_documents`

`list.witness_keys[]` → `witnesses.witness_key`. Documents attached from this witness appearance’s own document URLs; not every document from the meeting.

many-to-many; match: `equal`; nullable: true; resolution: `required`. Scope: selected release.

### `document_editions`

`list.version_keys[]` → `list.version_keys[]`. Different document rows sharing a version endpoint key; exclude the same row and deduplicate when keys overlap.

many-to-many; match: `shared_list_value`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `meeting_committees`

`meetings.committees[].system_code` → `committees.system_code`. Committee participation and its published role.

many-to-many; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `meeting_transcript_documents`

`meetings.transcripts[].list_row` → `list.list_row`. Retained printed hearing document; accompanying package_id preserves the source reference.

many-to-many; match: `equal`; nullable: true; resolution: `required`. Scope: selected release.

### `meeting_recordings`

`meetings.videos[].video_key` → `recordings.video_key`. Publisher video reference to a retained recording.

many-to-many; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `recording_meetings`

`recordings.event_ids[]` → `meetings.event_id`. Meetings explicitly associated with one recording; not an inferred transcript identity.

many-to-many; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `witness_meeting`

`witnesses.event_id` → `meetings.event_id`. Meeting occasion when known; package/page occasions may have no event ID.

many-to-one; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `witness_transcript_documents`

`witnesses.package_id` → `detail.package_id`. Appearance participation in a printed hearing package; separate from ownership of submitted documents.

many-to-many; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `witness_member`

`witnesses.bioguide_id` → `members.bioguide_id`. Published Bioguide identification of a witness who is a member; never infer by name.

many-to-one; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `committee_parent`

`committees.parent_system_code` → `committees.system_code`. Subcommittee’s parent committee when identified.

many-to-one; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `roster_committee`

`rosters.system_code` → `committees.system_code`. Committee assignment, current-Congress snapshot only.

many-to-one; match: `equal`; nullable: false; resolution: `unresolved_allowed`. Scope: rosters.congress; current-Congress coverage only.

### `roster_member`

`rosters.bioguide_id` → `members.bioguide_id`. Assigned member, current-Congress snapshot only.

many-to-one; match: `equal`; nullable: false; resolution: `unresolved_allowed`. Scope: rosters.congress; current-Congress coverage only.

### `bill_sponsor`

`bills.sponsor_bioguide_id` → `members.bioguide_id`. Primary sponsor when supplied; null is allowed.

many-to-one; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `amendment_sponsor`

`bills.amendments[].sponsor_bioguide_id` → `members.bioguide_id`. Sponsor of the nested amendment, not necessarily the bill sponsor.

many-to-many; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `bill_activity_committee`

`bills.committee_activities[].system_code` → `committees.system_code`. Committee performing an embedded activity; repeated activities are meaningful.

many-to-many; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `bills_committees`

`bills.committees[]` → `committees.system_code`. Published committee referrals.

many-to-many; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `bills_votes`

`bills.floor_votes[].vote_id` → spicy-regs roll-call-votes. External vote identity; the local embedded record provides only the published summary.

many-to-many; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `nominations_committees`

`nominations.committees[]` → `committees.system_code`. Published committee referrals.

many-to-many; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `nominations_votes`

`nominations.floor_votes[].vote_id` → spicy-regs roll-call-votes. External vote identity; the local embedded record provides only the published summary.

many-to-many; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `nomination_transcript_documents`

`nominations.transcripts[]` → `detail.package_id`. Printed hearing packages associated with this nomination; use exact package IDs.

many-to-many; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `document_body`

`detail.saved_body, saved_suffix` → archive body store. Use lowercase hex SHA-256 and the recorded suffix: bodies/sha256/{first two hex characters}/{full hex digest}{suffix}. Binary hashes are not text keys. Files are fetched separately.

many-to-one; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `alternate_bodies`

`detail.alternates[].body, alternates[].suffix` → archive body store. Use lowercase hex SHA-256 and the recorded suffix: bodies/sha256/{first two hex characters}/{full hex digest}{suffix}. Binary hashes are not text keys. Files are fetched separately.

many-to-many; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `recovery_body`

`recoveries.body, suffix` → archive body store. Use lowercase hex SHA-256 and the recorded suffix: bodies/sha256/{first two hex characters}/{full hex digest}{suffix}. Binary hashes are not text keys. Files are fetched separately.

many-to-one; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `recording_tracks`

`recordings.tracks[].body, tracks[].suffix` → archive body store. Use lowercase hex SHA-256 and the recorded suffix: bodies/sha256/{first two hex characters}/{full hex digest}{suffix}. Binary hashes are not text keys. Files are fetched separately.

many-to-many; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `member_lis`

`members.cross_ids.lis` → Senate LIS. Published member crosswalk identifier; null or an empty list means unavailable.

many-to-one; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `member_opensecrets`

`members.cross_ids.opensecrets` → OpenSecrets. Published member crosswalk identifier; null or an empty list means unavailable.

many-to-one; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `member_govtrack`

`members.cross_ids.govtrack` → GovTrack. Published member crosswalk identifier; null or an empty list means unavailable.

many-to-one; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `member_icpsr`

`members.cross_ids.icpsr` → ICPSR. Published member crosswalk identifier; null or an empty list means unavailable.

many-to-one; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `member_wikidata`

`members.cross_ids.wikidata` → Wikidata. Published member crosswalk identifier; null or an empty list means unavailable.

many-to-one; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `member_fec`

`members.cross_ids.fec[]` → FEC. Published member crosswalk identifier; null or an empty list means unavailable.

many-to-many; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `bill_cbo_publications`

`bills.cbo_estimates[].publication_id` → CBO publications. Published cost-estimate identifier; date and description remain embedded in the bill.

many-to-many; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `bill_amendments`

`bills.amendments[].amendment_id` → spicy-regs amendments. Published amendment identifiers; purpose, sponsor and latest action remain embedded in the bill.

many-to-many; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `document_package`

`detail.package_id` → GovInfo packages. Publisher package identity; it can exist without a retained local document.

many-to-one; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `meeting_transcript_packages`

`meetings.transcripts[].package_id` → GovInfo packages. Publisher package identity; it can exist without a retained local document.

many-to-many; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `witness_package`

`witnesses.package_id` → GovInfo packages. Publisher package identity; it can exist without a retained local document.

many-to-one; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `nomination_packages`

`nominations.transcripts[]` → GovInfo packages. Publisher package identity; it can exist without a retained local document.

many-to-many; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `source_address`

`sources.url` → web URL. Published URL, not proof of a locally retained document. Use the fixed urls lookup for document address searches.

many-to-one; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `source_listing_page`

`sources.listed_on` → web URL. Published URL, not proof of a locally retained document. Use the fixed urls lookup for document address searches.

many-to-one; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `recovery_address`

`recoveries.recovered_url` → web URL. Published URL, not proof of a locally retained document. Use the fixed urls lookup for document address searches.

many-to-one; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `witness_page`

`witnesses.page_url` → web URL. Published URL, not proof of a locally retained document. Use the fixed urls lookup for document address searches.

many-to-one; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `meeting_video_address`

`meetings.videos[].url` → web URL. Published URL, not proof of a locally retained document. Use the fixed urls lookup for document address searches.

many-to-many; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `committee_website`

`committees.website` → web URL. Published URL, not proof of a locally retained document. Use the fixed urls lookup for document address searches.

many-to-one; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `capture_request_address`

`url_state.requested_url` → web URL. Published URL, not proof of a locally retained document. Use the fixed urls lookup for document address searches.

many-to-one; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `capture_canonical_address`

`url_variants.canonical_url` → web URL. Published URL, not proof of a locally retained document. Use the fixed urls lookup for document address searches.

many-to-one; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `capture_variant_address`

`url_variants.variant_url` → web URL. Published URL, not proof of a locally retained document. Use the fixed urls lookup for document address searches.

many-to-one; match: `identifier`; nullable: true; resolution: `external`. Scope: external identifier or retained object; no local entity table implied.

### `meeting_treaties`

`meetings.subject_keys[]` → Congress.gov treaties. Subject identifiers of the form {congress}-treaty-{number}; bill and nomination values in the same list use their separate relationships. No treaty entity table is published.

many-to-many; match: `identifier`; nullable: true; resolution: `external`. Scope: typed treaty identifiers only.

## Query recipes (DuckDB)

### `bill_documents` — Documents related to a bill

Requires: `list`, `detail`.

Result: One document edition.

Parameters, in order: `bill_id` (example `119-hr-1`).

```sql
SELECT l.list_row,l.filename,l.title,hex(d.link_key) AS link_key
FROM "list" l JOIN detail d USING (list_row)
WHERE list_contains(l.measure_keys,?) ORDER BY l.list_row LIMIT 100
```

Does not require the bounded bills table to contain this identifier.

### `hearing_documents` — Documents and hearing titles

Requires: `list`, `meetings`.

Result: One document associated with the selected hearing.

Parameters, in order: `event_id` (example `118001`).

```sql
SELECT l.list_row,l.filename,m.event_id,m.title
FROM "list" l JOIN meetings m ON list_contains(l.meeting_keys,CAST(m.event_id AS VARCHAR))
WHERE m.event_id=? ORDER BY l.list_row LIMIT 100
```

meeting_keys stores decimal text; event_id is an integer.

### `witness_documents` — Documents submitted by a witness appearance

Requires: `list`, `witnesses`.

Result: One submitted document for this appearance.

Parameters, in order: `witness_key` (example `0123456789abcdef`).

```sql
SELECT w.witness_key,w.name,l.list_row,l.filename
FROM witnesses w JOIN "list" l ON list_contains(l.witness_keys,w.witness_key)
WHERE w.witness_key=? ORDER BY l.list_row LIMIT 100
```

Use a witness_key, never a person-name join.

### `witness_transcripts` — Printed hearings containing a witness appearance

Requires: `witnesses`, `detail`, `list`.

Result: One retained transcript document for the appearance.

Parameters, in order: `witness_key` (example `0123456789abcdef`).

```sql
SELECT w.witness_key,w.name,d.package_id,l.list_row,l.filename
FROM witnesses w JOIN detail d ON d.package_id=w.package_id JOIN "list" l USING (list_row)
WHERE w.witness_key=? ORDER BY l.list_row LIMIT 100
```

No package_id means no published package association; submitted documents use a different relationship.

### `committee_roster` — Committee members for a published Congress

Requires: `rosters`, `committees`, `members`.

Result: One current-Congress committee assignment.

Parameters, in order: `system_code` (example `hsif00`), `congress` (example `119`).

```sql
SELECT r.congress,r.system_code,c.name AS committee,r.bioguide_id,m.name,r.title,r.rank,r.party
FROM rosters r LEFT JOIN committees c USING (system_code) LEFT JOIN members m USING (bioguide_id)
WHERE r.system_code=? AND r.congress=? ORDER BY r.rank,r.bioguide_id LIMIT 100
```

An empty historical result does not establish that the committee had no members.

### `nomination_transcripts` — Printed hearings related to a nomination

Requires: `nominations`, `detail`, `list`.

Result: One retained transcript document.

Parameters, in order: `nomination_id` (example `119-pn-730-2`).

```sql
SELECT n.nomination_id,d.package_id,l.list_row,l.filename
FROM nominations n JOIN detail d ON list_contains(n.transcripts,d.package_id) JOIN "list" l USING (list_row)
WHERE n.nomination_id=? ORDER BY l.list_row LIMIT 100
```

Preserve the nomination part, for example 119-pn-730-2.

### `bill_votes` — Vote summaries associated with a bill

Requires: `bills`.

Result: One embedded roll-call summary for this bill.

Parameters, in order: `bill_id` (example `119-hr-1`).

```sql
SELECT b.bill_id,v.vote_id,v.basis,v.chamber,v.date,v.question,v.result,v.yea,v.nay
FROM bills b,UNNEST(b.floor_votes) AS votes(v)
WHERE b.bill_id=? ORDER BY v.date,v.vote_id LIMIT 100
```

This is vote-level data, not member voting records. Unnest only the list you need; unnesting amendments as well would multiply votes.

### `nomination_votes` — Vote summaries associated with a nomination

Requires: `nominations`.

Result: One embedded Senate vote summary.

Parameters, in order: `nomination_id` (example `119-pn-730-2`).

```sql
SELECT n.nomination_id,v.vote_id,v.date,v.question,v.result,v.yea,v.nay
FROM nominations n,UNNEST(n.floor_votes) AS votes(v)
WHERE n.nomination_id=? ORDER BY v.date,v.vote_id LIMIT 100
```

### `recording_tracks` — Captured tracks for a hearing

Requires: `recordings`.

Result: One captured recording track.

Parameters, in order: `event_id` (example `118001`).

```sql
SELECT r.video_key,hex(t.body) AS body,t.suffix,t.format,t.language,t.production
FROM recordings r,UNNEST(r.tracks) AS tracks(t)
WHERE list_contains(r.event_ids,CAST(? AS BIGINT)) ORDER BY r.video_key,t.language,t.format LIMIT 100
```

Construct the body URL using the recorded suffix; a track is not a list document.

### `document_editions` — Other editions sharing an endpoint

Requires: `list`.

Result: One other document edition.

Parameters, in order: `list_row` (example `3`).

```sql
SELECT DISTINCT other.list_row,other.filename,other.document_date
FROM "list" selected JOIN "list" other ON list_has_any(selected.version_keys,other.version_keys)
WHERE selected.list_row=? AND other.list_row<>selected.list_row ORDER BY other.list_row LIMIT 100
```

list_row belongs only to the selected release. Multiple shared endpoint keys must not duplicate a document.
