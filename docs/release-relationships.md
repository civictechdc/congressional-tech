# Published Congress data: keys and relationships

<!-- Generated from model/registries/release-schema.json; do not edit. -->

Regenerate with `.venv/bin/python -m viewer_publication.archive_schema`; use `--check` to detect drift.

What changed between releases, including retired link keys and identifier changes, is in [release notes](releases/README.md).

The producer publishes this metadata in each immutable release’s `schema.json`. The core archive schema remains version 1; relationship metadata has its own version 1. Older releases can lack this metadata. Availability describes tables actually published, not whether a reference resolves or whether external files can be fetched.

Paths use `[]` for list elements. Cardinality describes the relationship across source and target rows, including all list elements. Nullable references can be absent. `unresolved_allowed` means that bounded or incomplete source coverage can leave an identifier without a local row. A null is unknown; an absent table is unavailable; a published empty table has zero rows.

SQL examples use DuckDB and positional `?` parameters. They are guidance, never executed during discovery. Add `list_row` from zero-based physical position to list/detail, including shard offsets. Predicates such as `list_contains` preserve document grain; unnest only needed lists, and deduplicate before counting across multiple relationships.

## `list` — Searchable documents

One document edition in this release.

Identity: `list_row` (row_position; release).

list_row is virtual: zero-based physical row position, continued across manifest shard row ranges. Never reuse it across releases.

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `filename` | `string` | no | Displayed filename |
| `title` | `string` | yes | Document or publisher title when known |
| `document_kind` | `list<dict>` | no | Document kinds |
| `document_family` | `list<dict>` | no | Filename document families |
| `committee_keys` | `list<dict>` | no | Congress.gov committee system codes |
| `chambers` | `list<dict>` | no | Chambers associated with the document |
| `congress` | `int16` | yes | Congress number when unambiguous |
| `format` | `dict` | no | Original file format |
| `document_date` | `date32` | yes | Date of the document |
| `first_captured` | `date32` | yes | First good fetch date |
| `date_kind` | `dict` | no | Basis of the archive date |
| `saved_kind` | `dict` | no | Original file or recovery |
| `hidden` | `boolean` | no | Excluded from search by review; public links still resolve |
| `meeting_keys` | `list<dict>` | no | Decimal event IDs |
| `measure_keys` | `list<dict>` | no | Bill and nomination identifiers |
| `bioguide_ids` | `list<dict>` | no | Member Bioguide identifiers |
| `witness_keys` | `list<dict>` | no | Witness appearance identifiers |
| `version_keys` | `list<dict>` | no | Hex endpoint keys shared by editions |

Nullability: Nullability transcribes data model §8.1 (list.parquet bullet): a type without "nullable" there is required. A required column is refused at write time.

- `version_keys[]`: Shared lowercase hexadecimal endpoint keys identify different editions, not alternate formats of one document. A document can have several keys.
- `document_kind[]`: Embedded classification values, not foreign keys.
- `document_family[]`: Embedded filename classification values.
- `chambers[]`: Embedded chamber labels.

Outgoing: `document_detail`, `document_meetings`, `document_committees`, `document_bills`, `document_nominations`, `document_members`, `witness_submitted_documents`, `document_editions`.

Incoming: `links_document`, `urls_document`, `sources_document`, `recoveries_document`, `document_editions`, `meeting_transcript_documents`.

## `detail` — The keyed document table: one row per document with its stable link_key, files and every list field; list is its no-ID browser projection

One document edition, in exactly the same order as list.

