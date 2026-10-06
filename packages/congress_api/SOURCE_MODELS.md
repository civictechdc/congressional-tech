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

Inventory late acquisition lives in `acquisition.gaps`: witness PDF/MODS
capture and Senate day probes accept a defaulted `get=` function. The orchestrator
and `completeness.build` call it explicitly. `parsers.witness_pdf` retains the
byte-only PDF/MODS parser entry points. Collection calls belong to
`acquisition.gaps`; the former parser acquisition delegates were removed.
Production rejected listing and committee detail responses use
`retention.rejected_pages`, independently of any storage importer.

Our generated CSVs, TinyDB files, caption indexes and inventory files are local
imports, not upstream schemas. Existing compatibility readers remain available.
A government-provided CSV would instead have its own source parser and native
row model. None of the local CSV summaries becomes the canonical GovInfo model:
that model is `ModsDocument`.

## Source inventory

| Source we parse | Canonical model | Parser or entry point |
| --- | --- | --- |
| Congress.gov meeting/detail/list JSON | `CommitteeMeeting`, `MeetingResponse`, `MeetingsPage` | `models.congress.parse_response`; `acquisition.meetings.get` |
| Congress.gov committee/detail/list JSON | `CommitteeRecord`, `CommitteeDetail`, `CommitteeResponse`, `CommitteesPage` | `models.congress.parse_response`; `acquisition.meetings.get` |
| Congress.gov XML fallback | `CongressXmlDocument` | `parsers.congress.parse_congress_xml` |
| GovInfo collection JSON | `GpoCollectionPage`, `GpoCollectionPackage` | `acquisition.gpo.list_collection` |
| GovInfo MODS XML | `ModsDocument` and nested native MODS records | `parsers.gpo.parse_mods_document` |
| GovInfo ZIP package file-list XML (METS) | `GpoPackageManifest`, `MetsFile`, `MetsFileLocation` | `parsers.gpo.parse_package_manifest` |
| GovInfo transcript HTML | `GpoTranscriptText`, `GpoTranscriptDates`; structured `Transcript` extraction | `transcripts.gpo`, `acquisition.gpo`, `parsers.gpo_text` |
| House meeting and witness XML | `HouseMeetingXML`, `HouseWitnessListXML` | `parsers.house_xml.parse_house_meeting`, `parse_house_witnesses` |
| House meeting HTML and combined extraction | `HouseEvidence`, `HouseParsedRecord` | `parsers.house_evidence`, `parsers.house.parse_house_record` |
| Senate hearing and attachment HTML | `SenatePage`, nested witness/document/page records | `parsers.senate.parse_page` |
| Senate WordPress types and posts JSON | `WordPressType`, `WordPressPost`, nested ACF and metadata records | `acquisition.senate.wordpress_listed` |
| Witness-list PDF | `PdfWitnessObservation`, `PdfTextPage`, `DocumentWitness` | `parsers.witness_pdf.parse_pdf_observation` |
| MODS witness extraction | `ModsWitnessObservation` | `parsers.witness_pdf.parse_mods_observation` |
| Senate player query, HLS playlists and WebVTT | `SenatePlayerQuery`, `HLSRendition`, `SenateCaptionSources`, `WebVTTCue` | `parsers.senate_player`, `transcripts.senate` |
| unitedstates/congress-legislators JSON | `Legislator` and nested identifiers, terms and names | `parsers.legislators.parse_legislators` |
| Zyte response JSON | `ZyteResponse` | `transport.zyte.request` / `transport.zyte.get` |
| Gemini transcription JSON | `GeminiTranscriptResponse`, `GeminiResponseCapture` | `transport.gemini` |
| YouTube duration response | `YoutubeVideoResponse` | `transcripts.generate.video_duration` |
| yt-dlp video metadata used for duration and caption discovery | `YtdlpVideoInfo` | `transcripts.generate.video_duration`; retained caption metadata |

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

Regression tests use retained real Congress.gov records and committee response
fixtures, House XML, Senate layouts and WordPress records, MODS, actual witness
PDFs and caption samples. Checks cover complete source-value
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

Historical captures whose original bodies were never saved cannot acquire them
from a schema change. Existing saved source bodies can be replayed; absent ones
remain absent until fetched. A retained URL alone does not establish that its
PDF/XML body was downloaded or parsed. Capture, interpretation and publication
require separate checks.

