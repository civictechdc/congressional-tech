# Find and prioritize text repairs without repeating OCR

Assess every retained body cheaply, then inspect original pages where evidence
is missing or suggests loss. Keep source roles, completeness, recognition
quality and repair cost separate. A score orders investigation; it never accepts
text, discards a source or authorizes OCR. OCR remains paused and publisher
refetch remains deferred.

`ct-n3ik` owns this assessment and calibration plan, including its existing
selective backend comparison. The repair tickets below keep their existing
acceptance work. This extends the existing inventory rather than creating a
second corpus or another selection authority.

## Verified population and units

The retained census is frozen at body-text snapshot `919214147503378993` and
readings snapshot `4381392526125190580`, before the later recovery outcomes.
Its selected release is
`55c14dcda87ae954583bf518050b3bd45db6aed49c88c53413260c1d092ef105`.

| Unit in this snapshot | Count | What it means |
| --- | ---: | --- |
| Distinct completed current-version extracted bodies | 607,584 | Content identities, including unselected captures; not logical documents. |
| PDF bodies | 295,770 | One body per source hash at the frozen reading version. |
| Recorded PDF page slots | 7,764,694 | Lengths of retained PDF page-offset arrays; original physical page counts still need source comparison where suspect. |
| PDF pages marked OCR | 2,571,182 | Historical provenance, not a count of verified accurate pages. |
| Completed HTML / XML bodies | 192,530 / 117,517 | 310,047 bodies; their one-slot text offsets are not physical pages. |
| Completed WARC bodies | 1,767 | Require payload and saved-body reachability qualification. |
| Logical selected-release document rows | 323,564 | 310,979 join to a text result; multiple logical rows can share a body. |
| Extracted Unicode characters, all four parsers | 29,854,824,445 | Includes whitespace; this is text volume, not pages or words. |
| Existing proposed non-OCR cohort | 310,964 | Completed HTML/XML plus 917 additional recovery targets; not 310,964 defective documents. |

The user clarified the scale as approximately **2.7 billion tokens across
7.7 million pages**. The token figure is a user estimate; the tokenizer, input
selection and counting convention are not pinned. The page estimate agrees
with the frozen 7,764,694 recorded PDF page slots, subject to the source-count
qualification above. The denominator behind approximately 500,000 documents also
differs from the frozen logical-document count above. Future census exports must
name the snapshot, selected/unselected scope, body/document/reading/token unit,
and whether a page count is inferred or source-confirmed. Recovery additions
join by exact actual reading key, not by adding completed counts to this table;
a recovery result can replace an existing body's older result.

Count evidence: `investigations/text-quantity-review-20261113/population.json`,
`freeze.json`, `report-manifest.json`, and
`quality-expansion/page-feature-full-summary.json` under the main checkout's
`.cache/archive-release/`. The census script defines `pages=len(page_offsets)`.

### Paused recovery added to the frozen census

The 14 November reconciliation preserves the census above and joins the recovery
frozen after batch 205 by actual reading and output identities. It accounts for
610,216 distinct bodies: 608,900 with completed extraction metadata, 1,083 recovery errors,
23 unreadable decisions and 210 held targets. The completed population combines
607,584 census bodies with 1,316 recovery bodies; those completed sets do not
overlap. Historical refusals and alternative versions remain separate records.
These are retained extraction states, not source-quality or accepted-text counts.

The combined PDF metadata records 296,686 bodies and 8,141,096 page-offset slots.
This larger figure includes 376,402 recovery slots absent from the earlier
7,764,694-slot census. Physical page completeness still needs source evidence.
No new token total was calculated. Document-body exposure remains explicitly
bound to release `55c14dcda87a…`; it is not a current selected-text manifest.

Additive checks preserve the original paused-run evidence. The final 66 output
rows passed text hash, byte-count, page-offset and OCR-provenance integrity
checks. The pinned native reader independently enumerated exactly 2,399
recovery reading keys and 1,316 text keys, resolving the Python metadata
reader's codec refusal without changing any manifest. These checks establish
stored-output integrity and membership, not transcription accuracy.

