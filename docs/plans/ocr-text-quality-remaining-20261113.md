# Remaining OCR and text-quality work — 15 November 2026 UTC

The corpus is broadly useful for full-text search (FTS), with a specific tail of
missing, garbled and incomplete extractions. The cheap screen is complete and
selective repair continues. HTML/XML reparse and local adoption are complete.
Accepted-set-v9 passes independent stored-row and selection review. Private
recovery candidates still require quality disposition and accepted selection.

The user wants real, internally consistent text with minimal garbage, not perfect
transcription. Do not re-OCR the corpus or send every document to an LLM. Use
`gpt-6.1-terra` with medium reasoning for bulk manual source/page reviews. Read
actual source → intermediary → final text into context; scripts provide inventory
and integrity checks, not the source-quality verdict. The user owns SereneDB
search ingestion and deployment. The shelved SQLite/MCP prototype stays outside
this task.

## Current accepted text

The local handoff is `repairs/accepted-text-adoption-20261114/accepted-set-v9/`
under the durable recovery root below. It has:

- 311,726 selected release text bodies and 8,142,726 physical page slots.
- 2,727,457 OCR-marked pages, 1,217 explicit reading overrides and 339 quality dispositions.
- 26 exact source exclusions and 57 source-reviewed valid empty results.
- Native catalog snapshots: body_text `2003281374347950523`; readings `2857253250252688186`.

The latest nine pairs replace eight errors and one size-limit outcome, adding
315,131 UTF-8 bytes and 258 slots. They include eight geometry repairs with all
41 pages directly source-read and the complete 217-page ee7ad6da replacement.
Ee7 source review covers pages 1, 55, 109, 163 and 217; the other 212 remain
manually unread. Split/joined words, graph/table relationships, graphic signatures
and named footer omissions remain explicit FTS limitations.

Independent v9 review checks every stored field of all eighteen new native rows,
page boundaries, OCR/build provenance, append-only ancestry and actual native
selection results. The planted wrong digest is rejected. All prior 1,208 choices
and 330 dispositions survive unchanged. The nine-pair Parquet files are validation
deltas, **not a complete accepted-text export**. See
`accepted-set-v9-independent-review/{review.md,result.json}` beside the handoff.

Another 11,857 non-excluded saved bodies have no selected text at these accepted
versions: 266 errors, 205 size-limit outcomes and 11,386 without an applicable
reading. That last group includes 8,442 WARC, 1,470 HTML, 612 PDF, 386 DOCX,
126 Word, 259 ZIP, 68 ARC, 19 image, two WMV and two plain-text bodies. This is a
mixed eligibility/custody/processing inventory, not 11,386 OCR failures. Private
retry completion does not update these selected counts automatically.

## Recovery and repair status

| Work | Ticket | Verified state and next boundary |
| --- | --- | --- |
| Stored-size and resource recovery | [ct-a73a](../../.tickets/ct-a73a.md) | The separate 206-target lane finished at 09:46:27 UTC: 193 complete, thirteen pending archive-read failures. All 193 pass integrity and cheap quality checks. Qualify/adopt useful candidates and diagnose the thirteen reads. |
| Geometry failures | [ct-yy07](../../.tickets/ct-yy07.md) | First eight bodies are adopted in v9. Native census and remaining 196 whole-body candidates are complete; independent artifact checks pass. Complete source-risk dispositions and targeted 487aa18e repair before adoption. |
| Incomplete native layers and vector text | [ct-hz8y](../../.tickets/ct-hz8y.md) | Ee7 is adopted. F6 native-spacing repair and its nineteen-page source review are complete; staging/adoption remain. VFW page 105 and named handwriting/coverage cases remain held. |
| Corrected historical GPO text | [ct-kfsd](../../.tickets/ct-kfsd.md) | Eight corrected pairs and six unchanged controls are qualified, locally adopted and associated. Final accepted-data handoff remains. |
| Markup adoption | [ct-cbkz](../../.tickets/ct-cbkz.md) | All 310,928 completed texts and 310,963 readings are locally adopted; one valid feed is handled separately. All 35 original refusals survive with source dispositions. Final handoff remains. |
| Source roles and history | [ct-en4n](../../.tickets/ct-en4n.md), [ct-fb7k](../../.tickets/ct-fb7k.md) | Reviewed error/wait/feed/wrapper exclusions are selected. Preserve broader inventory and capture-history distinctions. |
| Publisher refetch | [ct-z4w5](../../.tickets/ct-z4w5.md) | Three newly retrieved PDFs are useful across all eight source-reviewed pages. Capture/reading adoption and association checks remain. Cornwell is still HTTP 200 with zero bytes. |
| Consistent-text handoff | [ct-m704](../../.tickets/ct-m704.md) | Bind final selected keys, hashes, page maps, exclusions and quality inventory for the user's SereneDB work. Do not present a small validation delta as the full table. |
| Downstream source-to-search acceptance | [ct-0a35](../../.tickets/ct-0a35.md) | Coordinate with the user's SereneDB work; this task claims no hosted search acceptance. |

