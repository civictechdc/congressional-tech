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

Coverage: Date bounds span accepted document dates only and Congress bounds skip suspect-dated documents; document_dates counts accepted, suspect and undated documents. Bounds are observed values, not evidence of complete coverage.

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
| `document_date` | `date32` | yes | Date of the document as read; detail.document_date_status says whether it is accepted or suspect |
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
- `document_kind[]`: Embedded classification values, not foreign keys. Words listed together under synonyms name one kind (the first is the House naming guide's word); filter them as one.
- `document_family[]`: Embedded filename classification values.
- `chambers[]`: Embedded chamber labels.
- `document_kind[]` synonyms: `witness-statement` = `testimony`.

Outgoing: `document_detail`, `document_meetings`, `document_committees`, `document_bills`, `document_nominations`, `document_members`, `witness_submitted_documents`, `document_editions`.

Incoming: `links_document`, `urls_document`, `sources_document`, `recoveries_document`, `document_editions`, `meeting_transcript_documents`.

## `detail` — The keyed document table: one row per document with its stable link_key, files and every list field; list is its no-ID browser projection

One document edition, in exactly the same order as list.

Identity: `link_key` (primary_key; release; a recovery-only document's key can move in a later release only as the data model section 8.2 states).

list_row stays virtual: zero-based physical row position, continued across manifest shard row ranges; never reuse it across releases. Older releases carry only the detail columns; their rows pair with list by list_row.

Coverage: Date bounds span accepted document dates only and Congress bounds skip suspect-dated documents; document_dates counts accepted, suspect and undated documents. Bounds are observed values, not evidence of complete coverage.

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `link_key` | `fixed[8]` | no | Stable public body or original-link key |
| `saved_body` | `fixed[32]` | no | SHA-256 of original bytes |
| `saved_suffix` | `dict` | no | Recorded physical object suffix |
| `saved_media_type` | `dict` | no | Media type of the saved file |
| `saved_bytes` | `int64` | no | Size of original bytes before storage compression |
| `document_date_source` | `dict` | yes | Filename, content or meeting date basis |
| `document_date_status` | `dict` | yes | accepted, or suspect for a filename date more than 30 days after first_captured or outside the tagged Congress's years (one year of margin); document_date keeps the literal reading either way; null when undated |
| `title_source` | `dict` | yes | Which candidate gave the title: correction, page_title, page_heading, link_text, other_format_page_title, other_format_page_heading, copy_link_text, recovered_copy, or label_witness (a label with the witness name); null when untitled |
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
| `description` | `string` | yes | The publisher's page summary as declared, never the title or the site's own description; NULL when none survives selection |
| `published_on` | `date32` | yes | The page's declared publication date on its stated local date; a page date, never a hearing or document date |
| `modified_on` | `date32` | yes | The page's declared modification date on its stated local date; never changes document_date, date_kind or first_captured |
| `publisher_labels` | `list<dict>` | no | The page's declared sections (article:section, articleSection) as stated |
| `page_metadata` | `list<struct<field dict,value string,format dict,path string,date date32,precision dict,resolved string,selected boolean,context_url string>>` | no | Publisher declarations with literal value, selection status and JSON Pointer into the pinned reading. Distinct literals for a field show a conflict. Declared addresses carry each qualifying capture URL and resolution against that address. A missing context or a detail size limit leaves resolutions empty. |
| `main_content` | `struct<outcome dict,selector string,text_sha256 string,text_bytes int32,snippet string,reader_version string,reading_status string,reason string,facts_limited boolean,text_available boolean,decision_id string,evidence_limited boolean>` | yes | Publisher-marked text preview and citation. Outcome distinguishes marked text, short marked text, fallback to the saved page, a failed reading, a recorded unreadable decision, exclusion, and an unattempted reading. The original body and reader version identify the source. The selector locates marked text. decision_id identifies a recorded unreadable decision. evidence_limited signals that the size limit omitted publisher evidence. |
| `selected_text` | `string` | yes | Bounded plain text from the cited marked element. Load only on request. Its SHA-256 and length are in main_content. The original remains available for larger or unselected pages. |
| `filename` | `string` | no | Displayed filename |
| `title` | `string` | yes | Document or publisher title when known |
| `document_kind` | `list<dict>` | no | Document kinds |
| `document_family` | `list<dict>` | no | Filename document families |
| `committee_keys` | `list<dict>` | no | Congress.gov committee system codes |
| `chambers` | `list<dict>` | no | Chambers associated with the document |
| `congress` | `int16` | yes | Congress number when unambiguous |
| `format` | `dict` | no | Original file format |
| `document_date` | `date32` | yes | Date of the document as read; detail.document_date_status says whether it is accepted or suspect |
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
- `publisher_labels[]`: Embedded declared section labels; not a key into another table.
- `page_metadata[]`: Embedded declared values with their JSON Pointer path into the pinned html_metadata reading; path is evidence, not a key. Reproduce it from saved_body with the release pin.
- `main_content`: Embedded reference to selected text. Verify selected_text with text_sha256 and find the marked element in saved_body with selector.

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
| `lookup_key` | `fixed[8]` | no | Exact address or serialization fallback lookup key in separate hash namespaces |
| `list_row` | `int32` | no | Zero-based row in list.parquet |

Nullability: Both columns are required by data model §8.1. A required column is refused at write time.

- `lookup_key`: Exact: first 8 SHA-256 bytes of lookup: plus fixed lookup_url(u): remove scheme, leading www, default port, fragment and one trailing path slash; lowercase host; preserve query bytes. Only after an exact miss, use lookup-alias:serialization-v1: plus that spelling with U+0020 serialized as %20 and valid percent triplets uppercased. Keep every matching edition. Both namespaces refuse different full hash inputs sharing eight bytes. This is not capture-profile url_key.

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
| `identity_note` | `string` | yes | Authored explanation of how the recovery relates to the original; null when the decision recorded none (kind still states the relationship) |

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
| `chamber_basis` | `string` | no | source if the meeting record supplies a chamber, source_chamber_unknown if the meeting record has no supported chamber, or meeting_detail_missing if only a document references the event. Earlier releases omit this field. |
| `title` | `string` | yes | Document or publisher title when known |
| `meeting_date` | `date32` | yes | Meeting date |
| `meeting_type` | `dict` | yes | Publisher meeting category |
| `session` | `int16` | yes | Congress session number |
| `status` | `dict` | yes | Selected publisher-reported meeting status; this does not itself prove a sitting |
| `sittings` | `list<struct<start timestamp,end timestamp,place string,room string,building string,address string>>` | no | Scheduled times and locations, as Congress.gov states them when it has a sitting |
| `committees` | `list<struct<system_code dict,role dict>>` | no | Host committee codes and roles |
| `subject_keys` | `list<dict>` | no | Bill, nomination and treaty subjects |
| `transcripts` | `list<struct<source dict,package_id string,list_row int32,formats list<string>,video_key string,language dict,production dict>>` | no | Every transcript the archive holds for the meeting, labelled by source: printed_hearing (a GPO print whose own MODS records the meeting, one per package: package_id, list_row of its preferred-format document, formats), committee_transcript (the committee's own transcript file, H{HRG,MKP,MTG}-<congress>-<committee>-Transcript-<meeting date>.pdf, linked to the meeting; list_row, formats), captions (a retained complete caption body or subtitle media playlist of the meeting's recording, never a stream segment; formats, video_key, language, production) |
| `videos` | `list<struct<name string,url string,video_key string>>` | no | Recorded meeting links |
| `congress` | `int16` | yes | Congress the publisher record states; null when no record states it, never inferred from documents |
| `congress_gov_updated` | `timestamp` | yes | Congress.gov's updateDate for this record: a publisher record update, distinct from the hearing date and capture time |
| `house_xml_updated` | `string` | yes | House XML update-date, literally as stated with no zone: a publisher record update, distinct from the hearing date and capture time |
| `congress_gov_meeting_type` | `dict` | yes | Congress.gov's type label (Hearing, Markup, Meeting) |
| `access` | `dict` | yes | open, closed, partly_closed or unknown, as the publisher type or title states |
| `access_basis` | `dict` | yes | The source and field that state access, such as congress_gov/title |
| `not_held` | `bool` | yes | Publisher status Canceled or Postponed, or the title opens with postponed, canceled or test; false where the meeting's own print was held that day under its title, or a curated read found the meeting's own recording of it on its date (status conflict, model/registries/meeting-status-conflicts.json); null with no record |
| `rescheduled_to` | `int64` | yes | Later meeting of the same committees and title, parts included, within 60 days that is not itself not held: when this meeting is not held, or has no recording, transcript file or witnesses of its own and either the publisher states Rescheduled or only the later twin has a recording; a hearing never moves to a markup; derived |
| `rescheduled_basis` | `dict` | yes | publisher_status or recording_on_later_twin |
| `document_references` | `list<struct<collection string, ordinal int32, url string, role string, format string, description string, name string>>` | yes | Congress.gov document links in source collection order. Null means the metadata is unavailable or unstated. An empty list means a supplied collection contained no links. |
| `publisher_status` | `string` | yes | Selected publisher-reported status, independent of the outcome |
| `publisher_status_observations` | `list<struct<source string,status string,meeting_date date32,record_sha string,observed_at timestamp>>` | yes | All retained publisher status observations, including conflicting statuses and dates; record_sha identifies raw evidence |
| `outcome` | `string` | yes | held, canceled or unknown on this event date; older releases omit outcome evidence |
| `outcome_basis` | `string` | yes | printed_hearing, committee_transcript, curated_source_review, publisher_cancellation or no_outcome_evidence |
| `outcome_source_reference` | `string` | yes | Print package ID, transcript list_row, or event ID with source observations/review |
| `outcome_reason` | `string` | yes | Evidence supporting outcome, or why the date-specific outcome remains unknown |
| `congress_gov_detail_observation` | `struct<state string,coverage string,successful_read struct<source_url string,retrieved_at timestamp,receipt_key string,receipt_line int32,capture_index int32,body_sha256 string,meeting_parser_version string,proof_parser_version string>,latest_attempt struct<evidence struct<source_url string,retrieved_at timestamp,receipt_key string,receipt_line int32,capture_index int32,body_sha256 string,meeting_parser_version string,proof_parser_version string>,state string,outcome string,http_status int32>,listing struct<source_url string,retrieved_at timestamp,receipt_key string,receipt_line int32,capture_index int32,body_sha256 string,meeting_parser_version string,proof_parser_version string>,has_undated_attempt boolean>` | no | Event-specific Congress.gov detail evidence. successful means an exact requested and final Congress/chamber/event detail route, successful receipt, and same-body selected meeting identity and qualified detail-only appearance reader. failed means recorded failures without a success or uncertain detail response. listing_only_in_scope means a proven listing and no detail success, failure or uncertain detail response in selected release inputs. unknown preserves missing or unqualified evidence. coverage is selected_release_inputs or unknown; it never claims complete acquisition history. successful_read and latest_attempt keep their own receipt and retrieval time; a later failure does not erase success. Among dated observations the latest is selected, then receipt locator breaks ties; has_undated_attempt marks attempts that cannot be ordered by time. Missing retrieval times stay null. Publisher update time remains congress_gov_updated. SpicyRegs journal recorded_at is separate and is not supplied by archive captures. |

Nullability: Nullability transcribes data model §8.1 (meetings.parquet row); access fields, not_held and rescheduling are null with no record, as their meanings state. List columns are empty, never null, except document_references. A required column is refused at write time.

- `sittings[]`: Embedded scheduled intervals and places. Congress.gov states instants and places, so its sitting is used when present; a House-only sitting's unzoned Eastern local time is converted to an instant. An explicit empty House state stays empty. Times retain published precision; do not invent a Congress from the session number.
- `committees[]`: Host/participant roles belong to this meeting-committee association.
- `transcripts[]`: One entry per GovInfo package. list_row is the package's listed document whose saved format ranks first (then lowest row); formats are the distinct saved and alternate formats over all the package's listed documents, in format-preference order. A package listed as several documents (editions) keeps one entry.
- `transcripts[].formats`: Format names (pdf, html, ...) the package is retained in, in format-preference order; values, not keys.
- `videos[]`: Publisher recording links; video_key joins retained recordings when available.
- `meeting_type`: As stated, with House XML codes (HHRG, HMKP, HMTG) on House rows; congress_gov_meeting_type carries the shared label.
- `document_references[].collection`: Source collection name, meetingDocuments or witnessDocuments. Witness documents are linked to this event without a witness identity claim.
- `document_references[].ordinal`: Zero-based occurrence within its source collection. Different references to the same URL keep their own values.
- `document_references[].url`: Publisher link. Use the existing document address lookup to find saved copies.
- `document_references[].role`: Publisher documentType. Null when omitted.
- `document_references[].format`: Publisher format, independent of the format of the saved body. Null when omitted.
- `publisher_status_observations[]`: Retained source statuses include their own meeting date and raw record identity; a changed date must not transfer a cancellation to another sitting.
- `congress_gov_detail_observation`: Evidence for the full Congress/chamber/event identity in selected release inputs only. Missing evidence stays unknown; this object does not certify complete acquisition history.
- `congress_gov_detail_observation.successful_read`: One qualified successful receipt and its response digest, retrieval time and selected reader versions. Nullable; retained independently of later failures.
- `congress_gov_detail_observation.latest_attempt`: One latest dated detail attempt and its raw outcome, HTTP status and qualification state. Undated attempts are signaled separately; ties use the receipt locator.
- `congress_gov_detail_observation.latest_attempt.evidence`: The attempt clock and locator are bound to the same capture. Receipt lines are one-based and capture indexes are zero-based; body digest and clocks may be null.
- `congress_gov_detail_observation.listing`: A bound successful listing route whose selected response supplied this meeting. A listing-only claim is confined to selected release inputs.

Outgoing: `meeting_bills`, `meeting_nominations`, `meeting_committees`, `meeting_transcript_documents`, `meeting_recordings`, `meeting_transcript_packages`, `meeting_video_address`, `meeting_treaties`.

Incoming: `document_meetings`, `recording_meetings`, `witness_meeting`, `match_meeting`, `match_meeting_associations`, `committee_record_meeting`, `coverage_meeting`.

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
| `witness_type` | `dict` | yes | Source witness classification; for GovInfo prints, statement_for_record or member_statement marks an entry that is a statement, not a witness |
| `testified` | `boolean` | yes | Whether the witness testified |
| `bioguide_id` | `dict` | yes | Bioguide identifier when the witness is a Member of Congress |
| `superseded_by` | `string` | yes | witness_key of the same person stated on the same meeting by a higher-ranked source (source priority, then record); null for the row to show |

Nullability: Nullability transcribes the phase-2 annex §3 file table (docs/plans/phase-2-annex-20261028.md): a type without "nullable" there is required. A required column is refused at write time.

- `occasion`: meeting:{event_id}, package:{package_id}, or page:{sha256_prefix}. Witness keys hash the occasion, source, record_sha, source_locator, and context_key; names alone never join or deduplicate appearances.

Outgoing: `witness_meeting`, `witness_transcript_documents`, `witness_member`, `witness_package`, `witness_page`.

Incoming: `witness_submitted_documents`, `witness_key_map_successor`, `witness_key_map_candidates`.

## `witness_key_map` — Earlier witness keys and the current witness each resolves to

One witness key this release no longer publishes, with its successor, its candidates, or neither.

Identity: `old_key` (primary_key; published identifier).

Coverage: Derived from earlier bodies the lake still holds, not from earlier releases: a key published only from a body no longer held has no row.

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `old_key` | `string` | no | A witness_key that an earlier body or capture context held for an occasion produces and this release does not publish in witnesses |
| `witness_key` | `string` | yes | The current witnesses.witness_key the old key resolves to; null when status is ambiguous or unresolved |
| `status` | `dict` | no | unambiguous (one successor), ambiguous (several candidates, listed in candidate_keys, none chosen) or unresolved (no candidate) |
| `basis` | `dict` | yes | The strongest evidence found: occurrence (the same body and locator, published under another occasion or capture context), content (the same occasion, source and print, with an equal name and equal other attributes, at least one of them stated or the same locator; repeats of one person pair in list order) or locator (the same locator, occasion, source and print, an edited name of the same family and given name, every other attribute equal and a position, organization or Bioguide ID stated); null when unresolved |
| `candidate_keys` | `list<string>` | no | With status ambiguous: the current witness keys the old key could resolve to, sorted; empty otherwise |
| `occasion` | `dict` | no | The occasion the old key's body is filed under in this release (meeting:{event_id}, package:{package_id}, or page:{sha256_prefix}) |
| `source` | `dict` | no | Observation source family of the old key (house_xml, congress_gov, senate_page, or mods) |

Nullability: witness_key is set exactly when status is unambiguous; basis is null exactly when status is unresolved (ct-kb4w). A required column is refused at write time.

- `old_key`: Disjoint from witnesses.witness_key. A re-fetched body, a newly bound capture context, or a meeting link that moves a print or Senate page off its package or page occasion gives each witness a new key (witness-occurrence-v2 is unchanged); the earlier keys are listed here. A name alone never maps (ct-30fp).
- `witness_key`: The successor can itself be superseded_by a higher-ranked row of the same person; follow witnesses.superseded_by to the row to show.

Outgoing: `witness_key_map_successor`, `witness_key_map_candidates`.

Incoming: none.

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

Incoming: `meeting_recordings`, `caption_resource_recording`.

## `caption_resources` — Archived caption roots and ordered playlist resources

One selected caption root or declared child, including a missing child.

Identity: `video_key, track_body, ordinal` (primary_key; published identifier).

Coverage: Only selected retained caption roots and their direct subtitle media-playlist segments; unsupported HLS features remain explicit at read time..

Coverage: Retained does not mean the body was verified by this reader, nor does a live playlist snapshot establish a complete hearing..

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `video_key` | `string` | no | Recording whose selected caption track owns this resource |
| `track_body` | `fixed[32]` | no | Selected caption track root body digest |
| `ordinal` | `int64` | no | Zero for the root; one-based playlist declaration order for each segment |
| `source_url` | `string` | no | Original root fetch address or child URI resolved in that root context; never an archive fetch target |
| `declared_uri` | `string` | yes | Literal child URI in the retained playlist; null for a root |
| `body` | `fixed[32]` | yes | Retained resource body digest; null when the declared resource is missing |
| `suffix` | `dict` | yes | Content-addressed archive storage suffix |
| `format` | `dict` | yes | Retained resource format |
| `parser_version` | `string` | yes | Pinned playlist reading that declared the ordered child resources; null for direct caption files |
| `status` | `dict` | no | retained or missing; missing declarations remain rows |

Nullability: Root identity and source URL are required. Missing children have null body/suffix/format. Declared URI is null only for roots; direct caption files have no playlist parser version. A required column is refused at write time.


Outgoing: `caption_resource_recording`.

Incoming: none.

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

Incoming: `document_members`, `witness_member`, `roster_member`, `bill_sponsor`, `amendment_sponsor`, `committee_record_sponsor`, `ballot_member`.

## `rosters` — Committee and subcommittee seats across published Congresses

One member assignment to a committee or subcommittee in a Congress (keyed by congress, system_code, bioguide_id; only Congresses populated in the pinned upstream committee_assignments snapshot appear; congress_basis and edition_date say which source and date state it).

Identity: `congress, system_code, bioguide_id` (primary_key; published identifier).

Coverage: Committee seats cover only the Congresses populated in the pinned upstream committee_assignments snapshot; congress_start and congress_end bound the published Congresses, and any Congress without roster rows, including every Congress when both are null, is unavailable, not zero seats.

Coverage: A seat from a Congressional Directory edition (congress_basis directory or directory-manual) is one dated printed snapshot (edition_date): changes during that Congress are invisible, ex officio members appear only where printed, and a list printed after a member left keeps that member (entry_label after_departure).

Coverage: A Ranking Member with position_basis inferred is the first minority-column entry of a list printing no minority leader, not a stated title.

Coverage: Printed directory entries that are not seats (vacancies, party organizations, unread lines) are not in this release; they are SpicyRegs committee_directory_entries rows.

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `congress` | `int16` | no | Congress number for the committee assignment |
| `system_code` | `dict` | no | Lowercase committee or subcommittee system code |
| `bioguide_id` | `dict` | no | Assigned member Bioguide identifier |
| `title` | `dict` | yes | Committee leadership or seat position title |
| `rank` | `int16` | yes | Numeric party rank on the committee |
| `party` | `dict` | yes | Party caucus for the committee assignment |
| `congress_basis` | `dict` | yes | Where the seat's Congress comes from: file (the House roster file states it), caller (the Senate file states none), directory (a Congressional Directory edition's package metadata) or directory-manual (a reviewed one-off reading of an edition's PDF) |
| `edition_date` | `date32` | yes | For a directory seat, the edition's dateIssued: the date the printed roster describes |
| `source_granule` | `string` | yes | The GovInfo directory granule (or, for a manual reading, package; for an archived chamber file, its Internet Archive URL) that states the seat |
| `source_line` | `string` | yes | The granule text line where the printed entry starts; for a manual reading, PDF page:line |
| `position_basis` | `dict` | yes | For a directory seat with a title: printed, or inferred for a Ranking Member taken from print position (the first minority-column entry) |
| `printed_entry` | `string` | yes | For a directory seat, the entry as printed (name and state), kept when a value was corrected |
| `entry_label` | `dict` | yes | For a directory seat: corrected (a printed name, state or column was corrected; printed_entry keeps it), after_departure (printed after the member left) or no_congress_gov_code (the body has no Congress.gov code) |

Nullability: Nullability transcribes the phase-2 annex §3 file table (docs/plans/phase-2-annex-20261028.md): a type without "nullable" there is required. A required column is refused at write time.

- `congress`: Keyed by (congress, system_code, bioguide_id); populated from the pinned upstream committee_assignments snapshot, whose populated Congresses the coverage congress_start and congress_end bound. Earlier Congresses appear only after an upstream backfill is pinned.
- `party`: Preserves the supplied assignment party; missing or blank values stay null. Service-term party assertions do not establish party or caucus at a roster observation, and the input does not supply qualified dated affiliation history.
- `congress_basis`: Earlier Congresses' seats come from one Congressional Directory edition per Congress (directory). A Congress whose edition serves no committee granules combines a reviewed reading of the edition's PDF (directory-manual) with Internet Archive captures of the House file (file) and the Senate file (caller); a seat both list is the chamber file's. The current Congress comes from the current chamber files.
- `title`: Chamber-file titles are verbatim (Chairman, Ranking Member); directory titles are normalized (Chair, Vice Chair, Ranking Member).
- `system_code`: hsba00-tf-terrorism-financing is directory-defined: that House Financial Services task force has no Congress.gov code; its committees row is synthesized with parent hsba00.

Outgoing: `roster_committee`, `roster_member`.

Incoming: none.

## `bills` — Referenced bills and embedded legislative facts

One bill referenced by documents, meetings, or committee activities, or a substantive/enacted bill (congress >= 113), plus 1-hop related bills of referenced bills; bounded by upstream retained data.

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
| `public_law_number` | `string` | yes | Enacted Public Law number (e.g. 118-50) when enacted |
| `cosponsor_count` | `int32` | yes | Published cosponsor count |
| `related_bills` | `list<struct<bill_id string,title string,relationship_types list<dict>>>` | no | Related, companion, and vehicle measures linked to this bill |
| `committees` | `list<dict>` | no | Referred committee system codes |
| `cbo_estimates` | `list<struct<publication_id string,date date32,description string>>` | no | CBO cost estimates associated with the bill |
| `floor_votes` | `list<struct<vote_id string,basis dict,chamber dict,date date32,question string,result string,yea int16,nay int16>>` | no | Roll-call votes tied by vote record or bill action |
| `amendments` | `list<struct<amendment_id string,purpose string,sponsor_bioguide_id dict,latest_action_date date32,latest_action_text string>>` | no | Direct and chained amendments to the bill |
| `committee_activities` | `list<struct<system_code dict,activity dict,date date32>>` | no | Committee referral, markup, and report activities |
| `subjects` | `list<string>` | yes | Published Congress.gov legislative subject labels; null means unavailable and empty means no labels supplied |
| `source_updated_at` | `string` | yes | Literal Congress.gov update_date; a publisher update, not an action date |
| `source_update_including_text` | `string` | yes | Literal Congress.gov update_date_including_text |

Nullability: Nullability transcribes the phase-2 annex §3 file table (docs/plans/phase-2-annex-20261028.md): a type without "nullable" there is required. A required column is refused at write time.

- `related_bills[]`: Embedded related, companion, and omnibus vehicle measures with canonical bill_id, title, and relationship_types.
- `related_bills[].relationship_types[]`: Embedded Congress.gov relationship labels, not foreign keys.
- `cbo_estimates[]`: Embedded publication IDs, dates and descriptions, not full CBO estimate text.
- `floor_votes[]`: One embedded vote per vote_id per bill; basis distinguishes vote_record from bill_action. Counts are vote totals, not member positions.
- `amendments[]`: Embedded direct/chained amendment summaries; 119th Congress coverage until upstream backfill.
- `committee_activities[]`: Embedded committee events; several activities can refer to the same committee.
- `subjects[]`: Published legislative subject labels, independent of policy_area; no title-keyword inference.

Outgoing: `bill_sponsor`, `amendment_sponsor`, `bill_activity_committee`, `bills_committees`, `bills_votes`, `bill_cbo_publications`, `bill_amendments`.

Incoming: `document_bills`, `meeting_bills`, `bill_action_bill`, `roll_call_bill`.

## `nominations` — Referenced nominations and embedded legislative facts

One nomination including its part when present, referenced by archive documents or meetings; bounded by upstream retained data.

Identity: `nomination_id` (primary_key; published identifier).

Coverage: Nominations cover the 119th Congress only until spicy-regs backfills.

Coverage: Local nomination profiles include only nominations referenced by published archive documents or meetings; other retained upstream nominations are outside this collection.

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `nomination_id` | `string` | no | Canonical nomination identifier ({congress}-pn-{number}[-{part}]) |
| `description` | `string` | yes | Nomination description |
| `organization` | `string` | yes | Executive or independent agency name |
| `received` | `date32` | yes | Date received in the Senate |
| `latest_action_date` | `date32` | yes | Date of latest action |
| `latest_action_text` | `string` | yes | Text of latest action |
| `committees` | `list<dict>` | no | Referred Senate committee system codes |
| `committee_activities` | `list<struct<system_code string, activities list<struct<name string, date string>>>>` | yes | Committee groups and activity names and dates as supplied, in source order. Null means unavailable or unstated. An empty list means the source supplied no entries. |
| `transcripts` | `list<string>` | no | Printed hearing package IDs from nomination hearing references |
| `floor_votes` | `list<struct<vote_id string,date date32,question string,result string,yea int16,nay int16>>` | no | Senate roll-call votes on the nomination |
| `source_updated_at` | `string` | yes | Literal Congress.gov update_date; a publisher update, not the latest action date |

Nullability: Nullability transcribes the phase-2 annex §3 file table, except description: upstream military promotion lists carry no description (in the pinned spicy-regs nominations generation, 1,349 of its 1,363 rows without one are military), so it is nullable, a legitimate upstream gap rather than a mapping loss. A required column is refused at write time.

- `floor_votes[]`: Embedded Senate roll-call summaries; no individual member positions.
- `transcripts[]`: GovInfo CHRG package identifiers; a retained transcript can have multiple document formats or editions.
- `committee_activities[].activities[].date`: Exact source date or timestamp string, including offset and precision. Null when missing.
- `committee_activities[].activities`: Null when not supplied or unreadable, empty when the source supplied an empty list.

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
| `recheck_meeting_date` | `date32` | yes | Meeting date the recheck band was aged against: the address's earliest linked meeting, else the date in its docs.house.gov /meetings/ path; null when neither is known (the family's shortest band applies) and on a queued row |
| `linked_from` | `list<fixed[8]>` | no | Every read page that links a queued address, as page keys (the first 8 bytes of the page body's SHA-256, the link-key form) in key order; empty on an address with attempts |

Nullability: Nullability transcribes data model §7.7. A required column is refused at write time.

- `requested_url`: Exact scheduled address. Missing success is not missing publication; this is operational capture state, not an entity or document catalogue.
- `linked_from`: A page key resolves in links.parquet only when the page is itself a listed document; wrapper and listing pages are kept as evidence, not listed. Published, with recheck_meeting_date, so the release gate can trace a scheduling change to the receipts that caused it (ct-9j3z).

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

Coverage: Historical package matcher scores are available separately when historical_recording_matches is published.

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `match_id` | `string` | no | Hex SHA-256 of the compact JSON [subject_kind, subject_id, video ref, basis] |
| `subject_kind` | `dict` | no | event or package |
| `subject_id` | `string` | no | Original subject identifier, including a stated event number without a meeting |
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
| `meeting_links` | `list<struct<event_id int64, basis dict, scope dict>>` | no | Supported meeting links ordered by event ID. Empty means no supported link. Absent on older releases. |

Nullability: The documents are silent; decided from the row meaning: the key and the fields that define the row are required, descriptive fields from upstream records can be absent, and list columns are empty, never null. A required column is refused at write time.

- `meeting_links[].basis`: direct_event for the observation’s stated event or print_agreement for vetted printed-hearing evidence.
- `meeting_links[].scope`: event identifies the subject of the observation. package_context supplies related evidence without establishing coverage for a sitting.

Outgoing: `match_meeting`, `match_meeting_associations`, `match_recording`.

Incoming: none.

## `historical_recording_matches` — Retained package-level scores, methods and observations from the historical recording matcher

One original CSV record from one exact historical matcher snapshot.

Identity: `source_snapshot_sha256, source_record_ordinal` (primary_key; input snapshot and physical data record).

Coverage: Historical package observations do not assign recordings to individual hearings or update meeting coverage..

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `package_id` | `string` | no | Government Publishing Office package identifier as supplied |
| `congress` | `string` | no | Congress as supplied |
| `chamber` | `string` | no | Chamber as supplied |
| `committee_code` | `string` | no | Committee code as supplied |
| `held_date` | `string` | no | Held date as supplied |
| `hearing_dates` | `string` | no | Additional hearing dates as supplied |
| `record_type` | `string` | no | Publication record type as supplied |
| `status` | `string` | no | Original matcher status; a negative status does not establish checked absence |
| `video_ids` | `string` | no | Original video identifiers or URLs in their supplied order and spacing |
| `channels` | `string` | no | Original channel text |
| `method` | `string` | no | Original package-level method text, which can name several methods |
| `score` | `int16` | yes | Original aggregate package score; null means blank. Zero is a supplied score |
| `video_minutes` | `string` | no | Original duration text |
| `flags` | `string` | no | Original flags text |
| `source` | `string` | no | Original matcher or research source label |
| `note` | `string` | no | Original note text |
| `source_snapshot_sha256` | `string` | no | SHA-256 of the exact input CSV |
| `source_record_ordinal` | `int64` | no | One-based CSV data record ordinal, excluding the header |

Nullability: A blank score becomes null. Other empty CSV fields remain empty strings. A required column is refused at write time.


Outgoing: none.

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
| `reason` | `dict` | yes | Why a state holds, when known: recording_decision_unresolved_or_conflicting, package_context_only, video_text_only, excerpts_only, stated_documents_not_held, senate_page_links_pending, package_witnesses_unattached, package_names_meeting_unlinked, recording_link_pending or recording_without_video_record; for a present transcript, the sources held (printed_hearing, committee_transcript, captions) |

Nullability: The documents are silent; entity-meeting-coverage.sql always sets basis (a CASE with an else) and count (coalesced), so both are required; reason is stated only when known. A required column is refused at write time.

- `state`: confirmed_absent only from an undisputed curated negative verdict with event scope; package context alone does not establish absence and zero rows never prove absence. partial means excerpts only; claimed means only a video’s own text; for captions, no observation is unknown, never empty. States rank present > unresolved > empty > unknown > not_stated: unknown, never not_stated, where held evidence is not yet linked. A Senate meeting is unknown for documents and witnesses until Senate committee-page links land (ct-gi01 R2). Captions are not_stated only when the recording is confirmed_absent or not_public.

Outgoing: `coverage_meeting`.

Incoming: none.

## `bill_actions` — Recorded bill actions and derived stages

One retained upstream row; no filter to local bill profiles.

Identity: `bill_id, action_index` (primary_key; published identifier).

Coverage: All rows of the selected upstream generation; publisher collection completeness is not established..

Coverage: Action dates and member vote dates preserve source spelling and precision; voice votes are actions, never individual ballots..

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `bill_id` | `string` | no | Literal selected upstream bill_actions.bill_id |
| `action_index` | `int64` | no | Literal selected upstream bill_actions.action_index |
| `action_date` | `string` | yes | Literal selected upstream bill_actions.action_date |
| `action_time` | `string` | yes | Literal selected upstream bill_actions.action_time |
| `action_text` | `string` | yes | Literal selected upstream bill_actions.action_text |
| `action_code` | `string` | yes | Literal selected upstream bill_actions.action_code |
| `action_type` | `string` | yes | Literal selected upstream bill_actions.action_type |
| `source_system_name` | `string` | yes | Literal selected upstream bill_actions.source_system_name |
| `recorded_vote_count` | `int64` | yes | Literal selected upstream bill_actions.recorded_vote_count |
| `is_latest_action` | `bool` | yes | Literal selected upstream bill_actions.is_latest_action |
| `stage` | `string` | yes | Literal selected upstream bill_actions.stage |
| `source_generation` | `string` | no | Exact selected SpicyRegs family generation digest |
| `source_reference` | `string` | no | Selected upstream Parquet path; identify a source row using this table primary key |

Nullability: Only source primary keys and release provenance are required; missing source values stay null. A required column is refused at write time.


Outgoing: `bill_action_bill`.

Incoming: none.

## `roll_call_votes` — Full roll calls, including votes outside local bill profiles

One retained upstream row; no filter to local bill profiles.

Identity: `vote_id` (primary_key; published identifier).

Coverage: All rows of the selected upstream generation; publisher collection completeness is not established..

Coverage: member_key remains authoritative when bioguide_id is missing; vote totals do not imply recorded individual ballots..

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `vote_id` | `string` | no | Literal selected upstream roll_call_votes.vote_id |
| `congress` | `string` | yes | Literal selected upstream roll_call_votes.congress |
| `chamber` | `string` | yes | Literal selected upstream roll_call_votes.chamber |
| `session` | `string` | yes | Literal selected upstream roll_call_votes.session |
| `roll_number` | `string` | yes | Literal selected upstream roll_call_votes.roll_number |
| `vote_date` | `string` | yes | Literal selected upstream roll_call_votes.vote_date |
| `question` | `string` | yes | Literal selected upstream roll_call_votes.question |
| `result` | `string` | yes | Literal selected upstream roll_call_votes.result |
| `yea` | `int64` | yes | Literal selected upstream roll_call_votes.yea |
| `nay` | `int64` | yes | Literal selected upstream roll_call_votes.nay |
| `present` | `int64` | yes | Literal selected upstream roll_call_votes.present |
| `not_voting` | `int64` | yes | Literal selected upstream roll_call_votes.not_voting |
| `tallies` | `list<struct<choice string,count int64>>` | yes | Literal selected upstream roll_call_votes.tallies |
| `member_vote_count` | `int64` | yes | Literal selected upstream roll_call_votes.member_vote_count |
| `bill_id` | `string` | yes | Literal selected upstream roll_call_votes.bill_id |
| `tally_kind` | `string` | yes | Literal selected upstream roll_call_votes.tally_kind |
| `documents` | `list<struct<congress int64,name string,number string,short_title string,title string,type string>>` | yes | Literal selected upstream roll_call_votes.documents |
| `amendments` | `list<struct<number string,purpose string,to_amendment_number string,to_amendment_to_amendment_number string,to_document_number string,to_document_short_title string>>` | yes | Literal selected upstream roll_call_votes.amendments |
| `vote_day` | `string` | yes | Literal selected upstream roll_call_votes.vote_day |
| `legis_num` | `string` | yes | Literal selected upstream roll_call_votes.legis_num |
| `clerk_body_element` | `string` | yes | Literal selected upstream roll_call_votes.clerk_body_element |
| `vote_desc` | `string` | yes | Literal selected upstream roll_call_votes.vote_desc |
| `vote_question_text` | `string` | yes | Literal selected upstream roll_call_votes.vote_question_text |
| `vote_title` | `string` | yes | Literal selected upstream roll_call_votes.vote_title |
| `majority_requirement` | `string` | yes | Literal selected upstream roll_call_votes.majority_requirement |
| `modify_date` | `string` | yes | Literal selected upstream roll_call_votes.modify_date |
| `tie_breaker_by_whom` | `string` | yes | Literal selected upstream roll_call_votes.tie_breaker_by_whom |
| `tie_breaker_vote` | `string` | yes | Literal selected upstream roll_call_votes.tie_breaker_vote |
| `party_totals` | `list<struct<party string,yea-total int64,nay-total int64,present-total int64,not-voting-total int64>>` | yes | Literal selected upstream roll_call_votes.party_totals |
| `source_generation` | `string` | no | Exact selected SpicyRegs family generation digest |
| `source_reference` | `string` | no | Selected upstream Parquet path; identify a source row using this table primary key |
| `bill_references` | `list<struct<bill_id string,action_index int64,congress string,chamber string,session string,roll_number string,date string,full_action_name string,source_generation string,source_reference string>>` | yes | All pinned bill-action references matching this roll call by congress/chamber/session/roll number; null means no matching source reference. Raw bill_id remains separate. |

Nullability: Only source primary keys and release provenance are required; missing source values stay null. A required column is refused at write time.

- `tallies[]`: Literal nested upstream values; source order and missing fields are preserved.
- `documents[]`: Literal nested upstream values; source order and missing fields are preserved.
- `amendments[]`: Literal nested upstream values; source order and missing fields are preserved.
- `party_totals[]`: Literal nested upstream values; source order and missing fields are preserved.
- `bill_references[]`: Source associations retain their action_index, literal date and bill-family generation/path. The vote itself belongs to roll-call-votes. A referenced bill may be absent from local bill profiles.

Outgoing: `roll_call_bill`.

Incoming: `ballot_roll_call`.

## `member_votes` — Individual recorded member ballots

One retained upstream row; no filter to local bill profiles.

Identity: `vote_id, member_key` (primary_key; published identifier).

Coverage: All rows of the selected upstream generation; publisher collection completeness is not established..

Coverage: member_key remains authoritative when bioguide_id is missing; vote totals do not imply recorded individual ballots..

| Field | Published type | Nullable | Meaning |
| --- | --- | --- | --- |
| `vote_id` | `string` | no | Literal selected upstream member_votes.vote_id |
| `congress` | `string` | yes | Literal selected upstream member_votes.congress |
| `chamber` | `string` | yes | Literal selected upstream member_votes.chamber |
| `session` | `string` | yes | Literal selected upstream member_votes.session |
| `roll_number` | `string` | yes | Literal selected upstream member_votes.roll_number |
| `member_key` | `string` | no | Literal selected upstream member_votes.member_key |
| `bioguide_id` | `string` | yes | Literal selected upstream member_votes.bioguide_id |
| `lis_id` | `string` | yes | Literal selected upstream member_votes.lis_id |
| `member_name` | `string` | yes | Literal selected upstream member_votes.member_name |
| `party` | `string` | yes | Literal selected upstream member_votes.party |
| `state` | `string` | yes | Literal selected upstream member_votes.state |
| `position` | `string` | yes | Literal selected upstream member_votes.position |
| `position_normalized` | `string` | yes | Literal selected upstream member_votes.position_normalized |
| `vote_date` | `string` | yes | Literal selected upstream member_votes.vote_date |
| `source_generation` | `string` | no | Exact selected SpicyRegs family generation digest |
| `source_reference` | `string` | no | Selected upstream Parquet path; identify a source row using this table primary key |

Nullability: Only source primary keys and release provenance are required; missing source values stay null. A required column is refused at write time.


Outgoing: `ballot_roll_call`, `ballot_member`.

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

`rosters.system_code` → `committees.system_code`. Committee or subcommittee assignment for the roster row's Congress.

many-to-one; match: `equal`; nullable: false; resolution: `unresolved_allowed`. Scope: rosters.congress (Congresses populated in the pinned committee_assignments snapshot).

### `roster_member`

`rosters.bioguide_id` → `members.bioguide_id`. Assigned member for the roster row's Congress.

many-to-one; match: `equal`; nullable: false; resolution: `unresolved_allowed`. Scope: rosters.congress (Congresses populated in the pinned committee_assignments snapshot).

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

### `witness_key_map_successor`

`witness_key_map.witness_key` → `witnesses.witness_key`. The current appearance an earlier witness key resolves to; a saved link to the old key opens this row.

many-to-one; match: `equal`; nullable: true; resolution: `required`. Scope: selected release.

### `witness_key_map_candidates`

`witness_key_map.candidate_keys[]` → `witnesses.witness_key`. Current appearances an ambiguous earlier key could resolve to; none is chosen.

many-to-many; match: `equal`; nullable: true; resolution: `required`. Scope: selected release.

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

`recording_matches.event_id` → `meetings.event_id`. The original event subject when the number resolves to a meeting.

many-to-one; match: `equal`; nullable: true; resolution: `required`. Scope: selected release.

### `match_meeting_associations`

`recording_matches.meeting_links[].event_id` → `meetings.event_id`. Meetings linked by the observation’s direct event evidence or by print agreement. See basis and scope before drawing conclusions about a sitting.

many-to-many; match: `equal`; nullable: false; resolution: `required`. Scope: selected release.

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

### `bill_action_bill`

`bill_actions.bill_id` → `bills.bill_id`. Exact published source key; missing profile rows remain unresolved.

many-to-one; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: All selected detail rows, including subjects outside local profiles.

### `roll_call_bill`

`roll_call_votes.bill_id` → `bills.bill_id`. Exact published source key; missing profile rows remain unresolved.

many-to-one; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: All selected detail rows, including subjects outside local profiles.

### `ballot_roll_call`

`member_votes.vote_id` → `roll_call_votes.vote_id`. Exact published source key; missing profile rows remain unresolved.

many-to-one; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: All selected detail rows, including subjects outside local profiles.

### `ballot_member`

`member_votes.bioguide_id` → `members.bioguide_id`. Exact published source key; missing profile rows remain unresolved.

many-to-one; match: `equal`; nullable: true; resolution: `unresolved_allowed`. Scope: All selected detail rows, including subjects outside local profiles.

### `caption_resource_recording`

`caption_resources.video_key` → `recordings.video_key`. The recording that owns the selected root and its ordered archived children.

many-to-one; match: `equal`; nullable: false; resolution: `required`. Scope: selected release.

## Pinned upstream relations

These are upstream source relations. A release names a relation’s generation and path only when it states that family’s digest. Locally published detail tables are listed above; a source pin alone does not make its rows locally queryable.

| Relation | Family and table | Keys | Local joins | Row | Limits |
| --- | --- | --- | --- | --- | --- |
| `bill_actions` | `bill-family/bill_actions` | `bill_id` | `bills.bill_id` | One recorded action on a bill | This release publishes all selected upstream rows in bill_actions.parquet when that local table is available; generation metadata alone does not establish local availability. |
| `bill_cosponsors` | `bill-family/bill_cosponsors` | `bill_id, bioguide_id` | `bills.bill_id`, `members.bioguide_id` | One cosponsorship | bills does not carry cosponsors. |
| `member_votes` | `roll-call-votes/member_votes` | `vote_id, member_key` | `bills.floor_votes[].vote_id`, `nominations.floor_votes[].vote_id`, `members.bioguide_id` | One member ballot | This release publishes all selected upstream rows in member_votes.parquet when that local table is available; generation metadata alone does not establish local availability. |
| `roll_call_votes` | `roll-call-votes/roll_call_votes` | `vote_id` | `bills.floor_votes[].vote_id`, `nominations.floor_votes[].vote_id` | One roll-call vote | This release publishes all selected upstream rows in roll_call_votes.parquet when that local table is available; generation metadata alone does not establish local availability. |
| `amendments` | `amendments/amendments` | `amendment_id` | `bills.amendments[].amendment_id` | One floor amendment | Coverage is limited by upstream; committee_records holds different, committee-stage documents. |
| `nominations` | `nominations/nominations` | `congress, number, part_number` | none | One nomination part | This pin describes the retained upstream source. The local nominations table includes only nominations referenced by published archive documents or meetings, so upstream rows can lack a local profile. |
| `committee_assignments` | `committee-rosters/committee_assignments` | `congress, system_code, bioguide_id` | `rosters.system_code`, `members.bioguide_id` | One committee assignment | Schema supports 113th–119th Congress committee and subcommittee assignments; populated only for the Congresses the pinned generation holds, which rosters.parquet coverage congress_start and congress_end bound. Directory seats are dated snapshots (edition_date). |

## Query recipes (DuckDB)

### `bill_documents` — Documents directly annotated with a bill

Requires: `list`, `detail`.

Result: One document edition.

Parameters, in order: `bill_id` (example `119-hr-1`).

```sql
SELECT l.list_row,l.filename,l.title,lower(hex(d.link_key)) AS link_key
FROM "list" l JOIN detail d USING (list_row)
WHERE NOT coalesce(l.hidden,false) AND list_contains(l.measure_keys,?) ORDER BY l.list_row LIMIT 100
```

Matches direct list.measure_keys annotations only. Use bill_hearing_transcripts for transcripts linked through meeting subjects.

Does not require the bounded bills table to contain this identifier. Hidden rows are excluded; remove NOT coalesce(l.hidden,false) to include them.

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
SELECT l.list_row,l.filename,l.title,lower(hex(d.link_key)) AS link_key,matched.meeting_ids
FROM matched JOIN "list" l USING (list_row) JOIN detail d USING (list_row)
WHERE NOT coalesce(l.hidden,false) ORDER BY l.list_row LIMIT 100
```

Follows meetings.subject_keys and meetings.transcripts[].list_row even when the document has no direct measure_keys annotation.

Repeated paths and multiple meetings produce one row per document. Supporting meetings explain the association; they do not establish witness participation or historical completeness.

Does not require the bounded bills table to contain this identifier. Missing required tables mean unavailable, not an empty complete result.

Returns at most 100 documents in list_row order. Use list_row filtering for further pages; query_sql also enforces its row and byte limits.

### `hearing_documents` — Documents and hearing titles

Requires: `list`, `detail`, `meetings`.

Result: One document associated with the selected hearing.

Parameters, in order: `event_id` (example `335321`).

```sql
SELECT l.list_row,l.filename,l.title,lower(hex(d.link_key)) AS link_key,m.event_id,m.title AS hearing
FROM "list" l JOIN detail d USING (list_row) JOIN meetings m ON list_contains(l.meeting_keys,CAST(m.event_id AS VARCHAR))
WHERE NOT coalesce(l.hidden,false) AND m.event_id=? ORDER BY l.list_row LIMIT 100
```

meeting_keys stores decimal text; event_id is an integer.

### `hearing_dossier` — One-row hearing dossier with witnesses, documents, and recordings

Requires: `meetings`, `witnesses`, `list`, `detail`, `recording_matches`.

Result: One hearing with embedded witnesses, visible documents, and recording matches.

Parameters, in order: `event_id` (example `335321`).

```sql
SELECT m.event_id,m.chamber,m.meeting_date,m.title,m.committees,m.subject_keys,m.transcripts,
  coalesce((SELECT list(struct_pack(witness_key:=w.witness_key,name:=w.name,position:=w.position,organization:=w.organization,panel:=w.panel,display_order:=w.display_order) ORDER BY w.panel_order NULLS LAST,w.display_order NULLS LAST,w.witness_key) FROM witnesses w WHERE w.event_id=m.event_id AND w.superseded_by IS NULL),[]) AS witnesses,
  coalesce((SELECT list(struct_pack(list_row:=l.list_row,filename:=l.filename,title:=l.title,document_kind:=l.document_kind,link_key:=lower(hex(d.link_key))) ORDER BY l.list_row) FROM "list" l JOIN detail d USING (list_row) WHERE NOT coalesce(l.hidden,false) AND list_contains(l.meeting_keys,CAST(m.event_id AS VARCHAR))),[]) AS documents,
  coalesce((SELECT list(r ORDER BY r.match_id) FROM (
   SELECT match_id,subject_kind,subject_id,event_id,package_id,video_key,url,basis,decision,score,recording_scope,status,note,source_ref,
    list_filter(meeting_links,lambda l:l.event_id=m.event_id) AS meeting_links
   FROM recording_matches
   WHERE list_contains(list_transform(meeting_links,lambda l:l.event_id),m.event_id)
   ORDER BY match_id LIMIT 100
  ) r),[]) AS recordings
FROM meetings m WHERE m.event_id=?
```

Uses correlated subqueries with coalesce(..., []) so nested lists do not Cartesian-multiply rows or drop zero-child hearings.

Uses m.event_id inside each subquery so only one ? parameter is required.

Lists current appearances only (superseded_by IS NULL); each superseded row restates the same person from a lower-ranked source.

Each recording observation appears once with its matching meeting links. Check association scope separately from recording scope.

### `witness_documents` — Documents submitted by a witness appearance

Requires: `list`, `detail`, `witnesses`.

Result: One submitted document for this appearance.

Parameters, in order: `witness_key` (example `0001497931f99cd1`).

```sql
SELECT w.witness_key,w.name,l.list_row,l.filename,l.title,lower(hex(d.link_key)) AS link_key
FROM witnesses w JOIN "list" l ON list_contains(l.witness_keys,w.witness_key) JOIN detail d USING (list_row)
WHERE NOT coalesce(l.hidden,false) AND w.witness_key=? ORDER BY l.list_row LIMIT 100
```

Use a witness_key, never a person-name join.

Returns documents annotated with exactly this witness_key; pass the current appearance (superseded_by IS NULL) from hearing_dossier or witnesses.

### `witness_transcripts` — Printed hearings containing a witness appearance

Requires: `witnesses`, `detail`, `list`.

Result: One retained transcript document for the appearance.

Parameters, in order: `witness_key` (example `0000b43c099edbc2`).

```sql
WITH w AS (SELECT witness_key,name FROM witnesses WHERE witness_key=?),
  packages AS (SELECT DISTINCT p.package_id FROM witnesses p, w WHERE p.package_id IS NOT NULL AND (p.witness_key=w.witness_key OR p.superseded_by=w.witness_key))
SELECT w.witness_key,w.name,d.package_id,l.list_row,l.filename,l.title,lower(hex(d.link_key)) AS link_key
FROM w, packages k JOIN detail d ON d.package_id=k.package_id JOIN "list" l USING (list_row)
WHERE NOT coalesce(l.hidden,false) ORDER BY l.list_row LIMIT 100
```

No package_id on the appearance or on the rows it supersedes means no published package association; submitted documents use a different relationship.

Follows superseded_by: a current appearance from a source without package_id reaches the package its superseded source row carries.

### `witness_by_any_key` — A witness appearance by its current or an earlier key

Requires: `witnesses`, `witness_key_map`.

Result: The current appearance for the key, with the earlier key it was reached through.

Parameters, in order: `witness_key` (example `0001497931f99cd1`).

```sql
WITH k AS (SELECT ? AS key)
SELECT w.witness_key,w.name,w.occasion,w.superseded_by,m.old_key,m.status
FROM k LEFT JOIN witness_key_map m ON m.old_key=k.key
JOIN witnesses w ON w.witness_key=coalesce(m.witness_key,k.key)
```

No row: the key is unknown, or witness_key_map states it ambiguous (candidate_keys) or unresolved.

Never resolves by name.

### `committee_roster` — Committee members for a published Congress

Requires: `rosters`, `committees`, `members`.

Result: One committee or subcommittee assignment for the selected Congress.

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

Parameters, in order: `nomination_id` (example `119-pn-11-12`).

```sql
SELECT n.nomination_id,d.package_id,l.list_row,l.filename,l.title,lower(hex(d.link_key)) AS link_key
FROM nominations n JOIN detail d ON list_contains(n.transcripts,d.package_id) JOIN "list" l USING (list_row)
WHERE NOT coalesce(l.hidden,false) AND n.nomination_id=? ORDER BY l.list_row LIMIT 100
```

Preserve the nomination part, for example 119-pn-11-12.

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

Parameters, in order: `event_id` (example `335321`).

```sql
SELECT r.video_key,hex(t.body) AS body,t.suffix,t.format,t.language,t.production
FROM recordings r,UNNEST(r.tracks) AS tracks(t)
WHERE list_contains(r.event_ids,CAST(? AS BIGINT)) ORDER BY r.video_key,t.language,t.format LIMIT 100
```

Construct the body URL using the recorded suffix; a track is not a list document.

### `document_editions` — Other editions sharing an endpoint

Requires: `list`.

Result: One other document edition.

Parameters, in order: `list_row` (example `8`).

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
WITH target AS (SELECT CAST(? AS BIGINT) AS event_id), observations AS (
 SELECT r.match_id,r.subject_kind,r.subject_id,r.event_id,r.package_id,r.video_key,r.url,r.basis,r.decision,r.score,r.recording_scope,r.status,r.note,r.source_ref,
  list_filter(r.meeting_links,lambda l:l.event_id=t.event_id) AS meeting_links
 FROM recording_matches r CROSS JOIN target t
)
SELECT * FROM observations WHERE len(meeting_links)>0 ORDER BY match_id LIMIT 100
```

claimed rows are what a video says about itself; conflicting rows are retained, not settled.

A package_context link gives package evidence without establishing coverage for the event. Older releases may omit meeting_links and publish their original recipes.

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

### `research_recent_bills` — Recent bills

Requires: `bills`.

Result: One published bills row.

Parameters, in order: `since_null` (example `2026-10-01`), `since` (example `2026-10-01`), `until_null` (example `2026-11-01`), `until` (example `2026-11-01`).

```sql
SELECT * FROM bills WHERE (? IS NULL OR introduced>=CAST(? AS DATE)) AND (? IS NULL OR introduced<CAST(? AS DATE))
```

Used by run_research_query with additional exact association filters and release-bound paging.

since inclusive, until exclusive; null bounds are open. Missing values remain unknown.

### `research_pending_nominations` — Pending nominations

Requires: `nominations`.

Result: One published nominations row.

Parameters, in order: `since_null` (example `2026-10-01`), `since` (example `2026-10-01`), `until_null` (example `2026-11-01`), `until` (example `2026-11-01`).

```sql
SELECT * FROM nominations WHERE (? IS NULL OR received>=CAST(? AS DATE)) AND (? IS NULL OR received<CAST(? AS DATE)) AND latest_action_text IS NOT NULL AND NOT regexp_matches(lower(latest_action_text),'^confirmed|withdrawal of nomination|withdrawn|^returned to the president|^rejected by the senate')
```

Used by run_research_query with additional exact association filters and release-bound paging.

since inclusive, until exclusive; null bounds are open. Missing values remain unknown.

Reads only local nomination profiles referenced by archive documents or meetings. An empty result does not establish that the Senate has no pending nominations.

Pending means a known latest action without supported confirmed, withdrawn, returned or rejected wording in the selected snapshot. It does not establish present-day status; missing latest actions are unknown and excluded.

### `research_hearings_by_committee` — Hearings by committee

Requires: `meetings`.

Result: One published meetings row.

Parameters, in order: `since_null` (example `2026-10-01`), `since` (example `2026-10-01`), `until_null` (example `2026-11-01`), `until` (example `2026-11-01`).

```sql
SELECT * FROM meetings WHERE (? IS NULL OR meeting_date>=CAST(? AS DATE)) AND (? IS NULL OR meeting_date<CAST(? AS DATE)) AND (lower(coalesce(meeting_type,'')) LIKE '%hearing%' OR upper(meeting_type)='HHRG')
```

Used by run_research_query with additional exact association filters and release-bound paging.

since inclusive, until exclusive; null bounds are open. Missing values remain unknown.

### `research_legislation_by_subject` — Legislation by subject

Requires: `bills`.

Result: One published bills row.

Parameters, in order: `subject` (example `Public transit`).

```sql
SELECT * FROM bills WHERE list_contains(subjects,?)
```

Used by run_research_query with additional exact association filters and release-bound paging.

since inclusive, until exclusive; null bounds are open. Missing values remain unknown.
