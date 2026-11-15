# Remaining OCR and text-quality work — 15 November 2026 UTC

Accepted-set-v10 contains 312,114 release-associated text bodies. All 388 latest
additions pass independent stored-row and selection checks. Their source review
covers 94 of 114,416 page slots; the remaining pages are not manually certified.
The separate 1,208-page recovery pilot completed mechanically, but direct source
review found substantial OCR omissions. Its candidate stays private and held.

The user wants useful, internally consistent text for full-text search, with
minimal missing content or garbage. Perfect transcription is not required.
Use selective repair, maintained SpicyDocs readers and existing renderers. Do not
re-OCR the corpus or send every document to an LLM. Bulk manual reviews use
`gpt-6.1-terra` with medium reasoning and read actual source → intermediary →
final output. Scripts provide inventory and integrity checks, not source verdicts.
The user owns SereneDB ingestion and deployment; the shelved SQLite/MCP path
remains outside this task.

## Counts and accepted text

Counts refer to distinct file-content hashes, not deduplicated logical documents.
The frozen assessment contains 610,216 bodies. The review inventory also identifies
11,383 bodies outside that population, giving a known union of 621,599 bodies.
This union is not a complete current object-store census. There are 297,484 PDFs
inside the assessment and 609 more in the outside inventory.

The assessment has 609,811 completed outputs: 85,515 contain at least one recorded
OCR page, and 524,296 contain no OCR markers. Of the latter, 211,578 are PDFs.
Completed includes explicitly held private candidates and historical/unassociated
bodies; it does not mean every output is suitable for publication.

The accepted local handoff is
`repairs/accepted-text-adoption-20261114/accepted-set-v10/` under the recovery root:

- 312,114 selected release-associated bodies, including 85,427 with OCR pages.
- 8,257,142 stored page slots and 2,807,900 OCR markers.
- 1,605 reading overrides, 727 quality dispositions, 26 source exclusions and
  57 source-reviewed valid empty results.
- Native snapshots: `body_text` 4383126096555098411;
  `readings` 6734786965736914418.
- Selection SHA256:
  `eb8473ab6163d3ab4b16f4fa56754a5b72b9391065aeedf3138db02eaaf3b111`.

Independent v10 review checks every stored field of the 388 new text/reading
pairs, append ancestry, page boundaries, text hashes, OCR provenance and actual
native selection. It preserves all 1,217 preceding choices and 339 disposition
lines and rejects a planted wrong digest. The added text totals 234,583,311 UTF-8
bytes, 114,416 page slots and 80,443 OCR markers. The catalog plus explicit
selection is the accepted dataset; small validation Parquets are not a full
accepted-text export. Evidence: `accepted-set-v10-independent-review/`.

## Remaining processing and source gaps

There are 11,469 non-excluded release-associated bodies without selected text:
70 errors, 13 size-limit outcomes and 11,386 without an applicable reading.
The 83 errors/size-limit refusals are PDFs. They comprise:

- 13 failed large-object archive reads; one source is now recovered, but its
  replacement OCR is held for source-quality failure.
- 19 older memory failures, separate from the original 66 memory/deadline cohort.
  Two have selected same-URL alternatives needing revision comparison; 17 remain
  fresh retry candidates.
- 49 zero-page parser errors whose source causes remain unassessed.
- One encrypted PDF and one missing-page-tree case.

The no-reading group contains 8,442 WARC, 1,470 HTML, 612 PDF, 386 DOCX, 126 Word,
259 ZIP, 68 ARC, 19 image, two WMV and two plain-text bodies. Three private
handwriting completions are among those 612 PDFs, leaving the 11,383 outside
inventory bodies above. These are mixed format, eligibility, custody and
processing gaps, not 11,386 OCR failures. Do not double-count the three private
holds in the 83 selected refusals or the distinct nineteen memory failures.

## Recovery and repair status