The unchanged PDF feature definition now covers the additional 916 completed
PDF bodies. It read only their 806,874,296 retained text bytes and reuses all
295,770 baseline feature rows in place. It does not rerun extraction or infer
source roles. Current-version compatibility, source-qualified findings,
held-out calibration and accepted selection remain open.

Evidence lives under
`ocr-recovery-20261113/repairs/corpus-assessment-20261113/` in the same durable
archive root: `current-reconciliation/`, `tail-integrity-20261114/`,
`native-membership-20261114/` and `pdf-feature-delta-20261114/`. Frozen input
identities and original receipts remain preserved.

The independent review at
`current-reconciliation/reviewer-shared-reader/independent-review.md` approved
this accounting and all three additive packets. It compared original and final
metadata in both directions, directly read seven record chains and one bounded
retained text, and rejected planted identity, completion, qualification and
feature defects. Its 198 checks support the stated metadata and integrity
scope; source transcription and held-out calibration remain separate work.

The four previously reviewed assessment examples now have exact links in
`review-links-20261114/`. S046, S055 and S150 match their historical PDF reading,
text hash and page-1 features. S301's reviewed HTML intermediate also matches;
its separate response-role result remains a private candidate, with no lake
reading. Independent review approved these links only. The original review
scopes and unqualified proposal flags remain intact.

An external recovery process subsequently resumed at 05:34/05:40 UTC on
14 November. The coordinator restored the pause guard and stopped recovery at
the batch-207 boundary at 05:50 UTC. Four additional outputs committed before
shutdown, leaving 206 targets pending and 1,320 completed recovery outputs.
They remain outside the reviewed batch-205 reconciliation and PDF features;
neither quality, integrity nor accepted selection follows from their completion.
The five frozen extraction source pins still match, and all seven identified
recovery processes have exited. The separate operational evidence is
`ocr-recovery-20261113/coordination/pause-conflict-20261114/` and
`pause-preserved-final-20261114.json` in its parent directory. OCR remains paused.

The separate `late-batch207-20261114/` packet preserves the four new metadata
chains and the original pause record's replacement locator. The later
`late-batch207-integrity-20261114/receipt.json` verifies their committed text
hashes, UTF-8 byte counts, offsets and OCR provenance. Together with the prior
receipts, stored-output integrity now covers all 1,320 completed recovery
results. The staged text file is absent, so staged-to-committed parity remains
unknown; source accuracy, current-version compatibility, page features and
accepted selection remain unqualified for the four late results.

## Reuse the work already retained

The existing census already stores body identity, parser/version, text hash,
UTF-8 bytes, Unicode/non-whitespace counts, selected document labels and status.
The full PDF feature pass already stores each page's character count and OCR
flag, blank runs, sparse-page repetition and document distributions for all
7,764,694 recorded pages. Reuse these 58,828,652 bytes of feature Parquet before
opening original PDFs or decoding 17.944 GB of PDF text again.

The current repair inventory provides 18,777 candidate bodies, 26 targeted PDF
bodies with 61 reviewed page units, 14 existing PDF candidates covering 281
pages, and 72 checked page controls. None is a prevalence estimate. Preserve
the review's scope: C015 is a cleanup/selection-equivalence control with a
missing handwritten signature; it is not complete form transcription.

For each body and page, retain:

- Raw body SHA, original/capture location, source format and observed source role.
- Actual reading key `(body_sha, parser, parser_version)`, text hash, selected
  key and alternative attempts; keep an absent result distinct from empty text.
- Page number (one-based PDF index), displayed label when known, byte offsets,
  and source/render/native/pre-cleanup/final artifact paths, hashes and locators.
- Feature-definition version, measured values and missing measurements. Missing
  geometry or source inspection is unknown, never zero coverage or a good page.
- Each finding's reason, measurement/runtime/direct-review basis, reviewer when
  applicable, observation scope, and the proposed action with its prerequisites.

Keep capture-to-body and document-to-body associations outside the distinct-body
assessment table. Score each exact body/reading once, then join the result back
to logical documents. Preserve feed entries and portfolio members separately;
deduplicating equal prose must not collapse their identities or links.

## Staged assessment