The 193-result quality chain covers 228,840,708 UTF-8 bytes, 111,129 page slots
and 81,135 OCR markers. No complete result is empty. Five have no obvious
screen flag, five have stronger first-review signals and 183 have weaker signals.
These are triage bands, not accuracy ratings. The final six-result delta extends
prior evidence without rereading its unchanged 187 predecessors. Exact bindings
are in `repairs/ocr-checkpoint-resume-20261114/quality-screen-chain-193.json`.

The thirteen pending objects are the largest stored payloads: 541,845,812 to
1,065,029,037 bytes. All current one-byte range checks and SDK metadata checks
match their retained identities; two full-range header probes also pass. Those
bounded probes read thirteen application bytes, not the complete objects.
The historical worker discarded the specific `ValueError`, so its exact subcause
is unknown. A prepared change retains safe phase/length/response diagnostics
without changing pending outcomes or reader versions. The next experiment is one
smallest-object raw-only transfer, stopping before decompression or OCR. See
`repairs/raw-range-diagnosis-final13-20261115/` and
`repairs/raw-range-diagnostics-code-20261115/`.

The 196 geometry candidates contain 4,445 slots and 412 OCR markers. Independent
review checks actual source/checkpoint/reading/final identities and page maps,
and rejects planted wrong-output and wrong-offset cases. Existing screens
nominate 342 unique pages; these are not 342 proved failures. Direct review covers 41 unique source pages, with remaining empty nominations
under review. The eight-page continuation sample found useful partial
fragmentation, legitimate symbol/bullet warnings and appropriate sparse/empty
outputs, with no new major prose omission in those eight.
In 487aa18e, source review found substantial missing cover text on page 1 and
questionnaire fields on page 82. Two targeted Vision calls recover useful page-82
text, but page 1's tiny screenshot collage produces extensive garbage and its
full OCR output remains held. Other named graph, header/footer, ordering and
signature limits remain in the source-review reports. Evidence is in
`repairs/geometry-wholebody-recovery-20261115/final-03/` and
`repairs/geometry-487-two-page-repair-20261115/`.

The 1,476-page f6d8df26 candidate uses maintained SpicyDocs
`DefaultReader(native_inhibit_spaces=True)`. It finished in 49 seconds at
0.665 GiB peak RSS: 1,465 native reads and eleven unchanged prior OCR contents,
with no new recognition or rendering. All native non-whitespace characters
survive; strong letter-fragmentation flags disappear. The final text has
4,206,117 UTF-8 bytes. Native character parity does not prove word quality.
Terra directly read nineteen source pages and confirmed all eight retained empty
exceptions. Sampled written pages provide useful FTS text with named spelling,
date, table and cover limitations. The explicit no-GPO-cleanup finishing policy
differs from 419 prior final slices: 169 strict additions and 250 punctuation/format
exceptions remain recorded. Every prior page's NFKC-normalized letters/digits
survive as a subsequence of the candidate, with zero exceptions. That metric
establishes preservation of prior search characters, not source accuracy.
See `repairs/ocr-checkpoint-resume-20261114/native-spacing-repair-20261115/`.

All 66 original memory/deadline cases are operationally accounted for: 62 have
same-body selected completions, one truncated source has a complete later stored
body at the same URL, and three new private retries completed 215/123/169 pages.
The three remain held because direct review found six materially damaged
handwriting pages; three useful controls do not qualify their unread 498 page
positions. Two Groq/Qwen handwriting candidates also guessed words and omitted
annotations. Preserve those rejected outputs. The truncated 4f57c7ee body has
67,108,864 of 118,982,865 declared bytes; its complete later 4e8115a7 body is
already selected and associated, so do not repeat its acquisition or OCR.

VFW page 105 remains unresolved. Vision at 200/400 DPI omitted substantial text;
a single Groq/Qwen six-key response invented passages and was rejected. Two
other damaged-PDF cases also retain honest source limits: one body lacks
recoverable pages, while a Walling file holds an earlier intact revision before
a truncated update. A generic qpdf rewrite dropped testimony and was rejected.
Repairing PDF structure alone does not qualify its text.

## Completed foundations and reusable evidence