| Work | Ticket | Current result and next step |
| --- | --- | --- |
| Resource and stored-size recovery | [ct-a73a](../../.tickets/ct-a73a.md) | All 193 completed bodies from the separate 206-target lane now have qualified selected text: 190 direct results, f6/4f6 repairs and the better existing dbaa composition. Thirteen historical read failures remain recorded. Diagnose the held 1,208-page pilot before expanding the remaining twelve. |
| Geometry failures | [ct-yy07](../../.tickets/ct-yy07.md) | Eight earlier bodies plus the final 196-body group are selected. The final group has 4,445 slots and 414 OCR markers. Its 56 source-reviewed pages include all eighteen nominated empty roles; the preceding eight bodies had all 41 pages read. Preserve damaged-source and partial-text limits. |
| Incomplete native layers and vector text | [ct-hz8y](../../.tickets/ct-hz8y.md) | Ee7, f6 native-spacing repair and 4f6 regional repair are selected. VFW page 105, handwriting and named source-loss cases remain held. |
| Corrected historical GPO text | [ct-kfsd](../../.tickets/ct-kfsd.md) | Eight corrected pairs and six unchanged controls are qualified and adopted. Carry their exact associations and limits into the final handoff. |
| HTML/XML adoption | [ct-cbkz](../../.tickets/ct-cbkz.md) | 310,928 completed texts and 310,963 readings are adopted. All 35 original refusals survive; one valid feed is handled separately. |
| Source roles and history | [ct-en4n](../../.tickets/ct-en4n.md), [ct-fb7k](../../.tickets/ct-fb7k.md) | Preserve reviewed error/wait/feed/wrapper exclusions and the broader missing-format inventory. |
| Publisher refetch | [ct-z4w5](../../.tickets/ct-z4w5.md) | Bill and Mahoney already have stored bodies and release associations. Preserve the better bill reading; a small Mahoney improvement is staged. Mast needs maintained receipt ingestion and an explicit document association. Cornwell remains HTTP 200 with zero bytes. |
| Consistent-text handoff | [ct-m704](../../.tickets/ct-m704.md) | Deliver catalog pins, exact selection and the current quality inventory together. Independently review the Q5 additive inventory and preserve its population boundary. |
| Source-to-search acceptance | [ct-0a35](../../.tickets/ct-0a35.md) | The user owns SereneDB integration. No hosted search acceptance follows from local text qualification. |

### Large-object transfer and held OCR pilot

CT PR179 merged at `043d048c0588a04f7921301efd6ec9cf170def95` after CI passed.
A complete pinned-object request can accept HTTP 200 only with the exact expected
length and ETag and no conflicting range header. Partial requests still require
206. The original pilot captured a rejected 200 response; the repaired raw-only
retry returned 206, so it is not live proof of the 200 branch. It recovered all
541,845,812 stored bytes in 14.2 seconds at 0.637 GiB peak RSS. Bounded local
unpacking verified 575,953,191 PDF bytes and the expected body hash.

The source-only OCR pilot completed 1,208 checkpoints in 1,037 seconds at
1.756 GiB outer peak RSS: 1,174 OCR pages, 34 native pages and 2,196,023 UTF-8
bytes. Stored row, page map, hash, source identity and resource checks pass.
A cheap whole-output screen found no replacement/control/private-use characters,
no repeated-line signal, one empty page and one possible fragmentation flag.

Direct Terra review of pages 1, 2, 4, 5, 7, 302, 604, 906 and 1208 found material
omission/garbling on pages 7, 302, 604 and 906 already in Vision observations.
Page 4 is visually blank; page 5 has useful contents headings but finishing
removes its page numbers. Other sampled pages are useful with named defects.
The remaining 1,199 pages are unread. This is a false negative for broad quality
inference from clean character statistics. Hold the candidate and remaining
twelve dispatches; compare maintained OCR/rendering settings on one failed page
before choosing the next processing policy. Evidence:
`repairs/raw-range-retry13-20261115/{postpilot-quality,independent-source-review}/`.

### Selective repairs and damaged sources

SpicyDocs PR32 merged at `b51b338fef18806b8c0db7759ebf793b4adebb2a`.
Its opt-in `DefaultReader(native_inhibit_spaces=True)` supports the selected f6
repair: 1,476 pages, eleven retained OCR pages, 4,206,117 UTF-8 bytes, 49 seconds
and 0.665 GiB peak RSS, with no new rendering or recognition. Nineteen source
pages were read. All prior normalized letters/digits survive, which establishes
preservation, not accurate word boundaries or whole-source fidelity.

