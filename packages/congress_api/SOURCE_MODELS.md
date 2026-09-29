# Source models

The source model represents what the publisher supplied. It does not depend on
CSV, Parquet, a database, or `committee_meeting`.

```text
upstream response bytes
    → source parser
    → Pydantic source model
    → normalization adapter
    → committee_meeting models
    → storage or export
```

Collectors handle HTTP and retention. Parsers interpret bytes without doing
HTTP or opening output files. Source models describe native values. The
`adapters/` modules translate those values into the application’s normalized
records. Storage readers and writers sit outside this sequence and can change
without redefining a publisher’s data.

Our generated CSVs, TinyDB files, caption indexes and inventory files are local
imports, not upstream schemas. Existing compatibility readers remain available.
A government-provided CSV would instead have its own source parser and native
row model. None of the local CSV summaries becomes the canonical GovInfo model:
that model is `ModsDocument`.

## Source inventory

| Source we parse | Canonical model | Parser or entry point |
| --- | --- | --- |
| Congress.gov meeting/detail/list JSON | `CommitteeMeeting`, `MeetingResponse`, `MeetingsPage` | `models.congress.parse_response`; `api.request_source` |
| Congress.gov committee/detail/list JSON | `CommitteeRecord`, `CommitteeDetail`, `CommitteeResponse`, `CommitteesPage` | `models.congress.parse_response`; `api.request_source` |
| Congress.gov XML fallback | `CongressXmlDocument` | `congress_source.parse_congress_xml` |
| GovInfo collection JSON | `GpoCollectionPage`, `GpoCollectionPackage` | `gpo.fetch.list_collection` |
| GovInfo MODS XML | `ModsDocument` and nested native MODS records | `gpo.source.parse_mods_document` |
| GovInfo ZIP package file-list XML (METS) | `GpoPackageManifest`, `MetsFile`, `MetsFileLocation` | `gpo.source.parse_package_manifest` |
| GovInfo transcript HTML | `GpoTranscriptText`, `GpoTranscriptDates`; structured `Transcript` extraction | `gpo.transcripts`, `gpo.fetch`, `transcribe.gpo_parse` |
| House meeting and witness XML | `HouseMeetingXML`, `HouseWitnessListXML` | `house.source.parse_house_meeting`, `parse_house_witnesses` |
| House meeting HTML and combined extraction | `HouseEvidence`, `HouseParsedRecord` | `house.evidence`, `house.records.parse_house_record` |
| Senate hearing and attachment HTML | `SenatePage`, nested witness/document/page records | `senate.records.parse_page` |
| Senate WordPress types and posts JSON | `WordPressType`, `WordPressPost`, nested ACF and metadata records | `senate.records.wordpress_listed` |
| Witness-list PDF | `PdfWitnessObservation`, `PdfTextPage`, `DocumentWitness` | `inventory.witness_lists.parse_pdf_observation` |
| MODS witness extraction | `ModsWitnessObservation` | `inventory.witness_lists.parse_mods_observation` |
| Senate player query, HLS playlists and WebVTT | `SenatePlayerQuery`, `HLSRendition`, `SenateCaptionSources`, `WebVTTCue` | `senate.isvp`, `senate.captions` |
| unitedstates/congress-legislators JSON | `Legislator` and nested identifiers, terms and names | `models.legislators.parse_legislators` |
| Zyte response JSON | `ZyteResponse` | `zyte.request` / `zyte.get` |
| Gemini transcription JSON | `GeminiTranscriptResponse`, `GeminiResponseCapture` | `transcribe.gemini` |
| YouTube duration response | `YoutubeVideoResponse` | `transcribe.main.video_duration` |
| yt-dlp video metadata used for duration and caption discovery | `YtdlpVideoInfo` | `transcribe.main.video_duration`; retained caption metadata |