- Shared reading selection [ct-55qo](../../.tickets/ct-55qo.md) and durable page checkpoints [ct-aitp](../../.tickets/ct-aitp.md) are closed after actual consumer qualification. Reuse exact retained pages and preserve original failures.
- Cheap screening [ct-n3ik](../../.tickets/ct-n3ik.md) is closed at independently accepted `final-all-screen-20261115/checkpoint-04-v7-private165/`: 610,216 inventory bodies, 609,574 exact current measurements and 114,636 deduplicated review/control rows. Later versions require additive reconciliation. Of measured outputs, 517,334 have no obvious flag, 85,498 weaker signals and 6,742 stronger signals. These do not measure accuracy.
- Frozen literal-empty review is complete: 26 source-confirmed omissions repaired and 57 legitimate empties preserved. All sources and actual new outputs were read directly; old intermediaries were unavailable where explicitly recorded.
- Font corruption, sideways pages, vector text and provider compositions have qualified local repairs in accepted sets v5–v7. Table associations, column order, small labels and Cherokee-script loss retain named limitations. No whole-corpus transcription claim follows.
- [ct-t4p3](../../.tickets/ct-t4p3.md) is closed after v8 adopted the 244-page repair. Qwen page 124 and regional Vision page 125 retain real provider evidence, all other 243 page strings are unchanged, and model-supplied incorrect metadata stays outside document metadata.
- Wrapper leakage [ct-g4yz](../../.tickets/ct-g4yz.md), markup encoding [ct-f6hr](../../.tickets/ct-f6hr.md), bounded append [ct-tpwm](../../.tickets/ct-tpwm.md), Vision edge bands [ct-l3xd](../../.tickets/ct-l3xd.md), empty attempted-journal handling [ct-saqg](../../.tickets/ct-saqg.md) and refetch request-scope preservation [ct-5cdu](../../.tickets/ct-5cdu.md) are closed with scoped consumer evidence. Reuse their receipts rather than rerunning unchanged qualifications.

The large BillsThisWeek XML is a valid Atom feed, not a legislative document.
The shared SpicyDocs reader and CT/Regs consumers retain 2,226 entries and 65,511
link occurrences. Five source entries received direct end-to-end review.
The maintained reader preserves original links and the recorded repair basis for
one malformed URL. See [feed behavior and limits](../house-floor-feed.md).
Recurring acquisition and freshness/coverage evaluation are separate from this
completed retained-input implementation.

## Finish sequence and operating rules

1. Complete direct source dispositions for the flagged private candidates and the narrowly repaired pages. Preserve useful FTS output with named limits; hold substantial garbage, invented content and unresolved source loss.
2. Append only qualified actual text/reading pairs. Preserve old rows and refusals, then validate real selection, page maps, hashes and every changed stored field. Reuse append ancestry for unchanged rows.
3. Diagnose the thirteen archive reads with the prepared bounded one-object replay. Preserve complete raw bytes if recovered; expand only from the observed result. No blind bulk retry or blanket re-OCR.
4. Adopt the three source-reviewed refetch results with capture/reading associations. Retain the empty Cornwell response as failure evidence.
5. Add later selected/private results to the frozen quality inventory by exact body/parser/version/output identity. Retain valid empties, source exclusions, false alarms and unresolved source cases.
6. Deliver the consistent accepted table, selection and quality inventory together. The user handles SereneDB ingestion/deployment; do not resume the shelved SQLite/MCP path.

OCR/refetch was explicitly authorized on 14 November. The original run remains
frozen at its committed boundary; the separate checkpointed lane preserves those
outcomes. The recovery version `e7af136c37deb9d3bab5a3e9f3d4c79a4f5b38bd8b8f820aba5ec175672826dc`
is distinct from ordinary `4d045589…` and historical `d6250c3c…`; never restamp
old rows. Root owns dispatch, catalog writes, selected versions and ticket edits.
Use measured watchdog admission, the shared archive lock and frozen runtime pins.
Preserve unrelated jobs and checkpoints.

The durable evidence root is
`<main checkout>/.cache/archive-release/ocr-recovery-20261113/`.
`coordination/text-quality-audit-20261113/repair-plan.md` holds the original causal
audit; `coordination/greybeard-root-cause-20261113/review.md` holds the independent
architecture review. `coordination/ocr-offline-ticket-matrix-20261113.md` names
the direct raw/intermediate/output reviewers and remaining gates. Accepted sets
v4–v9 retain preceding adoption/selection evidence. Historical progress is in
those immutable receipts and this document's Git history.

The last checked public release was
`4b9a7bd126cc17e39dfbe7f8fabafbdb7251dcd32576277f308916f469c9bab1`,
published at 05:25:35 UTC on 14 November, with 324,013 detail rows. That dated
observation is separate from the qualified local handoff. No new public search
release or full accepted export is claimed by these local repairs.
