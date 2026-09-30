# Literal media and endpoint suffixes

The filename reader now separates MP3, MP4, M3U8, ASPX and CFM suffixes using
its existing extension reader. Ten retained names change; the other 333,358
complete outputs remain identical to the accepted report-subjects run. Canonical
House filename formats remain unchanged.

Each changed result exactly matches the complete expected output recorded before
the edit. Ten extension fields are exposed. The existing fallback also separates
the numeric tails in `South Asia UAP 1.mp4` and `South Asia UAP 2.mp4`, producing
12 additional fields overall. Those numbers remain explicitly described generic
identifier assumptions; they are not asserted recording or part numbers. The
MP3 filename's date and nomination wording remain intact.

## Source evidence

Retained receipts distinguish filename suffixes from actual responses:

- `Download.aspx` returned a retained XML attachment with a `floorschedule` root.
- `index.cfm` redirected to a PDF.
- `Error.aspx` occurred as an HTML error-page redirect.
- `master.m3u8` returned an empty body despite its playlist content type.
- MP3 and MP4 headers identify media, but full media archival remains deferred.
- `ByEvent.aspx` appears as a related calendar URL; its response was not reviewed.

No downloads, inferred content types, retrieval-status claims or new dependencies
were added. The existing capture receipt calls the XML attachment an unrecognized
body; this filename-only change does not alter that capture classification.

## Verification

| Check | Result |
| --- | --- |
| Tests | 2,784 passed, including 27 new suffix tests; 119 focused tests passed |
| Full comparison | 333,368 filenames; exactly 10 expected changes |
| Typed adapter compared with engine | All 333,368 equivalent |
| Reconstruction and field spans | 333,368 inputs; 2,577,872 spans checked |
| Native omitted-field detail | All 31,761 rows unchanged; 19 previous review flags unchanged |
| Native fallback differences | Exactly 10 new rows: suffix-free names replace whole-filename name assumptions |
| Corpus mechanical checks | Passed; zero structural collisions; four incomplete source payloads remain |
| Catalog and portable regex checks | Three generated artifacts; 100 regexes; 54 positive and 54 rejection cases |

The ten fallback differences were reviewed individually. Each preserves the
source text through the stem, separate extension and original pieces. All other
native fallback details remain identical. The accepted earlier strict correction
for joined bill/Congress digits remains the only exception against the frozen
strict baseline. No new strict result changes occur in this iteration.

Evidence is under `.cache/filename-engine-comparison-20260929/`: the
`literal-suffixes/` and `literal-suffixes-corpus/` directories,
`literal-suffix-expected.json`, both literal-suffix source-review files,
`review_literal_suffixes.py`, and the focused/full test logs. The validation
manifest records source and evidence hashes. These reused inputs establish
preservation on the development corpus, not complete semantic accuracy.

## All output reports rechecked

All 11 Markdown files under `output/` were read, including the segmentation
report, corrected committee-context experiment, superseded first attempt and
PDF content review. Their paths and hashes still match the retained
`output-category-followup.json` inventory. Current-reader checks preserve the
reviewed fields for all 21 candidate-family examples and all 15 committee-context
probes.

The second experiment supports committee-context review: source-label agreement
increased from 77.84% globally to 84.39% with adaptive subcommittee/Congress
grouping. Committee-local vocabulary reached 85.66%, but its 1.27-point gain over
adaptive grouping missed the predeclared two-point threshold. It tested 11 broad
categories, not a finer taxonomy. The useful distinctions include Rules Committee
prints, explanatory statements, manager's amendments, notices and explicit
companion formats. Literal wording rules now cover the earlier notice, summary
and manager's-amendment gaps; source associations and committee-local meanings
remain separate from filename observations.

Changes remain local and uncommitted. Full semantic coverage is not established.