`models/` contains shared source definitions. `RawContent` retains exact bytes
with a verified SHA-256. `XmlElement` preserves expanded namespace names,
attributes, ordered and repeated children, text and tails. Source-specific XML
models expose typed fields while keeping the complete tree and original body.
This avoids pretending that a selected set of MODS fields is the entire MODS
standard.

GovInfo's MODS file links are not always a complete package file list. The METS
manifest inside an official package ZIP can identify additional filenames. Its
model preserves native file attributes and exact locators alongside the original
XML. A filename that differs from the package ID is not corrected or discarded.
Declared byte lengths remain publisher values even if they differ from captured
file lengths.

HTML and PDF models describe the structure we extract. They retain the source
body alongside it. Extracted PDF text is not a claim that image-only pages were
read; reviewed readings and extraction results remain distinguishable.

## Preserve source values

`SourceModel` validates scalar types strictly and retains unknown fields. It
does not normalize labels, dates, identifiers, URLs, whitespace or casing.
Missing fields, explicit nulls, empty strings and empty lists remain distinct.
Repeated values remain repeated. Publisher labels use strings rather than an
enum that rejects newly introduced labels.

Use `source_dict()` to serialize a native JSON record with its original field
names and field presence. `model_dump()` is Pydantic’s general serializer and
includes defaults unless requested otherwise. Unknown publisher keys, including
keys that happen to match a Python alias name, must survive unchanged.

```python
from congress_api.models.congress import CommitteeMeeting
from congress_api.adapters.meetings import records

source = CommitteeMeeting.model_validate(native_json)
assert source.source_dict() == native_json
normalized = list(records([source], context))
```

No CSV read or write is involved. House and Senate adapters also accept their
typed parser results. Existing dictionary interfaces are compatibility entry
points; they do not define the source schema. GovInfo’s `parse_mods` accepts a
`ModsDocument` and produces its existing hearing summary for legacy consumers.

For another language, generate JSON Schema directly from the model rather than
maintaining a second hand-written definition:

```python
schema = CommitteeMeeting.model_json_schema(by_alias=True)
```

## Verification and limits

Tests use retained real records, live committee response fixtures, all retained
Congress.gov records, House XML, Senate layouts and WordPress records, MODS,
actual witness PDFs and caption samples. Checks cover complete source-value
round trips, original-byte hashes, unknown fields, aliases, incorrect scalar
types and typed-parser-to-adapter parity. Local full-corpus receipts are in
`.cache/source-models/`; representative regression fixtures are included with
the code.

“Complete” means no source content is discarded by these representations. It
does not mean every possible future publisher field has a named Python
attribute, or that every interpretation of unstructured text is correct.
Unknown JSON keys and XML elements remain accessible until a typed field is
added. The raw body supports reinterpretation without refetching.

New House, Senate, WordPress, PDF and transcript captures retain source bodies.
Rejected Congress.gov meeting details remain in the existing pending-work file
alongside their retry URLs, so validation does not discard the response.
Rejected listing pages remain in an adjacent `.rejected.json` file while the
previous good snapshot stays intact.
`gpo-transcripts` keeps `source/<package>.json` even for short title-only HTML.
The transcriber keeps those HTML captures and each Gemini attempt separately.
Gemini's retained HTTP text is the SDK-decoded body, not original transport
bytes; an unavailable SDK body remains null.

Historical captures whose original bodies were never saved cannot acquire them from a
schema change. Existing saved source bodies can be replayed; absent ones remain
absent until fetched. This change does not trigger a historical refetch, alter
the running GovInfo refresh, rebuild public tables or publish data.

Congress.gov field definitions were checked against the publisher’s
[meeting documentation](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/CommitteeMeetingEndpoint.md)
and [committee documentation](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/CommitteeEndpoint.md),
with live responses used to verify actual JSON scalar types.

A [manual source review](SOURCE_MODEL_REVIEW.md) records the actual samples,
extraction fixes, combined test result and remaining qualification limits.
