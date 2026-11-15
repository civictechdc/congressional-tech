# Remaining OCR and text-quality work — updated 15 November 2026 UTC

The GPO cleanup and optional diagnostic evidence are merged in [PR #151](https://github.com/civictechdc/congressional-tech/pull/151), commit `2cef1dbde71f842d527b6a9cfb8893ff8c16dc25`. All ten CI checks passed. Bounded integration covered 14 archived PDFs / 281 pages through the real CT consumer; independent source review approved that scope. Corrected historical text has not yet been published.

The remaining work is to finish selective retries, adopt newly qualified repairs,
provide the final accepted-table handoff and resolve the named difficult PDF cases.
The frozen all-screen repair queue now passes independent acceptance.
The HTML/XML reparse and local adoption are complete. Full corruption screens
now cover both completed markup and the selected current PDF outputs.
All 26 confirmed omissions in the frozen 83-empty-result cohort now have
source-reviewed useful text; its other 57 results are legitimate empties.
Accepted-set-v8 passes independent stored-row and selection review. These
results establish the named scope, not complete source fidelity across the corpus.

The goal is useful full-text search (FTS): cheaply find failed, empty, badly
garbled or substantially incomplete extraction, then repair selected cases.
Perfect transcription and an LLM review of every document are not required.
On 14 November the user authorized targeted OCR and publisher refetch to
continue asynchronously. The old run stays frozen; its 206 remaining PDF keys
run in a separate current-policy lane with durable page checkpoints. At
09:18:12 UTC on 15 November, 188 had completed and 18 remained. A host-memory
stop preserved 76 page checkpoints, which the unchanged worker reused before
recognition resumed at page 77. Bounded supervision retries only no-commit
host-memory stops under the same memory admission. These are separate from
extraction failures. Refetch preserves every new response. Any bulk manual
PDF/page audit uses `gpt-6.1-terra` with medium reasoning.

Those 206 targets are original stored-size-limit cases, separate from the 66
original memory/deadline cases. Exact reconciliation finds 62 of the latter
selected and completed at the same body identity. Three have complete retained
captures and a separate checkpointed retry lane. Its d120 pilot hit the real
4 GiB worker limit, preserving its unreadable outcome and diagnostics. Fresh
workers reused 130, then 153, then 183 valid checkpoints before completing all
215 pages. The other two bodies completed all 123 and 169 pages. All three
remain private and held: independent source review finds six handwriting pages
with substantial garbling or missing content, alongside three useful controls.
The other 498 source-page positions are unread. Cheap text measures reported no
obvious failure, and even badly read Vision blocks can have confidence 1.0.
Neither runtime success nor confidence qualifies their text. Two targeted
Groq/Qwen handwriting candidates also failed direct review for guessed words
and missing annotations; their raw outputs remain retained and unselected.
The fourth, 4f57c7ee,
contains only 67,108,864 of the response's declared 118,982,865 bytes. Later source
history already retains the complete 4e8115a7 body at that same URL, with selected
completed text and a visible document association. Preserve the truncated bytes
and original failure, but do not refetch or repeat OCR on them. A current
same-worker regression confirms request memory resets correctly while the
process-lifetime high-water mark remains separate.

The user owns text search through SereneDB. This task checks the text tables for
internal consistency and useful source content, and reports omissions, garbage
and error responses explicitly. Plain text and minor OCR mistakes are acceptable.
Preserve actual reading keys, page offsets, provenance and source exclusions.
The local SQLite/MCP adapter is shelved, unmerged and unpublished; its independent
review found a page-map reuse defect. Do not continue that delivery path or infer
that its small consumer proof establishes the SereneDB integration.

## Remaining work and ownership

| Work | Ticket | State and completion boundary |
| --- | --- | --- |
| Shared accepted-reading selection | [ct-55qo](../../.tickets/ct-55qo.md) | Closed after actual 14-body planner/export qualification: eight corrected readings and six unchanged actual keys. Historical publication remains ct-kfsd. |
| Durable page checkpoints | [ct-aitp](../../.tickets/ct-aitp.md) | Closed after composed checks and independent raw/checkpoint/output review. Exact-page replacement survives two late-page exits and reuses matching pages. The new authorized recovery lane is writing these checkpoints. |
| Reconcile resource failures and targeted recovery | [ct-a73a](../../.tickets/ct-a73a.md) | The old pause boundary leaves 206 PDF targets. Background recovery is now authorized; a separate current-policy lane adds durable page checkpoints and keeps old outcomes intact. |
| Publish corrected historical GPO readings | [ct-kfsd](../../.tickets/ct-kfsd.md) | Eight corrected pairs are adopted and six unchanged controls retain their baseline keys. All 14 bodies have document associations; accepted export and downstream adoption remain. |
| Incomplete native layers and vector text | [ct-hz8y](../../.tickets/ct-hz8y.md) | Source-qualified page coverage and selective routing remain; existing cheap signals can miss charts and bullets. |
| Native geometry failures | [ct-yy07](../../.tickets/ct-yy07.md) | Of 204 exposed bodies / 1,344 failed pages, the first eight bodies now have all 41 physical pages source-read and all nineteen actual zero-width refusals inspected. Seven graphic/heading candidates pass direct review after nine bounded recognition calls. Whole-body assembly/adoption remain. The other 196 bodies / 1,325 failed pages need the bounded native census; its per-body adapter passes exact 41-page parity. |
| Page-local recognizer crashes | [ct-t4p3](../../.tickets/ct-t4p3.md) | Closed: the completed 244-page repair is appended and independently selected in v8. Reviewed page 124 Qwen text and page 125 regional Vision text retain exact provenance; model metadata and named partial-FTS limitations stay explicit. |
| Cheap extraction-failure screen | [ct-n3ik](../../.tickets/ct-n3ik.md) | Closed after independent checkpoint04 acceptance: 610,216 bodies, 609,574 exact current measurements and 114,636 deduplicated review/control rows. V7 choices and private cutoff 165 are reconciled. Later completions and source findings need additive updates; the p124 garbling missed by character measures remains an explicit limitation. |
| Congress.gov navigation in bill text | [ct-g4yz](../../.tickets/ct-g4yz.md) | Closed: PRs #173, #174 and #175 merged with passing CI. The bill and 210 wrapper repairs are selected; exact source-role exclusions remove seven exposed viewers and preserve all thirteen linked PDFs. V7 retains the independently qualified v6 choices. |
| HTML/XML reparse and adoption | [ct-cbkz](../../.tickets/ct-cbkz.md), upstream `ss-mkxe` | Reparse and exact local adoption are complete: 310,928 texts, 310,963 readings and one separately handled valid feed. All 35 refusals and older outcomes survive. Accepted data handoff remains. |
| HTML encoding and XML subsets | [ct-f6hr](../../.tickets/ct-f6hr.md) | Closed: shared helper and CT PR #168 are merged with passing CI; all 35 refusals have source dispositions and the seventeen actual repair pairs are adopted and selected. Public delivery remains ct-cbkz. |
| Document/feed/error/landing roles and capture history | [ct-en4n](../../.tickets/ct-en4n.md), [ct-fb7k](../../.tickets/ct-fb7k.md) | House error detection merged in CT PR #165 after all ten checks passed. Explicit reviewed source-body exclusions merged in PR #167 after independent native review and a real two-error/one-control export replay. Broader eligibility adoption and capture history remain. |
| Text-table consistency and quality handoff | [ct-m704](../../.tickets/ct-m704.md) | User owns SereneDB ingestion and deployment. Validate actual retained/selected keys, text hashes and page maps; expose missing and suspicious results. SQLite/MCP indexing work is shelved. |
| Verify source-to-search results | [ct-0a35](../../.tickets/ct-0a35.md) | Coordinate downstream acceptance with the user's SereneDB work. Keep source, accepted text, snippets and citations bound to their actual identities. No SereneDB acceptance is claimed here. |
| Publisher refetch | [ct-z4w5](../../.tickets/ct-z4w5.md) | Authorized on 14 November. The corrected-address followup recovered three useful PDFs, independently read across all eight pages. Cornwell remains HTTP 200 with zero bytes. Six other reviewed source URLs remain outside published capture scope. |

The four-document batch is appended and independently selected in v5:
the complete H.R.4307 HTML candidate, a two-page disclosure, a ten-page bill
and a two-page biography. The three PDF outputs previously contained no
searchable text. Their replacements cover all fourteen written pages. The
sideways biography uses an explicit raster rotation while retaining the original
PDF as extractor input; original native and rotated OCR coordinate frames stay
distinct. The batch has 23,108 UTF-8 bytes. Every actual appended field matches
the approved candidates; native selection and independent readback pass.

The broader 207 selected no-searchable-character candidates are distinct from
the earlier frozen 83 literal-empty results. Nine prior loss reviews now bind
exactly to current source/reading/output identities; they cover 23 of 91 pages
and belong to ct-hz8y. Four newly audited sources account for the fourteen
written pages above and five pages that render blank. Those five blanks agree
with the retained source; upstream completeness and publisher intent remain
unknown. A shape or byte-count signal alone does not establish source failure.

Three font-corruption cases have 52 source-reviewed pages appended and selected
in v5: all thirteen pages of e8a51168, pages 79–115 of 0e7a0f9b and both
pages of 4ddca9b9. The 0e composition preserves original pages 1–78 byte-for-byte
and keeps their existing OCR markers. Six sideways pages use explicit rendering
rotation. The existing 32-page composition bound is preserved through two
recorded stages, with intermediate history retained. These candidates recover
useful search words but retain known spelling/numeric errors and unreliable
checkbox/row associations. Independent stored-row and selection review pass,
including rejection of a wrong digest and exclusion of the intermediate history
version. This is not a whole-corpus font-fidelity claim.

The shared HTML wrapper follow-up reuses maintained SpicyDocs byte events,
source spans and USLM/HTML rendering. Independent reading covers four complete
short legislative bodies, four controls and declared opening/interior/closing
contexts of the long preformatted bill. The planted omission of the operative
gaming prohibition is rejected. Most long-bill lines and the remaining candidate
sources are explicitly unread. Fifteen fallbacks retain their original keys:
fourteen are statute PDF viewers and one is a publisher challenge. All thirteen
distinct linked PDFs already have stored captures and selected release-exposed
readings. One two-page PDF was directly checked; the other twelve have metadata
proof only. Seven viewer bodies are themselves exposed. The existing `wrapper`
role now has a focused, tested publication-exclusion extension merged in PR #175.
V6 applies the reviewed exclusions and preserves completed readings and the separate
PDF identities. No refetch is needed for these retained PDF assets.

## Newly isolated defects

- [ct-tpwm](../../.tickets/ct-tpwm.md) is closed after PR #169 merged with passing CI and all remaining markup rows reconciled. The same bounded writer adopted another 945 text/reading pairs at 0.464 GiB peak RSS. No memory ceiling was increased.
- [ct-l3xd](../../.tickets/ct-l3xd.md) is closed for the qualified shared fix and selective CT adoption. SpicyDocs PR #31 and CT PR #171 are merged with passing CI. Pages 600 and 1100 gain one recognized line each, while the other 1,156 pages remain byte-identical. The actual composition version is selected; remaining omissions and imperfect order are explicit. The active OCR policy stays frozen.
- [ct-saqg](../../.tickets/ct-saqg.md) is closed: merged PR #170 represents an absent attempted journal as a real empty native input. CI, 107 focused scheduler cases and the exact native consumer pass.
- [ct-5cdu](../../.tickets/ct-5cdu.md) is closed after PR #170 merged with passing CI. Reviewed request roots remain separate from related history. The seven-target replay preserves four requests and seven cutoff records at 1.539 GiB RSS. The independent A/B/C native consumer passes; initial full metadata preparation remains explicit.

Refetch evidence is under `repairs/source-refetch-20261114/scheduler-followup/`.
The corrected-address batch retained all responses and receipts. A Terra medium
reviewer read the complete four-page bill, one-page Mast amendment and three-page
Mahoney disclosure form through actual producer outputs. All provide useful
FTS text; Mahoney checkbox state and a name suffix remain imperfect. The empty
Cornwell PDF is still a failed source. New capture and reading adoption,
association checks and public search verification remain.

The seven strongest old-recovery signals received a direct 17-page Terra
review. Two photographic sources are valid empty prose; four bodies have useful
partial text with named gaps or damaged sources. Their useful readings are
selected, with page 140 of 3a21a04f now repaired at a distinct actual key. The
217-slot ee7ad6da output remains held: its 216 newline bytes omit visible prose.
Three useful candidate pages do not qualify a whole-body replacement.

The five earlier one-page repairs remain selected: S002/S016 biographies,
S010's mine-plan title and legend, and S027/S029 amendments. The remaining
77 unknown empty sources have now all been read directly: 45 one-page PDFs and
32 tiny ASX media playlists. The PDFs contain 26 omitted texts, 18 images
without readable prose and one blank page. Adding the prior six valid empties
fully explains the frozen 83-body cohort: 26 repairs and 57 legitimate empties.

The new candidates reused maintained SpicyDocs native/OCR strategies. One
amendment recovered through the native path; 25 pages needed recognition.
The full-page map candidate lost a substantive negation and was rejected.
A maintained regional read recovered its complete legend, including **Not
Destroyed**, plus the title and date. Terra medium reviews cover every actual
source, new intermediate and final output. Historical intermediaries of the
old empty readings remain unavailable. Checkbox placement, table associations,
column order and small map labels retain explicit limits: the recovered words
are useful for search, not exact structured interpretation.

The prior local handoff is
`accepted-text-adoption-20261114/accepted-set-v4/`. Its manifest has **982 actual
overrides** and eleven source exclusions. The selected release has **311,721
text bodies**, each with an exact completed reading, with no duplicate selected
body or completed selection missing text in the checked set. The unchanged
prior checks are reused by exact identity and append-only ancestry. Independent
review read all 52 new native files and every field, checked four append-only
transitions, and proved that all 956 prior overrides remain unchanged. The
26 new pairs contain 36,529 UTF-8 bytes and pass native selection validation,
including planted wrong-digest rejection. Historical tables retain older
readings and response text; consumers
must use the explicit selection and exclusions. No standalone full-text export
or public search deployment is claimed.

The v5 handoff is `accepted-text-adoption-20261114/accepted-set-v5/`.
It preserves the previous generation and adds seven final repairs: **989
overrides**, eleven exclusions and the same **311,721 release-associated text
bodies**. Independent review checked all sixteen newly appended native rows
(eight pairs, including one history pair), selected only the seven finals and
rejected the planted wrong digest. All 982 prior overrides and 89 prior quality
dispositions remain unchanged. The seven new dispositions retain known OCR,
numeric, form and ordering limitations. Page slots remain 8,142,229; OCR markers
increase by 66 to 2,727,023. Its small Parquet files are a validation delta,
not a complete selected export.

The independently reviewed v6 predecessor is
`accepted-text-adoption-20261114/accepted-set-v6/`. It adds the 210 actual HTML
repairs and fifteen reviewed source exclusions: fourteen statute viewers and
one publisher challenge. Seven viewers were exposed; all thirteen linked PDFs
and the separately retained resolution remain eligible. V6 has **1,199
overrides**, **26 exclusions**, **311,714 selected release bodies**,
**8,142,222 page slots**, **2,727,023 OCR markers**, and the same 57 valid literal
empties. Independent review checks every new native field, append ancestry,
209 old-reading controls, exact prior choices/dispositions and the planted wrong
digest. Its Parquet files contain 210 changed pairs, not a full corpus export.

The predecessor handoff is `accepted-text-adoption-20261114/accepted-set-v7/`.
Eight actual PDF pairs are appended, selected and independently verified. Six
compositions replace 22 reviewed pages across Q005, Q007, Q009, Q010, S167 and
S188. All ten S167 pages gain useful article text. S188 gains English search
text while its Cherokee-script sidebar remains unrecognized. Q009 combines its
actual Groq/Qwen page 37 and Vision page 47, preserving the other 47 pages exactly;
the provider adapter passes 37 focused tests and is merged in PR #176
at `9e507b62c0f9d52790fd535775217f94f91bcb57`, with both CI workflows passing. Two native
replays recover the c848 letter and 156 biography at explicit replay versions,
retaining prior failed-page readings and word-split/graphic/signature limits.

V7 preserves all 1,199 previous choices, 26 exclusions and 321 dispositions, adding
eight choices and dispositions. It has 1,207 overrides, 311,716 selected release
texts, 8,142,224 page slots, 2,727,045 OCR markers and the same 57 valid empties.
The two native replays add two texts/slots; the six compositions add 22 OCR
markers. Independent review compares all 16 actual native rows, append ancestry,
eight old-reading controls, exact prior choices and the planted wrong digest.
The eight-pair Parquet files are a validation delta. Partial table/chart coverage,
ordering/numeric errors, a missing signature and photo-sign noise remain explicit.

The current handoff is `accepted-text-adoption-20261114/accepted-set-v8/`.
It adds the repaired 244-page document while preserving every prior choice,
exclusion, disposition and valid-empty identity. V8 has 1,208 overrides,
311,717 selected release texts, 8,142,468 page slots, 2,727,233 OCR markers,
330 dispositions, 26 exclusions and 57 legitimate empties. The one-pair Parquet
files are a validation delta, not a complete selected export. Independent review
checks the actual stored rows, native append ancestry and real positive and
wrong-digest consumer results. The new stage-only base is not appended.

Another **11,866** non-excluded saved bodies have no selected text: 274 errors,
206 size-limit outcomes and 11,386 without a reading at the accepted versions.
The last group includes 8,442 WARC, 1,470 HTML, 612 PDF, 386 DOCX, 126 Word,
259 ZIP, 68 ARC, 19 image, two WMV and two plain-text bodies. It is a mixed
eligibility/custody/processing inventory, not 11,386 OCR failures. The selected
set now has **57 empty outputs**, all source-reviewed as valid within the frozen
83-body cohort. The 11,867 missing selections describe this accepted version,
not the current private retry lane. Earlier mechanical signals remain retained
observations; changing a selected version requires rebinding its old flag rather
than silently carrying its semantic conclusion forward.

A separate incremental screen of **56 completed background OCR results** checked
59,876,306 UTF-8 text bytes and 27,514 page slots in 18 seconds at 0.27 GiB RSS.
All reading/text keys, hashes, byte counts, UTF-8 boundaries and OCR markers
pass; no whole output is empty. It reuses the existing feature function and
maintained quality measures. Two strong word-spacing warnings received a direct
two-page review: f6d8df26 page 1 has broken word boundaries already in native
text; 5e3f6444 page 1602 remains mostly searchable with one letter-spaced line.
Three disjoint incremental checks extend this to the first **105 completed
private results**, including exact hashes, page maps and recognition markers.
The 20-, 15- and 14-body deltas add 15.50, 15.22 and 12.06 MB respectively,
with no empty whole outputs or new strong garbling signal. New completions
need their own delta; the frozen queue cutoff is distinct from live progress.
Two further disjoint checks cover results 106–120 and 121–131, adding 15.86 MB
and 10.56 MB. All identities, hashes, page maps and append checks pass, with no
empty whole outputs. Two letter-spacing candidates in the first of those deltas
remain semantically unassessed; the latter has no new strong candidate.
A further fourteen-result delta extends the exact quality chain through **145**,
adding 21.92 MB / 10,959 page slots. Integrity passes with no empty whole output.
One new isolated-letter-run candidate on three slots remains source-unreviewed.
The frozen queue cutoff remains distinct from these additive results.
The next twenty-result delta covers 146–165: 27,014,796 UTF-8 bytes, 13,139 slots
and 11,738 OCR markers. Identity/hash/page/append checks pass with no empty whole
outputs or new first-review flags. The subsequent eleven-result delta covers
166–176: 17,528,369 UTF-8 bytes, 8,835 slots and 6,863 OCR markers. Integrity
passes with no empty outputs or new strong flags; all eleven have weak signals.
The next eleven-result delta covers 177–187: 20,178,870 UTF-8 bytes, 9,173
slots and 8,279 OCR markers. Identity/hash/page/append checks pass with no
empty outputs or new strong flags. Ten have weak flags and one has no obvious
failure. The fixed quality chain through 187 remains distinct from live progress;
the prior 176 payloads were not reread.

The independently accepted checkpoint04 combines v7 with private cutoff 165:
300 disjoint affected bodies, comprising 225 accepted replacements, fifteen
source-role changes and sixty later private results. It preserves checkpoint03,
57 legitimate empties, 26 exclusions and all previous review positions. The
queue contains 114,636 unique review/control rows and 609,574 measured current
outputs across the 610,216-body population. Four of the frozen 207 selected
no-searchable candidates have reviewed replacements; 203 remain. No private
output is automatically selected. These are review inventories, not confirmed
defect counts. Root checked exact retained rows, prior history, current keys and
measurement conservation in 18 seconds at 0.95 GiB RSS without rereading old
text or PDF payloads. Later private results and repairs need additive updates.

The maintained alternate native reader also fragments f6 words. Direct source
review now covers f6 pages 1, 739 and its valid blank back cover, plus the
localized 5e control. Targeted OCR repairs page 1 usefully. Three-band and
one-band page-739 candidates omit different real lines already absent from
recognition observations; neither is a complete repair. Other flagged pages
remain measurements, not independently confirmed defects. These private results
are outside the accepted selection except for the separately qualified dbaa
repair. Do not infer that a reader switch or whole-body OCR will solve this case.

The full markup screen measured **310,928 actual outputs / 11.800 GB UTF-8** in
19m37.5s at 0.434 GiB peak RSS. It found 268,339 outputs with no obvious failure,
37,626 weak flags and 4,963 first-review flags. The latter include 3,760 outputs
without searchable tokens, 61 severe mechanical signals and 1,142 template
candidates. These are candidate counts, not confirmed defects or selected
document counts. The corrected candidate handoff leaves selection unknown until
the actual-key join; a no-mutation annotation is not an exposure fact.

A separate 1,790-key screen covers 1,767 WARC outputs and 23 selected markup
alternatives. Its single strong selected-markup flag was directly checked in
raw HTML and actual output: intentional A-M table columns and a spaced CONTENTS
heading. Preserve that bounded false-alarm disposition and the mechanical
observation. No global threshold was weakened. All 26 new v4 keys pass their
small exact-key delta screen.

The PDF corruption pass is complete: **296,690 exact outputs / 18.759 GB
UTF-8**, in 41m26s at 0.726 GiB peak RSS. Identity, digest, byte and page-map
checks pass. Its 1,530 severe candidates include 1,424 triggered only by a long
single-letter run, 104 only by private-use character density, and two by both.
Keep isolated typography separate from widespread font/word damage in ranking.
The pass adds the signal missing from the old quantity features; it did not
reread raw PDFs or repeat OCR. Terra medium source review subsequently confirmed
three font-loss cases, whose exact selective candidate scope is recorded above.
The final frozen queue integration passes independent acceptance; later repairs
and completion prefixes remain separately versioned evidence.

The exact markup exposure join finds eight selected, release-associated severe
candidates and zero release-associated template candidates. Root read the raw
and actual output contexts for all 13 long-letter runs in those eight cases:
they are deliberate heading typography or table availability marks. One source
also contains undefined table symbols, which remain a limitation. A separate
real defect emerged in the Congress.gov case: quick-search member choices
pollute its bill text. ct-g4yz owns that fix. Preserve all 1,142 unassociated
template candidates in the corpus inventory; release absence does not establish
their safety for another consumer.

[PR #172](https://github.com/civictechdc/congressional-tech/pull/172) merged at
`298b93ffa654138bf06ab16d1ed1879e36fed691` with both CI workflows passing. Its
counter implementation preserves existing scores and policy; bounded paired
measurements show a 3.16x faster counter kernel. Do not apply that ratio to an
unmeasured whole job. The source pins and independent equivalence evidence
remain with the completed screen artifacts.

The formerly crashing 244-page document now has a completed CT candidate and
244 valid checkpoints. Its reviewed seven-region page-125 fallback preserves
useful partial text with named contact/roster defects. Direct sampling found
severe garbling on page 124 that character-only measurements missed. A targeted
Vision retry still failed quality review. One Groq/Qwen image request using the
same six-key schema recovered the complete readable biography in two seconds;
independent review found no omitted sentence or invented substantive passage.
Its model-supplied document type, date and identifier are wrong and stay outside
document metadata. The exact page-124 composition is now appended and selected
in v8; the other
243 page strings are unchanged. The complete text has 476,218 UTF-8 bytes,
244 page slots and 188 OCR markers. Independent stored-row and selection review
passes while preserving the sampled source limits and 239 unread source pages.

The difficult VFW page 105 remains unresolved. Both 200- and 400-DPI Vision
candidates omit substantial text. A single Groq `qwen/qwen3.8-27b` image request
used the recovered six-key JSON schema and fidelity prompt. Its schema-valid
response invented sections and testimony and omitted real sections, so the
independent reviewer rejected it. No model output entered the table. This
finding is specific to the tested request, not a general model ranking.

Evidence is under `accepted-text-adoption-20261114/` and
`ocr-checkpoint-resume-20261114/quality-screen-20261114/`. Source reviews and
metadata/selection checks establish different claims. Runtime completion alone
does not certify useful text.

## Sequence and limits

1. Resume only the 206 remaining targeted PDF keys in a separate checkpointed lane. The frozen worker lacks page checkpoints, so restarting it would lose page work again on interruption. The maintained unlimited-size recovery policy has actual PDF version `e7af136c37deb9d3bab5a3e9f3d4c79a4f5b38bd8b8f820aba5ec175672826dc`, derived from ordinary policy `4d045589…`; neither may be used to restamp old `d6250c3c…` results. Use measured worker admission and preserve original pause receipts.
2. Reuse the frozen completed markup run. The normal lane finished at 14:50:05 UTC on 14 November: 310,528 completed and 35 refusals. Adding the separate 400-key lane gives 310,928 completed readings; the remaining inventory key is the valid dedicated feed. The run took 3h 6m 37.5s at 1.433 GiB peak RSS and produced 11,800,377,840 UTF-8 text bytes / 3,854,160,110 staged Parquet bytes. These are operational outcomes, not whole-corpus semantic acceptance. Bounded local adoption subsequently appended and verified all text and reading rows; no accepted selection followed automatically.
3. Diagnose only residual failures. Preserve useful prior text at its actual old key. The new spicy-docs helper creates explicitly unqualified, hash-bound encoding/entity candidates; it never silently changes the default reader. Missing endings, error responses and external/recursive entity requests remain explicit refusals. Reuse existing raw/intermediate/output reviews and read new tail cases directly.
4. Reuse qualified markup and PDF adoption receipts. The v8 native snapshots are body_text `5142626956824563545` and readings `166109599630118892`. The latest one-pair append preserves prior snapshot ancestry and passes every-field readback and independent selection review. Historical rows and refusals remain intact. These retained tables contain multiple versions; the actual selected version and explicit source exclusions determine the accepted text.
5. Reuse the independently accepted `final-all-screen-20261115/checkpoint-04-v7-private165/` queue under `corpus-assessment-20261113/triage-current-20261114/`: 114,636 unique review/control rows, all 610,216 frozen population identities accounted for, and 609,574 current outputs measured. Its private cutoff is 165; later quality chains and source dispositions are additive. Filter current review_priority while preserving prior positions. Retain legitimate empties, source exclusions, false alarms, original refusals and outdated versions. The 400 examples annotate existing bodies. Cheap signals can miss real prose corruption, as the new page124 source review demonstrated; current scores are not source certificates.
6. Keep explicit reviewed search eligibility in the accepted selection. V6 has 26 exact error/wait/feed/wrapper exclusions while preserving completed readings and saved-body custody. Exclusion cannot hide a wrong accepted digest. The producer's native eligibility steps exclude seven actual exposed viewers and retain all thirteen linked PDF identities plus the alternate resolution. The wrapper helper merged in PR #175; no hosted index has changed.
7. Keep the table's consistency, missing outcomes and useful-text evidence explicit. Search integration and deployment belong to the user's SereneDB work. Continue repairing identified bad PDF pages/bodies, reuse checkpoints and retained intermediates, and run authorized targeted OCR/refetch under separate supervision. Groq candidates that invented content remain rejected; the useful Q009 candidate has its own reviewed provider provenance. The small `accepted-set-v8/body_text.parquet` is a one-row validation delta, not a full accepted-text export. Hand off the catalog pins, actual selection and quality records together.

Operational completion and source completeness remain separate. Preserve valid empty results, old refusals and recovery evidence. Carry forward only readings proved unaffected, and declare semantic changes rather than restamping old rows. New recovery results carry their actual new policy version.

Two damaged-PDF source reviews also show why repair success needs content
review. One retained body contains only 1,553 bytes of a declared four-page PDF
and exposes no recoverable pages. The Walling body contains an intact earlier
nine-page revision before a truncated fourteen-page update. Its exact original
prefix `[0:336711]` is retained as a separately hashed inspection candidate;
it is not a complete replacement for the later document. A generic qpdf rewrite
passes its structural check while dropping testimony pages and blanking a
partially readable disclosure form. Named reviewers rejected that candidate.
Those structural repair candidates did not authorize selection or recognition. After the later explicit refetch authorization, the short bill was retrieved completely and all four new source pages were directly reviewed; its accepted adoption still remains. Evidence is under `repairs/native-pdf-repair-20261113/`.

Further geometry review retrieved three exact originals from the retained
archive, without contacting publishers. All five nominated pages contain finite,
in-page zero-width lines, but two PDFs also have truncated streams, missing-font
repairs and garbled output. The third has an invisible native span and a graphic
header missing from text. The alternate maintained PypdfReader also omits the
upper-right address on the c848 control. Native salvage must preserve original
text and diagnostic facts without inventing geometry or accepting those coverage
losses. The source-backed findings and exact unresolved identities are under
`repairs/geometry-reconciliation-20261113/`; the role proposal and producer
boundary are under `repairs/ct-markup-compatibility-20261113/role-partition/`.

## The large XML case is a feed

The retained `https://docs.house.gov/BillsThisWeek-RSS.xml` body is Atom despite
the filename. The hash-pinned 13 November inspection found a complete feed with
2,226 entries describing weekly House floor consideration, update times and
links to bill documents. Escaped HTML inside entries produces millions of text
callbacks. The ordinary CT page reader also refuses this body at its 24 MiB
bound; the body-text reader reaches its event bound. Neither outcome establishes
an error response or a truncated source.

The current body-text consumer refused after 1.25 seconds at 0.26 GiB peak RSS.
A temporary six-million-event measurement completed in 7.03 seconds at 1.34 GiB
RSS. No production bound changed. These measurements identify the cost of the
generic event representation; they do not justify treating the feed as one
legislative document. The prior tentative truncation interpretation is superseded.

The shared spicy-docs reader and offline CT/Regs consumers are now implemented.
Final actual outputs retain 2,226 entries and 65,511 link occurrences. CT resolves
every occurrence, including one malformed leading-slash URL whose exact target
appears in another retained entry. The original href and repair basis remain
inspectable. Direct reviews cover five entries through actual intermediate and
final outputs. The native CT replay uses 0.67 GiB/14 seconds; Regs uses
0.59 GiB/8 seconds. See [reader behavior and limits](../house-floor-feed.md).
Compare discovery coverage and verify freshness before recurring acquisition.
Scheduled consideration remains distinct from enacted status, votes or completed
actions. Neither local replay publishes a new release or starts source fetching.

Exact archived bytes, input identity and measurements are retained under
`repairs/ct-f6hr-event-limit-20261113/`. Retrieval used the retained raw archive;
no publisher refetch or OCR ran. The markup pilot and independent consumer
review are under `repairs/ct-markup-readers-20261113/`.

## Evidence and follow-on consumers

The durable local evidence root is `<main checkout>/.cache/archive-release/ocr-recovery-20261113/`. `coordination/text-quality-audit-20261113/repair-plan.md` contains the mechanism-by-mechanism design and source-review references; `repairs/ct-gpo-consumer-20261113/` contains consumer readback. The corpus/source review lives under `.cache/archive-release/investigations/text-quantity-review-20261113/`.

The original pause receipt at **18:32:53 UTC on 13 November** records **2,422/2,632** committed outcomes: **1,316 completed, 1,083 errors and 23 unreadable**, leaving **210** targets. An external process later resumed; the coordinator restored the guard and stopped it at the batch-207 boundary on 14 November. Four additional completed PDFs leave **206** targets pending. Their additive integrity and feature evidence is retained separately; the old receipts are unchanged. The later explicit user authorization resumes targeted work in a separate checkpointed lane; it does not rewrite this old run.

Current evidence under `repairs/corpus-assessment-20261113/` includes
`exception-queue-20261114/final/`, the independently reviewed predecessor and unchanged builder,
`late-batch207-features-20261114/`, and `publication-state-final-20261114/`.
The checked public release is
`4b9a7bd126cc17e39dfbe7f8fabafbdb7251dcd32576277f308916f469c9bab1`,
published at 05:25:35 UTC on 14 November. Its exact detail metadata has 324,013
rows. Of the final queue priorities, 834 have unhidden document associations;
all 400 examples have none. This is association evidence, not accepted reading
or search coverage. The connector failed locally, so the public pointer and
hash-verified immutable metadata were checked directly. The export route's 404
records that route and observation time, not every possible unpublished artifact.

`repairs/markup-reparse-20261114/` retains the completed progress receipt, staged
batches, frozen final reconciliation, residual source reviews and native
adoption measurements. `adoption-planning-20261114/pdf-adoption-inputs.json`
binds the 920 recovery readings and existing 14-body private selection evidence.

The independent audit is retained under `coordination/greybeard-root-cause-20261113/review.md`; `inventory/README.md` names the frozen CPU and targeted-page cohorts. The audit's earlier instruction to let OCR finish was superseded by the user's pause, then by the 14 November authorization for the separate checkpointed lane. Ticket rewrites distinguish shared selection and lost page work from native coverage, geometry refusal before routing, markup adoption/compatibility, worker-lifetime RSS attribution and source-role/history gaps.

Closed `ct-chc4` covers the earlier script/JSON-LD/CSS leakage fix. Existing `ct-fk4w` owns downstream document-name/kind decisions using PDF text; `ct-m704` owns the consistent-text and quality handoff. The user owns SereneDB search integration. These consumer boundaries remain separate from extraction-quality acceptance.

`coordination/ocr-offline-ticket-matrix-20261113.md` maps every scoped ticket to
its named direct raw/intermediate/output reviewer, exact artifacts and remaining
gate. A passing script is not that review. Bounded controls do not establish
whole-corpus completeness; missing table contents, handwriting, page-local
recognizer errors and truncated originals remain explicit source-quality gaps.