1. **Reconcile metadata without reading source content.** Freeze current catalog
   and selection identities; reuse matching census rows and add only new or
   changed reading keys. Account for every body as assessed, missing evidence,
   unsupported, pending or refused. Index exact hashes before candidate joins;
   avoid repeated whole-table aggregates and text scans. A single bound or
   parser refusal is an explicit state, not an empty successful document.

2. **Use retained text and page features to rank.** Keep page-level minima,
   interior blank runs, sparse repeated furniture, mixed OCR/native gaps,
   control/replacement characters, suspicious glyph spacing, exact duplicate
   text, and output loss between known versions as separate features. Compare
   within document kind/format/era/language/source family. Kind labels can be
   wrong or multilabel; retain an unknown stratum. Long output and a completed
   status must not suppress investigation of missing pages, bullets or values.
   Only compute missing features, in the next necessary text read, with a
   versioned completion marker per input partition.

3. **Resolve source role before choosing an extraction repair.** Use the shared
   bounded markup readers, the dedicated feed reader, retained capture history
   and CT's narrow response-role observations. Error phrases alone cannot label
   a document. Distinguish error, waiting, zero-payload, feed, manifest/metadata,
   portfolio/container, legitimate empty and unassessed. A saved error body can
   coexist with a successful retained copy; reconcile that copy before adding
   an unresolved source to the deferred refetch list.

4. **Read original structure for nominated pages and a random control sample.**
   Use spicy-docs' selected-page/native observation APIs for PDF bounds, crop,
   rotation, native spans/font/glyph issues, raster areas and vector activity.
   Compare X and Y coverage, orientation and placement with the actual output.
   Captions, vertical notices and page furniture can exceed fifty characters
   while the body disappears. Vector ink also occurs on legitimate blank grids,
   so geometry alone is a feature, not a verdict. Original opening/container
   checks remain document-level; page extraction remains selective.

5. **Compare source, intermediate and output.** Identify the first loss:
   absent raw content, parser/native loss, destructive cleanup, OCR error, or
   wrong reading selection. Reuse pre-cleanup text where its identity and page
   coverage are proved. S055/S150's missing bullets call for re-normalization
   when that intermediate is retained; S017's lost native tail can be reread
   natively. Q007's captions do not cover its table/chart values. S149's fluent
   name/title do not establish correct date or checked-choice extraction.
   Table cells, signs/decimals, labels, names/dates, reading order, handwriting
   and figure text need source-specific checks, not a prose-quality threshold.

6. **Propose the smallest repair.** The offline assessor emits one of `keep`,
   `reparse`, `renormalize`, `native_reread`, `selective_ocr`, `manual_review`, or
   `refetch_deferred`, plus all reasons and unresolved prerequisites. `keep`
   means preserve the existing reading at the stated scope, not certify the
   uninspected remainder. Non-OCR parser-policy updates may nominate a complete
   qualified HTML/XML cohort without labeling every member defective.
   `selective_ocr` requires exact reviewed page scope and stays blocked while
   paused. Ambiguous tables/forms may later justify a bounded LLM/VLM comparison,
   but no provider result is accepted from plausibility alone.

7. **Qualify and select separately.** Compare baseline, candidate and a same-code
   repeat. An independent reviewer reads the original, intermediary and raw
   output contents; scripted checks supplement this review. Preserve old
   selected output if a candidate fails. Only `ct-55qo` changes selection after
   qualification; `ct-aitp` checkpoints valid pages and `ct-a73a` measures the
   actual supervised request. Do not start a recognizer or acquisition from a
   score or assessment record.

## Scores, uncertainty and calibration

Begin with a transparent **ordinal review priority**, not a claimed probability:
directly reviewed loss or a selected wrong source first; runtime/provenance
failures next; measured anomalies next; no-trigger and unassessed controls last.
Within each stratum retain coverage, recognition, role, normalization and
provenance findings as separate axes. Selected exposure and estimated repair
cost are sorting columns, not quality evidence. A high readability score cannot
cancel a source-confirmed omission. Do not let many correlated length features
count as several independent votes.

