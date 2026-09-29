# Source-model review — 2026-09-28

Manual raw-source review is complete for the retained source families described below. The review found and fixed extraction and normalization errors that exact round-trip tests alone cannot detect. With the subsequent gap-recovery fixes, the combined suite passes **688 tests and 31 subtests**. Changes are local; existing published data was not rebuilt. Additional raw captures remain in progress.

## What was checked

| Source family | Manual sample coverage | Detailed local evidence |
| --- | --- | --- |
| Congress.gov JSON and XML | All ten observed meeting types; eight committee categories; documents, witnesses, videos, continuations, locations, legislation and nomination/treaty references; all four JSON endpoint shapes; two fresh XML responses | `.cache/source-models/final-manual-congress.md` |
| House XML and HTML | Eight XML inputs covering meetings, witnesses, amendments, votes, removals, repeated files and field locations; two HTML inputs | `.cache/source-models/final-manual-house-pdf.md` |
| Witness PDFs | Eight actual PDFs, all nine pages rendered and visually inspected; text, scans, two columns, multiple pages and an abbreviated member schedule | Same House/PDF report; rendered pages and compared model/normalizer outputs under `.cache/source-models/manual-house-pdf/` |
| Senate HTML and WordPress | Seven witness layouts and their full source pages; historical/current event pages, attachment pages, listing rows, application errors; modern/legacy/empty WordPress fields and metadata | `.cache/source-models/final-manual-senate-media.md` |
| GovInfo MODS and transcript HTML | Eight varied MODS samples: nominations, repeated dates, joint committees, constituent ownership, multipart volumes, addenda and errata; complete short markup, unavailable-text stub, errata and large transcript HTML | `.cache/source-models/final-manual-gpo-transcription.md` |
| Captions and players | Actual player parameters, HLS master and 553-segment playlist, one empty and one spoken WebVTT segment; acquisition receipts | Senate/media report |
| Supporting JSON | Nine complete legislator records spanning observed nested fields; collection response; five actual YouTube resource items; retained generated/printed transcript JSON | Congress and GPO reports |

The source-family reports record exact paths/IDs, fields read, before/after results, raw-body digests, visual checks and qualifications. Corpus round-trip receipts remain separate in `.cache/source-models/`; this is not a claim that every file was manually reviewed.

## Fixes from actual samples

- Field-hearing addresses now populate normalized building/city/state and the complete address label. Each convening committee retains its own chamber in mixed-chamber hearings.
- House field-location models now expose nested state metadata correctly, including the postal code and full state name. Known MODS witness honorifics are explicitly typed.
- Exact-file reviewed readings recover an eight-person scanned witness list and all 13 people across a two-page list whose automatic parser found only one. Original PDF bytes and automatic text remain separate. House XML already supplies these witnesses to production, so this does not add duplicate appearances.
- Senate document titles use an explicit witness owner when the old extraction selected a generic Witnesses heading. Dates come from the listing's own row when available. Empty player query values survive. Observed Forbidden/Error HTML cannot replace a successful live hearing capture.
- Complete short GPO proceedings survive the old length cutoff. Special/Select/Joint committee-name prefixes remain intact. Native part/addendum labels reach rendition metadata without changing existing title values.
- Package-only transcription metadata uses the native MODS chamber and the same title fallback as the GPO parser. Historical generated files remain unchanged evidence.

Native document classifications are preserved separately from file formats and normalized categories. For House XML, examples include `HW`, `WS`, `WB`, `WT`, `SD`, `CA` and `CV`; a file's `doc-type="PDF"` describes its format. Meeting-document versus witness-document ownership also survives. Raw JSON `documentType` labels are not replaced by our categories.

## Limits that remain visible

- **No real retained upstream Gemini response was available for manual qualification.** Its model and capture/error paths have constructed regression coverage. Zyte now has real retained responses qualified in the September 29 follow-up below. The subsequent recovery now retains real yt-dlp metadata and complete YouTube API list responses; their validation is described below.
- Unreviewed scans still need OCR or visual reading. Some Senate JEC witnesses occur in running prose retained as source text without structured witness extraction. Abbreviated member schedules are not expanded into invented names.
- The initial manual review read two actual WebVTT segments. The subsequent complete capture retained all 553 segments of `jec011724` and validated 17,855 cues, original bytes, playlist order and regenerated text. A complete YouTube capture retained five English tracks and verified the selected manual track. It exposed and fixed our handling of space-only cue payload lines; the source was valid. Original captures and per-track checks are in `.cache/raw-source-backfill-20260928/captions/`. These checks establish source retention and parsing, not speech or timestamp accuracy.
- Publisher disagreements remain evidence. For example, one HTML errata notice conflicts with its MODS `isErrata=false`. Old meetings may still have a source status of Scheduled. No silent source correction was made.
- Linked PDFs/XML files are not claimed to have been downloaded or fully parsed merely because their URLs are retained. Missing historical raw bodies remain missing.
- The MODS capture subsequently completed for all **34,559 packages**, with zero capture or normalization failures. Replay through parser version 3 made no HTTP requests, added rendition metadata to 78 packages, and preserved every existing rendition value, acquisition time and prior transcript observation. Evidence: `.cache/gpo-xml-refresh-20260928/parser-v3-validation.json`. The separate full transcript-HTML acquisition remains a background job under `.cache/raw-source-backfill-20260928/gpo/`.