The selected 4f6 repair replaces page 223 with maintained regional Vision output
and preserves its other 442 slices byte-for-byte. The whole-page one-band result
omitted content; Groq repeated a table and invented prose before a token/schema
failure. Both rejected outputs remain preserved. Regional output restores the
paragraphs and caption with explicit number/unit and table-association defects.
The final body has 968,281 UTF-8 bytes, 443 slots and 387 OCR markers.

All 66 original memory/deadline identities are operationally accounted for:
62 same-body selected completions, one truncated body with a complete later
selected source, and three private 215/123/169-page completions held after
source review found handwriting loss. Their six bad pages and three useful
controls do not qualify the other 498 page positions. The separate nineteen
memory failures above are a different cohort.

VFW page 105 remains held: Vision and Groq trials omitted or invented prose.
For damaged ZIP-code collections a558/e51, macOS PDFKit could not open either
retained original and installed Adobe Acrobat reported both damaged and
unrepairable. No new images were recovered. Earlier white renderings remain
unknown-source pages, not confirmed blanks. These are distinct from Walling
ed029, which retains an earlier useful revision before a truncated update.
Existing qpdf rewriting lost content and was rejected. Evidence:
`repairs/established-viewer-damaged-probe-20261115/`.

### Refetch integration

Current `archive_r1b.captures_df55_20261113` snapshot 4529945025615165014 contains
the bill/Mahoney bodies and Mast parent HTML/historical 410. It contains neither
the Mast PDF nor the six checked November 14 refetch receipt keys. Preserve all
six attempts, including failures, through maintained receipt ingestion. Mast's
parent links the malformed address and the corrected address redirects to the
reviewed PDF; that trail alone is not a logical document association.

Mahoney's exact reviewed three-page Vision pair is staged in native schemas and
restores Self, Organization and CV/biography lines. Radio state remains ambiguous.
It needs independent pre-apply review and a narrow selected replacement. Bill's
current reading already preserves the provisions more cleanly, so retain it.
Evidence: `repairs/refetch-three-adoption-planning-20261115/`.

## Quality inventory and finish sequence

Cheap screening [ct-n3ik](../../.tickets/ct-n3ik.md) is closed at its frozen Q4
scope. The additive Q5 candidate keeps 610,216 assessed bodies and 114,636
review/control rows, updates 485 existing rows and binds 609,811 current measured
outputs totaling 30,809,112,369 UTF-8 bytes. It reuses prior measures; only the final
487/4f6 compositions needed new scoring, 1,323,322 bytes. Its author consumer
checks pass; independent Q5 review is pending. Character/structure flags rank
review effort and do not certify content completeness. The new held pilot is
outside this frozen Q5 generation.

1. Diagnose the held pilot with one matched-source-page comparison before the
   remaining twelve large-source OCR jobs. Preserve all original checkpoints.
2. Retry the seventeen distinct memory candidates under measured limits; compare
   the two same-URL alternatives before deciding whether they need retry.
3. Classify the forty-nine zero-page cases and missing-format inventory from raw
   evidence; use known better source versions and maintained tools where useful.
4. Complete narrow Mahoney selection and Mast capture/source-link integration,
   preserving failures and exact source history.
5. Independently qualify Q5, then add later candidates by exact output identity.
   Preserve the 26 exclusions, 57 valid empties, 203 exposed no-search-character
   candidates and source holds as distinct outcomes.
6. Deliver selected text, native catalog pins and quality inventory for the user's
   SereneDB work. Do not equate local text qualification with search publication.

Reading selection, page checkpoints, bounded append, Vision edge-band handling,
wrapper/encoding repairs and qualified literal-empty repairs are completed
foundations. Reuse their exact retained evidence. The shared valid Atom-feed
reader preserves 2,226 entries and 65,511 links; recurring feed acquisition is a
separate task. See [feed behavior and limits](../house-floor-feed.md).

OCR/refetch was explicitly authorized on November 14. The original run remains
frozen; selective continuations use separate checkpoints and declared versions.
Root owns dispatch, catalog writes, selected versions and tickets. Use measured
watchdog admission, shared archive locking and frozen runtimes. Preserve unrelated
jobs. The durable evidence root is
`<main checkout>/.cache/archive-release/ocr-recovery-20261113/`.
Earlier accepted generations and reports remain immutable; this file's Git
history retains preceding status. No new public release, full accepted-text
export, SereneDB ingestion or BGE embedding is claimed by these local repairs.