Freeze a pilot before inspecting labels: the named confirmed failures and
controls form a **development** set. Draw a separate held-out sample by source
hash, document family, format, era, language and layout. Keep related captures,
exact-text template families and pages from one document in the same split.
Include source-disjoint and later-capture holdouts where available. Deliberately
include completed, long, normal-score and no-trigger documents; sampling only
the repair queue cannot measure false negatives.

Start with a feasible 200-body held-out review budget and record inclusion
probabilities. Cover at least 60 no-trigger/low-risk bodies, 40 legitimate
short/empty/repeated/metadata/container controls, 40 high-signal bodies, 30
mixed-layout/forms/tables and 30 response-role/encoding families; deduplicate
overlaps and publish the final disjoint allocation. These are planning quotas,
not evidence that 200 bodies can bound every source family's error rate.
For long PDFs review nominated pages plus seeded random pages and first/middle/
last pages, with the unreviewed pages explicit. Only page-level claims follow
unless the whole document was read. Use document-level clusters in uncertainty
estimates; pages from one template are not independent samples.

Reviewers blinded to rank/route labels record: substantive omissions, invented
content, wrong numbers/names/dates/choices, ordering, role and useful coverage;
record uncertain cases rather than forcing a label. Measure per-action precision,
false-negative rate among low-risk pages, per-family coverage and unknown share.
Review both directions of every changed candidate and report confidence
intervals using the sampling design. Zero observed failures does not establish
zero population error. Keep prioritization thresholds provisional until this
held-out evaluation is complete.

Plant at least a missing substantive paragraph/bullet/table value, a plausible
wrong date/number, a mislabeled error page and an omitted page whose remaining
text is long/fluent. An author-independent reviewer must reject each from the
raw source, not by seeing the planted label. Preserve legitimate short, blank,
photo, redacted-grid, non-Latin, repeated amendment and valid-feed controls.

## Keeplist inspiration and limits

Read-only source reference: Keeplist Backend commit
`fb1245c2ca3e838d6ce896c9df76464a57b75714`.

| Reuse | Source and CT adaptation |
| --- | --- |
| Independent measurement axes | `keeplist_io/scrape/parsers/text_v2.py:54-85,721-774`: body, rendering, error and fact evidence remain separate. CT adds source/page coverage and cleanup loss; factual-looking text does not prove accuracy. |
| Unicode and link-label preservation | `text_v2.py:172-238,735-765`: preserve non-Latin text and link labels, compare counts in the same units. Use shared spicy-docs markup events, not a Django dependency or reconstruction of links already lost from plain text. |
| Replayable alternatives | `parsers/html.py:306-390,421-460`: retain every candidate hash/verdict, separate scoring from selection. CT must inspect successful outputs too; Keeplist's failure-only rescue skipped passing raw fallbacks. |
| Independent frozen evaluation | `linkunderstanding/evaluation.py:54-137,275-430`: bind inputs, versions, runs and reviewer labels; exclude contamination, separate unknown costs, use paired comparisons and explicit unresolved states. Adapt the pattern to body/page clusters and keep model execution disabled. |
| Measured threshold rejection | `docs/plans/markdown-rescue-hardening.md`: raising 2.5 to 3.5 removed no junk in that retained experiment and lost useful pages; a title/script check was reverted after false vetoes. CT needs source mismatch evidence, not a higher generic score. |

The existing CT applicability probe already ran these scorers on 376 retained
cases / 372 bodies. Both garbled forms and S150's missing-bullet output passed;
10 of 18 source-checked legitimate short documents failed; 14 of 29 error
responses cleared the body/render/error checks. Reuse that evidence rather than
repeating it. The eight-source original-HTML probe found useful focused regions,
but five whole-body fallbacks still passed. These are exploratory results, not
a fresh held-out CT calibration.

Do not copy Keeplist's 2.5 threshold, English readability, price/contact signals,
whole-document fallback ordering, or phrase-only error veto as CT acceptance.
Its own `test_text_v2.py:779-809` explicitly retains a false positive on genuine
"moved or deleted" prose. `ValidationContext.profile` is currently not used by
the scoring function. Reuse existing maintained capabilities; extract a shared
leaf measurement only when CT demonstrates a missing useful signal, and keep
the application-specific selection policies separate.

## Cost, checkpoints and sequencing