The separate [PDF extractor comparison](PDF_EXTRACTOR_COMPARISON.md) evaluates the actual native-text alternatives. The [paired witness dataset inventory](WITNESS_PDF_DATASET.md) identifies locally usable XML/PDF pairs.

## Validation

`python -m pytest tests packages/committee_meeting/tests -q`: **661 passed, 31 subtests passed**, after all manual-review code fixes. Log: `.cache/source-models/final-manual-test-run.log`. `git diff --check` passed. New regressions use real source samples for the discovered defects; synthetic future-field/error tests are labeled separately.

After the complete-caption follow-up and its real YouTube regression, the same
combined command passes **662 tests and 31 subtests**. Log:
`.cache/raw-source-backfill-20260928/test-run.log`.

## Full gap-recovery follow-up

The recovery work found source omissions and collector assumptions that the
original samples did not exercise:

- Senate archive streams can declare separate WebVTT tracks. Four previous
  negative caption results now have complete retained timing captures. The
  collector checks both live and archive locations and falls back when a declared
  live subtitle playlist or segment fails. Failed-path responses remain evidence.
- Senate discovery previously excluded every title containing `closed`,
  `briefing` or `executive session`. It now uses explicit access classification,
  permitting open portions and events whose access is unspecified. Native page
  embeds supply recording evidence, and explicit no-broadcast notices survive as
  scoped assessments. Repeated shared video widgets are not meeting associations.
- Exact Senate page labels fill 48 unknown access values in existing, date-matched
  occurrences. Prior source evidence and record IDs survive. Existing explicit
  disagreements retain both readings; filling unknown access does not manufacture
  a conflict issue. Real-page tests follow the result through catalog assembly.
- One Veterans listing URL retained literal `&amp;`. Entity decoding restores
  the original usable address without altering the retained HTML.
- Official ZIPs for all ten GPO packages without MODS HTML links contain usable
  PDFs. Two also contain HTML files absent from those MODS links. Their METS
  manifests identify the actual addendum and different-chamber filenames. All ten
  ZIP/member integrity checks and PDF page-tree parses passed; two real METS
  fixtures cover exact-byte and structured-model roundtrips. One recovered HTML
  remains a publisher text-unavailable notice.
- All 275 retained complete YouTube API response bodies passed digest checks and
  exact native JSON roundtrips through `YoutubeVideoResponse` (13,712 item
  occurrences, including overlapping verification batches). This establishes
  preservation, not playback or whole-session coverage. Real yt-dlp discovery
  metadata is also retained and qualified separately from the generated VTT.

The combined suite after these changes passes **688 tests and 31 subtests**.
The retained-file integrity snapshot validated all 34,855 referenced path/digest
pairs against full decompressed bytes, lengths and SHA-256 values, with no failures.
Later downloads fall outside that snapshot. Integrity does not prove content accuracy.
Evidence and running download status are under
`.cache/raw-source-backfill-20260928/`; its README distinguishes the initial
catalog gap inventory from new recovery evidence. Bulk caption/document captures
remain in progress. Full video files are deferred by the user's choice. No new
site catalog has been published, and changes remain local.

## September 29: Zyte refused-document recovery

The authorized Zyte fallback now retains complete API response bytes and headers,
including error responses, separately from the decoded publisher body. Five
actual recovered PDFs from Finance, Rules and GAO were checked directly: exact
Zyte model round-trip, base64 decoding, content digests, PDF page trees and first
page text. Repeated publisher headers and unknown API fields survive. A Zyte
API success with an upstream refusal remains a failure; a missing upstream
status remains unknown. Intermediate redirect history is not supplied and is
marked unavailable.

Evidence is in `.cache/raw-source-backfill-20260928/documents/zyte/`, especially
`initial-validation.json`, `local-check.json` and the append-only receipts. The
focused HTTP/Zyte/House source suite passes 29 tests. The normal download jobs
continue independently. These checks establish capture fidelity for the samples,
not semantic correctness of every recovered document or published explorer data.

### Failure retries and source timing

The failed Senate captures exposed zero-duration WebVTT cues, not backwards
timestamps. The model now preserves equal start/end values and continues to
reject an end before its start. Capture receipts count zero-duration cues
separately. Replaying all 15 affected recordings retained 7,707 such cues and
completed their caption captures without changing publisher timestamps. A real
segment with 51 zero-duration cues is now a regression fixture. The caption
collector also checks the official archive path for `intlnarc`, whose published
player table has no corresponding live stream ID.

The targeted caption/model/HTTP/Zyte suite passes 51 tests and 14 subtests.
Failure recovery receipts, direct source samples, public replacement URL
associations, document integrity checks and remaining gaps are recorded under
`.cache/raw-source-backfill-20260928/failure-recovery/`. New captures remain
separate from original failures. A working alternative URL establishes a current
published copy; it does not establish equality with an unavailable historical
body. Where GovInfo PREMIS metadata supplies a SHA-256, recovery compares that
publisher digest with the retained PDF bytes. No site catalog was rebuilt.