Identity: `link_key` (primary_key; release; a recovery-only document's key can move in a later release only as the data model section 8.2 states).

list_row stays virtual: zero-based physical row position, continued across manifest shard row ranges; never reuse it across releases. Older releases carry only the detail columns; their rows pair with list by list_row.

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `link_key` | `fixed[8]` | no | Stable public body or original-link key |
| `saved_body` | `fixed[32]` | no | SHA-256 of original bytes |
| `saved_suffix` | `dict` | no | Recorded physical object suffix |
| `saved_media_type` | `dict` | no | Media type of the saved file |
| `saved_bytes` | `int64` | no | Size of original bytes before storage compression |
| `document_date_source` | `dict` | yes | Filename, content or meeting date basis |
| `in_archive_since` | `date32` | yes | Earliest known archive import date |
| `removed_on` | `date32` | yes | Date the publisher removed the document |
| `review_note` | `string` | yes | Review explanation |
| `review_decided_at` | `date32` | yes | Date of the applying review |
| `src_start` | `int32` | no | First source row for this document |
| `src_len` | `int32` | no | Number of source rows for this document |
| `rec_start` | `int32` | no | First recovery row for this document |
| `rec_len` | `int32` | no | Number of recovery rows for this document |
| `alternates` | `list<struct<format dict,body fixed[32],suffix dict,size int64>>` | no | One saved file per other format |
| `package_id` | `string` | yes | GovInfo package identifier |
| `facts` | `list<struct<field dict,value string>>` | no | Selected filename facts, one value per entry |
| `filename` | `string` | no | Displayed filename |
| `title` | `string` | yes | Document or publisher title when known |
| `document_kind` | `list<dict>` | no | Document kinds |
| `document_family` | `list<dict>` | no | Filename document families |
| `committee_keys` | `list<dict>` | no | Congress.gov committee system codes |
| `chambers` | `list<dict>` | no | Chambers associated with the document |
| `congress` | `int16` | yes | Congress number when unambiguous |
| `format` | `dict` | no | Original file format |
| `document_date` | `date32` | yes | Date of the document |
| `first_captured` | `date32` | yes | First good fetch date |
| `date_kind` | `dict` | no | Basis of the archive date |
| `saved_kind` | `dict` | no | Original file or recovery |
| `hidden` | `boolean` | no | Excluded from search by review; public links still resolve |
| `meeting_keys` | `list<dict>` | no | Decimal event IDs |
| `measure_keys` | `list<dict>` | no | Bill and nomination identifiers |
| `bioguide_ids` | `list<dict>` | no | Member Bioguide identifiers |
| `witness_keys` | `list<dict>` | no | Witness appearance identifiers |
| `version_keys` | `list<dict>` | no | Hex endpoint keys shared by editions |

Nullability: Nullability transcribes data model §8.1 (list and detail bullets). A required column is refused at write time.

- `alternates[]`: Other formats of the same document; each has its own body and suffix.
- `facts[]`: Embedded selected filename field/value observations; not a generic entity join.
- `src_start`: Zero-based physical sources row offset; src_len is the contiguous row count.
- `rec_start`: Zero-based physical recoveries row offset; rec_len is the contiguous row count.
- `list_row`: This table repeats every list column, so a bare column name in `"list" JOIN detail USING (list_row)` is ambiguous on new releases; qualify columns (l.filename, d.link_key).
- `document_kind[]`: Same values as list.document_kind; see that field.
- `document_family[]`: Same values as list.document_family; see that field.
- `committee_keys[]`: Same values as list.committee_keys; see that field.
- `chambers[]`: Same values as list.chambers; see that field.
- `meeting_keys[]`: Same values as list.meeting_keys; see that field.
- `measure_keys[]`: Same values as list.measure_keys; see that field.
- `bioguide_ids[]`: Same values as list.bioguide_ids; see that field.
- `witness_keys[]`: Same values as list.witness_keys; see that field.
- `version_keys[]`: Same values as list.version_keys; see that field.

Outgoing: `document_public_link`, `document_body`, `alternate_bodies`, `document_package`.

Incoming: `document_detail`, `witness_transcript_documents`, `nomination_transcript_documents`.

## `links` — Public document link lookup

One stable link key mapped to one release-local document row.

Identity: `link_key` (primary_key; published identifier).

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `link_key` | `fixed[8]` | no | Stable public body or original-link key |
| `list_row` | `int32` | no | Zero-based row in list.parquet |

Nullability: Both columns are required by data model §8.1. A required column is refused at write time.

- `link_key`: First 8 body SHA-256 bytes, or first 8 SHA-256 bytes of url: plus exact original URL for recovery links. Binary key; hex is a display encoding.

Outgoing: `links_document`.

Incoming: `document_public_link`, `retired_link_successor`.

## `retired_links` — Redirects and removal notices for link keys no longer published

One retired link key with its successor or a removal notice.

Identity: `link_key` (primary_key; published identifier).

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `link_key` | `fixed[8]` | no | A link key an earlier release published and this release no longer publishes in links |
| `successor_key` | `fixed[8]` | yes | The current document's primary link key that the retired key redirects to; null means a removal notice |
| `last_release_id` | `string` | no | The latest release that published the key |
| `last_filename` | `string` | yes | The filename the key resolved to in that release |
| `address_versions` | `list<fixed[8]>` | yes | With a removal notice: the current documents (primary link keys) listed at the retired document's addresses, other editions shown as versions, never as a redirect |

Nullability: Nullability transcribes data model §8.1 (retired_links.parquet row). A required column is refused at write time.

- `link_key`: Disjoint from links.link_key. A key published again leaves the ledger. Data model §8.2, Retired keys.
- `address_versions`: Set only when successor_key is null; an address can hold several editions (data model §7.5), so the notice lists them instead of choosing one.

Outgoing: `retired_link_successor`.

Incoming: none.

## `urls` — Normalized source address lookup

One lookup key and document row pair; an address can identify several editions.

Identity: `lookup_key, list_row` (primary_key; release).

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `lookup_key` | `fixed[8]` | no | Fixed normalized address lookup key |
| `list_row` | `int32` | no | Zero-based row in list.parquet |

Nullability: Both columns are required by data model §8.1. A required column is refused at write time.

- `lookup_key`: First 8 SHA-256 bytes of lookup: plus fixed lookup_url(u): remove scheme, leading www, default port, fragment and one trailing path slash; lowercase host; preserve query bytes. This is not capture-profile url_key.

Outgoing: `urls_document`.

Incoming: none.

## `sources` — Publisher addresses and listing context

One source address/context occurrence within a document.

Identity: `list_row, ordinal` (primary_key; release).

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `list_row` | `int32` | no | Zero-based row in list.parquet |
| `ordinal` | `int32` | no | Order within a document |
| `url` | `string` | no | Source address |
| `member_path` | `string` | yes | Path inside an archive container |
| `is_saved` | `boolean` | no | Whether this source names the saved file |
| `first_seen` | `date32` | yes | First observed date of this source |
| `listed_on` | `string` | yes | Publisher page listing the source |
| `link_text` | `string` | yes | Publisher link label |
| `doc_type` | `string` | yes | Publisher document type |
| `posted` | `date32` | yes | Publisher link posting date |

Nullability: Nullability transcribes data model §8.1 (sources.parquet row). A required column is refused at write time.

- `member_path`: Path inside a captured archive container. Interpret together with the source URL; not a document key.
- `url`: Required. A member of a ZIP keeps the ZIP URL here and its place in member_path; the ZIP itself is never a document when its contents were captured.

Outgoing: `sources_document`, `source_address`, `source_listing_page`.

Incoming: none.

## `recoveries` — Recovered document files

One recovered file occurrence within a document.

Identity: `list_row, ordinal` (primary_key; release).

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `list_row` | `int32` | no | Zero-based row in list.parquet |
| `ordinal` | `int32` | no | Order within a document |
| `kind` | `dict` | no | Recovery display kind |
| `body` | `fixed[32]` | no | SHA-256 of original recovered bytes |
| `suffix` | `dict` | no | Physical recovered body suffix |
| `bytes` | `int64` | no | Original recovered byte count |
| `imported_at` | `date32` | yes | Recovery import date; unknown when the input has no import record, as in the v5 seed |
| `recovered_url` | `string` | no | Address where the recovered copy was found |
| `identity_note` | `string` | yes | Explanation identifying the recovery |

Nullability: Nullability transcribes data model §8.1 (recoveries.parquet row). A required column is refused at write time.


Outgoing: `recoveries_document`, `recovery_body`, `recovery_address`.

Incoming: none.

## `meetings` — Congressional meetings and hearings

One event, shared House/Senate event ID namespace.

Identity: `event_id` (primary_key; published identifier).

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `event_id` | `int64` | no | Congressional meeting event ID |
| `chamber` | `dict` | yes | House, Senate or joint |
| `title` | `string` | yes | Document or publisher title when known |
| `meeting_date` | `date32` | yes | Meeting date |
| `meeting_type` | `dict` | yes | Publisher meeting category |
| `session` | `int16` | yes | Congress session number |
| `status` | `dict` | yes | Current meeting status |
| `sittings` | `list<struct<start timestamp,end timestamp,place string,room string,building string,address string>>` | no | Scheduled times and locations, as Congress.gov states them when it has a sitting |
| `committees` | `list<struct<system_code dict,role dict>>` | no | Host committee codes and roles |
| `subject_keys` | `list<dict>` | no | Bill, nomination and treaty subjects |
| `transcripts` | `list<struct<package_id string,list_row int32,formats list<string>>>` | no | Official hearing transcripts, one per package |
| `videos` | `list<struct<name string,url string,video_key string>>` | no | Recorded meeting links |
| `congress` | `int16` | yes | Congress the publisher record states; null when no record states it, never inferred from documents |
| `congress_gov_updated` | `timestamp` | yes | Congress.gov's updateDate for this record: a publisher record update, distinct from the hearing date and capture time |
| `house_xml_updated` | `string` | yes | House XML update-date, literally as stated with no zone: a publisher record update, distinct from the hearing date and capture time |
| `congress_gov_meeting_type` | `dict` | yes | Congress.gov's type label (Hearing, Markup, Meeting) |
| `access` | `dict` | yes | open, closed, partly_closed or unknown, as the publisher type or title states |
| `access_basis` | `dict` | yes | The source and field that state access, such as congress_gov/title |
| `not_held` | `bool` | yes | The publisher title opens with postponed, canceled, rescheduled or test; null with no record |
| `rescheduled_to` | `int64` | yes | Later meeting of the same committees and title within 60 days, when the publisher states Rescheduled or only the later twin has a recording; derived |
| `rescheduled_basis` | `dict` | yes | publisher_status or recording_on_later_twin |

Nullability: Nullability transcribes data model §8.1 (meetings.parquet row); access fields, not_held and rescheduling are null with no record, as their meanings state. List columns are empty, never null. A required column is refused at write time.

- `sittings[]`: Embedded scheduled intervals and places. Congress.gov states instants and places, so its sitting is used when present; a House-only sitting's unzoned Eastern local time is converted to an instant. An explicit empty House state stays empty. Times retain published precision; do not invent a Congress from the session number.
- `committees[]`: Host/participant roles belong to this meeting-committee association.
- `transcripts[]`: One entry per GovInfo package. list_row is the package's listed document whose saved format ranks first (then lowest row); formats are the distinct saved and alternate formats over all the package's listed documents, in format-preference order. A package listed as several documents (editions) keeps one entry.
- `transcripts[].formats`: Format names (pdf, html, ...) the package is retained in, in format-preference order; values, not keys.
- `videos[]`: Publisher recording links; video_key joins retained recordings when available.
- `meeting_type`: As stated, with House XML codes (HHRG, HMKP, HMTG) on House rows; congress_gov_meeting_type carries the shared label.

Outgoing: `meeting_bills`, `meeting_nominations`, `meeting_committees`, `meeting_transcript_documents`, `meeting_recordings`, `meeting_transcript_packages`, `meeting_video_address`, `meeting_treaties`.

Incoming: `document_meetings`, `recording_meetings`, `witness_meeting`, `match_meeting`, `committee_record_meeting`, `coverage_meeting`.

## `witnesses` — Witness appearances

One source-occurrence witness observation at a meeting, package, or page; not a deduplicated person.

Identity: `witness_key` (primary_key; published identifier).

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `witness_key` | `string` | no | Lowercase hex of first 8 bytes of SHA-256 of ["witness-occurrence-v2", occasion, source, record_sha_hex, source_locator, context_key] |
| `occasion` | `dict` | no | Appearance occasion key (meeting:{event_id}, package:{package_id}, or page:{sha256_prefix}) |
| `source` | `dict` | no | Observation source family (house_xml, congress_gov, senate_page, or mods) |
| `record_sha` | `fixed[32]` | no | SHA-256 of the source body or inline record supplying this witness observation |
| `source_locator` | `string` | no | Deterministic occurrence locator within the retained source record |
| `context_key` | `string` | no | Lowercase hex SHA-256 of compact JSON [source_url, member_path] for the bound capture context |
| `event_id` | `int64` | yes | Meeting event ID when occasion is a meeting |
| `package_id` | `string` | yes | GovInfo CHRG package ID when occasion is a package or matched transcript |
| `page_url` | `string` | yes | Senate hearing page URL when occasion is a page |
| `name` | `string` | yes | Display name of the witness |
| `position` | `string` | yes | Witness title or position |
| `organization` | `string` | yes | Witness organization or affiliation |
| `on_behalf_of` | `string` | yes | Represented entity when distinct from organization |
| `location` | `string` | yes | Witness locality or state |
| `panel` | `string` | yes | Panel heading or label |
| `panel_order` | `int16` | yes | 1-based panel order within the occasion |
| `display_order` | `int16` | yes | 1-based witness display order within the occasion or panel |
| `witness_type` | `dict` | yes | Source witness classification |
| `testified` | `boolean` | yes | Whether the witness testified |
| `bioguide_id` | `dict` | yes | Bioguide identifier when the witness is a Member of Congress |

Nullability: Nullability transcribes the phase-2 annex §3 file table (docs/plans/phase-2-annex-20261028.md): a type without "nullable" there is required. A required column is refused at write time.

- `occasion`: meeting:{event_id}, package:{package_id}, or page:{sha256_prefix}. Witness keys hash the occasion, source, record_sha, source_locator, and context_key; names alone never join or deduplicate appearances.

Outgoing: `witness_meeting`, `witness_transcript_documents`, `witness_member`, `witness_package`, `witness_page`.

Incoming: `witness_submitted_documents`.

## `recordings` — Meeting recordings and captured tracks

One provider-prefixed recording.

Identity: `video_key` (primary_key; published identifier).

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `video_key` | `string` | no | Provider-prefixed recording identifier |
| `event_ids` | `list<int64>` | no | Sorted meeting event IDs associated with this recording |
| `tracks` | `list<struct<body fixed[32],suffix dict,format dict,language dict,production dict>>` | no | Captured caption, subtitle, and playlist tracks from their latest good fetch |

Nullability: Nullability transcribes the phase-2 annex §3 file table (docs/plans/phase-2-annex-20261028.md): a type without "nullable" there is required. A required column is refused at write time.

- `tracks[]`: Embedded captured caption/subtitle/playlist files. Language and production describe each track; these are not document-list rows.

Outgoing: `recording_meetings`, `recording_tracks`.

Incoming: `meeting_recordings`.

## `committees` — Current and historical committees

One Congress.gov system code.

Identity: `system_code` (primary_key; published identifier).

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `system_code` | `string` | no | Congress.gov committee system code |
| `name` | `string` | no | Official committee name |
| `chamber` | `dict` | no | House, Senate or joint |
| `committee_type` | `dict` | yes | Committee category |
| `parent_system_code` | `dict` | yes | Parent committee code |
| `names` | `list<struct<name string,start date32,end date32>>` | no | Dated committee names |
| `website` | `string` | yes | Official committee website |
| `is_current` | `boolean` | yes | Current committee record |

Nullability: Nullability transcribes the phase-2 annex §3 file table (docs/plans/phase-2-annex-20261028.md): a type without "nullable" there is required. A required column is refused at write time.

- `names[]`: Embedded names with half-open [start,end) dates, ordered latest start first. Null endpoints mean unknown or open-ended.

Outgoing: `committee_parent`, `committee_website`.

Incoming: `document_committees`, `meeting_committees`, `committee_parent`, `roster_committee`, `bill_activity_committee`, `bills_committees`, `nominations_committees`, `channel_committee`.

## `members` — Current and historical members

One Bioguide member.

Identity: `bioguide_id` (primary_key; published identifier).

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `bioguide_id` | `string` | no | Bioguide member identifier |
| `name` | `string` | no | Member display name ({name_first} {name_last}) |
| `terms` | `list<struct<chamber dict,state dict,district int16,party dict,start date32,end date32>>` | no | Congressional service terms ordered latest first |
| `cross_ids` | `struct<lis string,opensecrets string,govtrack string,icpsr string,wikidata string,fec list<string>>` | no | Cross-walk identifiers across legislative datasets |

Nullability: Nullability transcribes the phase-2 annex §3 file table (docs/plans/phase-2-annex-20261028.md): a type without "nullable" there is required. A required column is refused at write time.

- `terms[]`: Embedded service terms with half-open [start,end) dates, latest first. Terms do not establish historical committee seats.
- `cross_ids`: External dataset identifiers; an identifier does not imply that dataset is included in this release.

Outgoing: `member_lis`, `member_opensecrets`, `member_govtrack`, `member_icpsr`, `member_wikidata`, `member_fec`.

Incoming: `document_members`, `witness_member`, `roster_member`, `bill_sponsor`, `amendment_sponsor`, `committee_record_sponsor`.

## `rosters` — Current-Congress committee seats

One member assignment to a committee in a Congress; no historical roster reconstruction.

Identity: `congress, system_code, bioguide_id` (primary_key; published identifier).

Coverage: Current-Congress seats only; spicy-regs keeps no roster history.

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `congress` | `int16` | no | Congress number for the committee assignment |
| `system_code` | `dict` | no | Lowercase committee or subcommittee system code |
| `bioguide_id` | `dict` | no | Assigned member Bioguide identifier |
| `title` | `dict` | yes | Committee leadership or seat position title |
| `rank` | `int16` | yes | Numeric party rank on the committee |
| `party` | `dict` | yes | Party caucus for the committee assignment |

Nullability: Nullability transcribes the phase-2 annex §3 file table (docs/plans/phase-2-annex-20261028.md): a type without "nullable" there is required. A required column is refused at write time.


Outgoing: `roster_committee`, `roster_member`.

Incoming: none.

## `bills` — Referenced bills and embedded legislative facts

One bill referenced by documents or meetings; bounded by upstream retained data.

Identity: `bill_id` (primary_key; published identifier).

Coverage: Amendments cover the 119th Congress only until spicy-regs backfills.

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `bill_id` | `string` | no | Canonical bill identifier ({congress}-{type}-{number}) |
| `title` | `string` | yes | Official or primary bill title |
| `short_title` | `string` | yes | Short title when present |
| `sponsor_bioguide_id` | `dict` | yes | Primary sponsor Bioguide identifier |
| `introduced` | `date32` | yes | Date the measure was introduced |
| `latest_action_date` | `date32` | yes | Date of the latest recorded action |
| `latest_action_text` | `string` | yes | Text of the latest recorded action |
| `stage` | `dict` | yes | Lifecycle stage derived by spicy-regs |
| `policy_area` | `dict` | yes | CRS policy area |
| `committees` | `list<dict>` | no | Referred committee system codes |
| `cbo_estimates` | `list<struct<publication_id string,date date32,description string>>` | no | CBO cost estimates associated with the bill |
| `floor_votes` | `list<struct<vote_id string,basis dict,chamber dict,date date32,question string,result string,yea int16,nay int16>>` | no | Roll-call votes tied by vote record or bill action |
| `amendments` | `list<struct<amendment_id string,purpose string,sponsor_bioguide_id dict,latest_action_date date32,latest_action_text string>>` | no | Direct and chained amendments to the bill |
| `committee_activities` | `list<struct<system_code dict,activity dict,date date32>>` | no | Committee referral, markup, and report activities |

Nullability: Nullability transcribes the phase-2 annex §3 file table (docs/plans/phase-2-annex-20261028.md): a type without "nullable" there is required. A required column is refused at write time.

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

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `nomination_id` | `string` | no | Canonical nomination identifier ({congress}-pn-{number}[-{part}]) |
| `description` | `string` | yes | Nomination description |
| `organization` | `string` | yes | Executive or independent agency name |
| `received` | `date32` | yes | Date received in the Senate |
| `latest_action_date` | `date32` | yes | Date of latest action |
| `latest_action_text` | `string` | yes | Text of latest action |
| `committees` | `list<dict>` | no | Referred Senate committee system codes |
| `transcripts` | `list<string>` | no | Printed hearing package IDs from nomination hearing references |
| `floor_votes` | `list<struct<vote_id string,date date32,question string,result string,yea int16,nay int16>>` | no | Senate roll-call votes on the nomination |

Nullability: Nullability transcribes the phase-2 annex §3 file table, except description: upstream military promotion lists carry no description (in the pinned spicy-regs nominations generation, 1,349 of its 1,363 rows without one are military), so it is nullable, a legitimate upstream gap rather than a mapping loss. A required column is refused at write time.

- `floor_votes[]`: Embedded Senate roll-call summaries; no individual member positions.
- `transcripts[]`: GovInfo CHRG package identifiers; a retained transcript can have multiple document formats or editions.

Outgoing: `nominations_committees`, `nominations_votes`, `nomination_transcript_documents`, `nomination_packages`.

Incoming: `document_nominations`, `meeting_nominations`.

## `url_state` — Capture scheduling state

One exact requested URL, including requests without a successful capture.

Identity: `requested_url` (primary_key; published identifier).

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `requested_url` | `string` | no | Exact address scheduled for capture |
| `attempts` | `int32` | no | Number of fetch lines for the address |
| `last_attempt` | `timestamp<microsecond,UTC>` | yes | Latest attempt time |
| `last_status` | `int16` | yes | Latest attempt HTTP status |
| `last_outcome` | `dict` | yes | Latest attempt outcome |
| `last_good_at` | `timestamp<microsecond,UTC>` | yes | Latest good fetch time |
| `next_attempt_at` | `timestamp<microsecond,UTC>` | yes | Next scheduled fetch time |

Nullability: Nullability transcribes data model §7.7. A required column is refused at write time.

- `requested_url`: Exact scheduled address. Missing success is not missing publication; this is operational capture state, not an entity or document catalogue.

Outgoing: `capture_request_address`.

Incoming: none.

## `url_variants` — Active capture URL aliases

One canonical/variant URL pair used by capture policy.

Identity: `canonical_url, variant_url` (primary_key; published identifier).

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `canonical_url` | `string` | no | Active canonical URL for capture joins |
| `variant_url` | `string` | no | Active alternate URL for capture joins |

Nullability: The documents are silent; decided from the row meaning: the key and the fields that define the row are required, descriptive fields from upstream records can be absent, and list columns are empty, never null. A required column is refused at write time.

- `canonical_url`: Capture-profile aliases only. Do not use this table to reproduce the fixed public URL lookup hash.

Outgoing: `capture_canonical_address`, `capture_variant_address`.

Incoming: none.

## `videos` — Collected committee channel uploads, matched or not

One upload a retained YouTube cache lists.

Identity: `video_key` (primary_key; published identifier).

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `video_key` | `string` | no | youtube:{id} video identity |
| `handle` | `dict` | no | Channel handle whose cache table lists it |
| `channel_id` | `string` | yes | YouTube channel ID, null when the cache has none |
| `system_code` | `dict` | yes | Committee of the curated channel; channel membership does not make a video a hearing |
| `title` | `string` | yes | Title as the channel states it |
| `source_description` | `string` | yes | Description as the channel states it, distinct from any HTML description |
| `published_at` | `timestamp` | yes | YouTube's publication time for the upload |
| `video_published_at` | `timestamp` | yes | YouTube's video publication time |
| `duration_seconds` | `int32` | yes | Duration in seconds when retained |
| `available` | `bool` | yes | Whether the last check found it available |
| `has_caption` | `bool` | yes | Whether YouTube states a caption exists |
| `details_checked_at` | `timestamp` | yes | When details were last checked |
| `stated_event_ids` | `list<int64>` | no | Event IDs the video's own text names: claims, since committees mistag |
| `record_sha` | `fixed[32]` | no | SHA-256 of the cache body, which also holds upstream API JSON and is the evidence reference |

Nullability: The documents are silent; decided from the row meaning: the key and the fields that define the row are required, descriptive fields from upstream records can be absent, and list columns are empty, never null. A required column is refused at write time.

- `stated_event_ids[]`: A claim the video makes, not a verified link; recording_matches keeps it as claimed.

Outgoing: `video_channel`.

Incoming: `match_recording`.

## `channels` — Curated committee YouTube channel directory

One curated channel handle.

Identity: `handle` (primary_key; published identifier).

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `handle` | `string` | no | Channel handle |
| `channel_id` | `string` | yes | YouTube channel ID |
| `system_code` | `dict` | no | Committee the directory maps it to |
| `committee_label` | `string` | yes | Committee label in the directory |
| `role` | `dict` | no | primary, secondary or member |
| `title` | `string` | yes | Channel's own title when cached |
| `custom_url` | `string` | yes | Channel's custom URL when cached |
| `uploads_scan_complete` | `bool` | yes | Whether the cache scanned every upload |
| `mapping_basis` | `dict` | no | curated_directory: a curated mapping with no further evidence column |
| `record_sha` | `fixed[32]` | yes | SHA-256 of the cache body, null with no cached channel row |

Nullability: The documents are silent; decided from the row meaning: the key and the fields that define the row are required, descriptive fields from upstream records can be absent, and list columns are empty, never null. A required column is refused at write time.


Outgoing: `channel_committee`.

Incoming: `video_channel`.

## `recording_matches` — Recording links and decisions with their basis

One observation that a subject has, or lacks, a recording.

Identity: `match_id` (primary_key; published identifier).

Coverage: Scored date and title matches arrive with the native matcher; gpo_hearing_videos.csv stays a parity oracle until then.

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `match_id` | `string` | no | Hex SHA-256 of the compact JSON [subject_kind, subject_id, video ref, basis] |
| `subject_kind` | `dict` | no | event or package |
| `event_id` | `int64` | yes | Meeting subject; null for a package or a stated number no meeting has |
| `package_id` | `string` | yes | GPO package subject |
| `video_key` | `string` | yes | Video identity; can lack a video row |
| `url` | `string` | yes | Off-channel recording URL |
| `basis` | `dict` | no | publisher_link, video_states_event_id or curated |
| `decision` | `dict` | yes | The verdict as stated, or linked |
| `score` | `int16` | yes | 100 publisher link, 95 stated event ID; null otherwise |
| `recording_scope` | `dict` | yes | full, excerpt or unknown |
| `status` | `dict` | no | asserted, claimed, decided, conflicting or unresolved; unresolved is a negative verdict that old matcher evidence disputes |
| `note` | `string` | yes | Curator note, or the unmatched stated number |
| `source_ref` | `string` | yes | Evidence reference: the record or decision |

Nullability: The documents are silent; decided from the row meaning: the key and the fields that define the row are required, descriptive fields from upstream records can be absent, and list columns are empty, never null. A required column is refused at write time.


Outgoing: `match_meeting`, `match_recording`.

Incoming: none.

## `committee_records` — Amendment and vote documents House meeting XML lists

One document link in a meeting record; a vote row is a document link, not a ballot or tally.

Identity: `record_key` (primary_key; published identifier).

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `record_key` | `string` | no | Hex SHA-256 of the compact JSON [record_sha hex, ordinal as text] |
| `event_id` | `int64` | no | Meeting event ID |
| `kind` | `dict` | no | amendment or vote |
| `bill` | `string` | yes | Bill as stated |
| `number` | `string` | yes | Amendment or vote number as stated |
| `sponsor_bioguide` | `dict` | yes | Sponsor as stated |
| `amendment_type` | `dict` | yes | Amendment type as stated |
| `enbloc` | `string` | yes | En bloc number as stated |
| `source_description` | `string` | yes | Description as stated |
| `url` | `string` | yes | Document URL, null when the record states none |
| `record_sha` | `fixed[32]` | no | SHA-256 of the House XML body |
| `ordinal` | `int32` | no | Position in that record, so duplicate links stay distinct |

Nullability: The documents are silent; decided from the row meaning: the key and the fields that define the row are required, descriptive fields from upstream records can be absent, and list columns are empty, never null. A required column is refused at write time.


Outgoing: `committee_record_meeting`, `committee_record_sponsor`.

Incoming: none.

## `meeting_coverage` — Typed coverage facts per meeting

One aspect of one meeting: recording, transcript, documents, witnesses or captions.

Identity: `event_id, aspect` (primary_key; published identifier).

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `event_id` | `int64` | no | Meeting event ID |
| `aspect` | `dict` | no | recording, transcript, documents, witnesses or captions |
| `state` | `dict` | no | present, partial, claimed, empty, not_stated, unresolved, not_public, confirmed_absent or unknown; these never merge |
| `basis` | `dict` | no | Which relation states it |
| `count` | `int32` | no | Rows behind present |
| `reason` | `dict` | yes | Why a state holds, when known, such as old_evidence_disputes_negative_verdict |

Nullability: The documents are silent; entity-meeting-coverage.sql always sets basis (a CASE with an else) and count (coalesced), so both are required; reason is stated only when known. A required column is refused at write time.

- `state`: confirmed_absent only from undisputed curated negative verdicts on every package of the meeting, each linked to that meeting alone; zero rows never prove absence. partial means excerpts only; claimed means only a video’s own text; for captions, no observation is unknown, never empty.

Outgoing: `coverage_meeting`.

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

### `video_channel`

`videos.handle` → `channels.handle`. The curated channel whose cache lists the video.

many-to-one; match: `equal`; nullable: false; resolution: `unresolved_allowed`. Scope: selected release.

### `match_meeting`

`recording_matches.event_id` → `meetings.event_id`. The meeting an observation concerns.

many-to-one; match: `equal`; nullable: true; resolution: `required`. Scope: selected release.

### `match_recording`

`recording_matches.video_key` → `videos.video_key`. The collected video; a publisher or curated key can lack one.

many-to-one; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `committee_record_meeting`

`committee_records.event_id` → `meetings.event_id`. The meeting whose record lists the document.

many-to-one; match: `equal`; nullable: false; resolution: `required`. Scope: selected release.

### `committee_record_sponsor`

`committee_records.sponsor_bioguide` → `members.bioguide_id`. The sponsor as stated.

many-to-one; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: selected release.

### `coverage_meeting`

`meeting_coverage.event_id` → `meetings.event_id`. The meeting a coverage fact describes.

many-to-one; match: `equal`; nullable: false; resolution: `required`. Scope: selected release.

### `channel_committee`

`channels.system_code` → `committees.system_code`. The committee of a curated mapping.

many-to-one; match: `equal`; nullable: false; resolution: `unresolved_allowed`. Scope: selected release.

### `retired_link_successor`

`retired_links.successor_key` → `links.link_key`. A retired key redirects to the document its successor key resolves to.

many-to-one; match: `equal`; nullable: true; resolution: `required`. Scope: selected release.

## Pinned upstream relations

Held upstream and never mirrored here. A release names a relation’s generation and path only when it states that family’s digest.

| Relation | Family and table | Keys | Local joins | Row | Limits |
| --- | --- | --- | --- | --- | --- |
| `bill_actions` | `bill-family/bill_actions` | `bill_id` | `bills.bill_id` | One recorded action on a bill | bills carries only the latest action: a summary is not a history. |
| `bill_cosponsors` | `bill-family/bill_cosponsors` | `bill_id, bioguide_id` | `bills.bill_id`, `members.bioguide_id` | One cosponsorship | bills does not carry cosponsors. |
| `member_votes` | `roll-call-votes/member_votes` | `vote_id, bioguide_id` | `bills.floor_votes[].vote_id`, `nominations.floor_votes[].vote_id`, `members.bioguide_id` | One member ballot | Local floor_votes hold totals, not ballots. |
| `roll_call_votes` | `roll-call-votes/roll_call_votes` | `vote_id` | `bills.floor_votes[].vote_id`, `nominations.floor_votes[].vote_id` | One roll-call vote | Includes votes not tied to a local bill or nomination. |
| `amendments` | `amendments/amendments` | `amendment_id` | `bills.amendments[].amendment_id` | One floor amendment | Coverage is limited by upstream; committee_records holds different, committee-stage documents. |
| `nominations` | `nominations/nominations` | `congress, number, part_number` | none | One nomination part | Coverage is limited by upstream; local nominations cover what that generation holds. |
| `committee_assignments` | `committee-rosters/committee_assignments` | `congress, system_code, bioguide_id` | `rosters.system_code`, `members.bioguide_id` | One committee assignment | Current Congress only: not a historical roster. |

## Query recipes (DuckDB)

### `bill_documents` — Documents directly annotated with a bill

Requires: `list`, `detail`.

Result: One document edition.

Parameters, in order: `bill_id` (example `119-hr-1`).

```sql
SELECT l.list_row,l.filename,l.title,hex(d.link_key) AS link_key
FROM "list" l JOIN detail d USING (list_row)
WHERE list_contains(l.measure_keys,?) ORDER BY l.list_row LIMIT 100
```

Matches direct list.measure_keys annotations only. Use bill_hearing_transcripts for transcripts linked through meeting subjects.

Does not require the bounded bills table to contain this identifier. This SQL includes hidden rows; add NOT coalesce(l.hidden,false) to exclude them.

### `bill_hearing_transcripts` — Hearing transcripts linked to a bill through meetings

Requires: `meetings`, `list`, `detail`.

Result: One visible transcript document edition with its distinct supporting meeting IDs in numeric order.

Parameters, in order: `bill_id` (example `119-hr-1`).

```sql
WITH matched AS (
  SELECT t.list_row,list(DISTINCT m.event_id ORDER BY m.event_id) AS meeting_ids
  FROM meetings m,UNNEST(m.transcripts) AS u(t)
  WHERE list_contains(m.subject_keys,?) GROUP BY t.list_row
)
SELECT l.list_row,l.filename,l.title,hex(d.link_key) AS link_key,matched.meeting_ids
FROM matched JOIN "list" l USING (list_row) JOIN detail d USING (list_row)
WHERE NOT coalesce(l.hidden,false) ORDER BY l.list_row LIMIT 100
```

Follows meetings.subject_keys and meetings.transcripts[].list_row even when the document has no direct measure_keys annotation.

Repeated paths and multiple meetings produce one row per document. Supporting meetings explain the association; they do not establish witness participation or historical completeness.

Does not require the bounded bills table to contain this identifier. Missing required tables mean unavailable, not an empty complete result.

Returns at most 100 documents in list_row order. Use list_row filtering for further pages; query_sql also enforces its row and byte limits.

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

### `meeting_recordings` — A meeting's recordings with basis and status

Requires: `recording_matches`.

Result: One observation.

Parameters, in order: `event_id` (example `115538`).

```sql
SELECT video_key,url,basis,decision,score,recording_scope,status,note
FROM recording_matches WHERE event_id=? ORDER BY basis,video_key,url
```

claimed rows are what a video says about itself; conflicting rows are retained, not settled.

### `channel_unmatched_videos` — Videos of a channel with no recording match

Requires: `videos`, `recording_matches`.

Result: One upload.

Parameters, in order: `handle` (example `@AgRepublicans`).

```sql
SELECT v.video_key,v.title,v.published_at FROM videos v
WHERE v.handle=? AND NOT EXISTS (SELECT 1 FROM recording_matches m WHERE m.video_key=v.video_key)
ORDER BY v.published_at DESC NULLS LAST LIMIT 100
```

Channel membership is not evidence that a video is a hearing.

### `coverage_counts` — Coverage counts for an aspect

Requires: `meeting_coverage`.

Result: One state.

Parameters, in order: `aspect` (example `recording`).

```sql
SELECT state,count(*) AS meetings FROM meeting_coverage WHERE aspect=? GROUP BY state ORDER BY state
```

unknown and not_stated are not absence.