| Existing measurement | Result | Boundary |
| --- | --- | --- |
| PDF text-feature pilot, largest source Parquet file | 71,824 pages; 1.55 s; 0.83 GiB RSS | Retained text, not opening/rendering original PDFs. |
| Remaining PDF text-feature pass | 169.5 s; 1.12 GiB RSS; zero census mismatches | 17.764 GB newly read; full retained result covers 17.944 GB. Do not repeat. |
| Metadata inventory assembly | About 1 s script / 2 s supervised; 0.61 GiB RSS | Reuses 607,584 metadata rows; not a source reparse estimate. |
| Retained markup CPU pilot | 34 bodies / 1,179,343 source bytes; 0.109 s; 0.05 GiB RSS | Small local files; not full-cohort throughput. |

Before a broad source read, measure a representative source-size/layout pilot
and the largest retained eligible body for each lane, with cold/warm cache
conditions stated. The 38.9 MB House Atom feed has a dedicated reader; it is not
a generic-prose performance proxy. Account for original bytes, decompressed
bytes, PDF page count, render pixels, parse time, request peak RSS, output and
diagnostic bytes, read-ahead, workers and remaining disk. Use the repository
watchdog; stop and retain a refusal if a bound is exceeded. Do not extrapolate
OCR cost from text-feature speed. Sum per-stratum measured work with an explicit
unknown-cost bucket before proposing recognition.

The 2.7-billion-token estimate is not an LLM-scoring workload. Cheap metadata and
text measurements cover the corpus first. On that estimate, even 0.1% would be
2.7 million text tokens before prompts, retries and image inputs; this arithmetic
is a planning illustration, not a token measurement. Count the exact nominated
page/crop prompts with the chosen tokenizer only when a model comparison is
proposed. The retained optional comparison has five bodies / eleven pages,
not all 61 repair-page units or all 7.7 million pages. Report text input/output,
image/render units, repeated prompt/context, failed attempts and cached-input
assumptions separately. Cost is the sum of measured units times the then-pinned
provider/model prices, with explicit call/token/dollar caps and an unknown bucket
for unpriced work. No model, prompt, price or recognition budget is adopted here.

Partition new observations by source/readings/feature-policy identity. Skip a
matching completed partition before opening raw data; use atomic manifests and
retain partial/incompatible/corrupt states separately. Store durable evidence
under the main checkout's `.cache/archive-release/`. Use existing page
checkpoints and exact-page override identities for any later repair; keep
unchanged pages. Recompute a score policy from retained features without
rerunning extraction. A parser change recomputes only its exact eligible input
predicate, followed by combined-generation invariants.

Deliver in this order: inventory reconciliation and offline recommendations;
independent calibration; qualified non-OCR reparse/cleanup work; measured source
feature expansion; then an explicit selective recognition proposal. OCR and
refetch stay paused throughout the first stages.

## Existing ticket ownership and remaining gates

| Ticket | Work retained by that ticket |
| --- | --- |
| `ct-n3ik` | Assessment inventory, priority policy, source-qualified typeset/scanned/mixed split, held-out evaluation, backend/cost proposal and optional complex-page comparison. |
| `ct-hz8y` | Incomplete-native/vector detection and source-confirmed page recovery, including held-out omission controls. |
| `ct-kfsd` | Historical cleanup exposure, retained-intermediate reuse, corrected selection/publication and composed-WARC qualification. |
| `ct-cbkz`, `ct-f6hr` | Qualified non-OCR cohort/pilot, markup normalization, encoding/DOCTYPE compatibility and reparse acceptance. |
| `ct-en4n`, `ct-z4w5` | Qualified response/container/feed roles, retained source reconciliation and deferred acquisition list. |
| `ct-55qo`, `ct-aitp`, `ct-a73a` | Actual reading selection, durable page reuse, and supervised request resource/recovery evidence. |
| `ct-yy07`, `ct-t4p3` | Typed geometry fallback and page-local recognition crash policy; real recovered output remains gated by the OCR pause. |

No ticket closes from this plan or an offline priority output. Full coverage,
held-out detector accuracy, source-qualified repairs and publication/readback
remain separate acceptance claims.