Congress.gov field definitions were checked against the publisher’s
[meeting documentation](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/CommitteeMeetingEndpoint.md)
and [committee documentation](https://github.com/LibraryOfCongress/api.congress.gov/blob/main/Documentation/CommitteeEndpoint.md),
with live responses used to verify actual JSON scalar types.

The September 28–29 manual review covered the observed JSON/XML families,
House/Senate pages, MODS, witness PDFs, captions and supporting JSON. Full sample
reports remain in `.cache/source-models/final-manual-{congress,house-pdf,senate-media,gpo-transcription}.md`;
follow-up capture evidence is in `.cache/source-history/`. The former
`.cache/raw-source-backfill-20260928/` path remains a compatibility link for
unchanged historical receipts and experiment manifests. Compressed bodies with
identical archive bytes resolve to `.cache/congressional-tech-raw/`.
These are local evaluation records, not runtime inputs or current download status.
The review did not manually inspect every file or qualify an actual upstream
Gemini response. Synthetic Gemini tests do not establish that qualification.

Preserve these interpretation limits:

- Native document classifications, file formats and meeting/witness document
  ownership are separate signals. Keep publisher disagreements and status labels.
- Complete short GPO proceedings can be valid; text length alone does not establish
  completeness. An unavailable-text notice is not a transcript.
- Captions retain source timing, including valid zero-duration cues. Successful
  byte/cue validation does not establish speech accuracy or whole-session coverage.
- Source pages can contain witnesses in running prose that the structured parser
  misses. Unreviewed scans and abbreviated schedules require separate evaluation.

### Witness PDF extraction and evaluation

Keep `pypdf` native-text extraction. The September 28 comparison used eight
visually checked PDFs (nine pages, 35 witnesses) plus 461 valid cached PDFs for
throughput. All four pypdf/PyMuPDF modes exposed the same 23 names in native text;
the witness parser recognized 11. The remaining misses came from name parsing
and scans. Default PyMuPDF also introduced two false person records by changing
table reading order. Its speed advantage saved about 1.5 seconds across 523
pages, excluding I/O and parsing. These selected samples are not corpus-wide
accuracy estimates or a qualification for long printed hearings.

Keep the PDF signature check: some `.pdf` responses are HTML error pages.
Empty native text in an image-only PDF is different from failed acquisition.
Exact-digest reviewed readings remain separate from automatic extraction.
SpicyDocs' pypdf reader matched the existing text on these samples; its geometry
reader reproduced the PyMuPDF reading-order issue. Neither provides a demonstrated
witness-accuracy improvement by merely replacing the library.

The benchmark scripts, pinned inputs, expected readings, per-page results and
versions remain in `.cache/source-models/pdf-extractor-comparison/`.
The paired XML/PDF inventory script and manifest remain in
`.cache/source-models/witness-pdf-pairs/`; later download paths and hashes are in
`.cache/source-history/witness-pdfs/manifest.json`.

For another witness evaluation, select active named XML witnesses and identify
candidate PDFs using native `HW`/Witness List types, explicit descriptions or
`-WList-` filenames. Older `SD` documents can also be witness lists. Join by House
event ID and exact attachment filename, retaining source URLs, type, selector
and digest. These pairs are candidates: verify editions, withdrawals, panel
subsets and actual PDF content before treating XML as expected output. Publisher
labels sometimes identify an organizational statement as a witness list.

## Committee details and XML meeting recovery

`CommitteeSnapshot` retains a Congress-specific `committee` and optional full
`detail` (`CommitteeDetail`) with independent `detail_url` and
`detail_retrieved_at`. The collector fills missing details and refreshes endpoints
represented in its refreshed Congress lists. The adapter retains the complete
snapshot but uses the historical list for Congress-specific classification.

`parsers.congress.meeting_from_xml` explicitly interprets known meeting lists and
numeric fields from `CongressXmlDocument`. The resulting `CommitteeMeeting`
retains the exact original bytes as `_source_xml` (`RawContent`), distinguishing
this interpretation from native JSON. Unknown XML, attributes and scalar spelling
remain recoverable from those bytes. Unexpected structures fail and stay in the
collector's pending-response evidence, rather than silently dropping values.
