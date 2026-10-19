# Complete malformed date shapes: results

Accepted run: `.cache/filename-engine-comparison-20260929/malformed-dates-remainders/`.
Previous accepted extractor: `citation-references-first/`.

**435 filenames now retain complete date-shaped text without silently correcting
it or treating its components as separate identifiers.** The full comparison
checks 333,368 inputs; strict parsing remains unchanged for all of them. All
2,562,473 observed field spans match the original input. **1,672 tests pass**,
including 40 new cases since the citation iteration. Generated JSON, ECMAScript
checks and `git diff --check` pass. Native code, existing vocabulary meanings and
official guide definitions remain unchanged.

## Direct comparison and behavior

| Source filename | Earlier interpretation | Current interpretation |
| --- | --- | --- |
| `Transcript_03.01.20231.pdf` | House extracted `20231` as a possible short date; native extracted no date. | Complete `03.01.20231`, warning, no normalized date. |
| `20-11_03-04-20201.pdf` | Both parsers selected `20-11_03` as a date-shaped prefix. House also interpreted the `20201` fragment. | Complete `03-04-20201` with a warning; independent `20` and `11` remain fallback identifiers. Earlier date candidates remain inspectable. |
| `Official Hearing Transcript_10.22.20254.pdf` | Both parsers split a normalized `2025-10-22` from suffix `4`. | Complete `10.22.20254`; the label remains active and the old date/suffix split remains in `suppressed`. |
| `Testimony - Alur - 2022-09-141.pdf` | Both parsers split date `2022-09-14` and suffix `1`. | Label and subject `Alur` remain active; complete `2022-09-141` has a warning and no selected calendar date. |
| `EBM Results - 2022-11-175.pdf` | No complete date shape. | Complete year-first shape with a warning; surrounding title retained. |
| `Poster and Handout_R&E Ligado Hearing MDG Final 1235_05-06-291.pptx` | House treated the ending numeric components separately. | Complete `05-06-291`, independent identifier `1235` and remaining title. |

An appended digit might be an upload/copy suffix, a transcription mistake or
something else. The filename alone does not settle that boundary. The extractor
does not assert that the file or its event date is wrong; it preserves the source
and earlier candidate readings without choosing a corrected value.

The same rule handles date-shaped text with unsupported final-component lengths.
It requires consistent punctuation and plausible month/day positions, and
respects assigned source identifiers and explicit measure references. Generic
label/date layouts retain their useful labels and subjects while expanding only
a partial numeric date component. The shared date-remainder helper preserves
independent text and numbers before or after malformed shapes.

## Verification and rejected candidates

Discovery and targeted checks cover **368 shapes with unsupported year length**
and **67 year-first shapes with unsupported day length**. The latter comprise 60
existing label/date layouts and seven unlabelled names. All 435 retain their full
source text without a selected corrected calendar date. All 66 affected existing
label/date layouts preserve their original label and subject fields exactly.

The full field review accounts for all removals:

- 1,023 generic numeric fields become components of complete malformed shapes.
- 758 earlier name/subject fields remain covered by source fields.
- 207 replaced fields remain verbatim in suppressed alternatives.
- 58 prior date fields remain there with the equivalent `short_date_token` name;
  their raw text, spans, candidates and other metadata are identical.
- 95 subject-location notes now say the text is outside a malformed date. All
  other field attributes and the qualification about identity remain unchanged.

Twenty-five independent numeric assumptions are newly exposed outside the
malformed shapes. None overlap the complete date token. No existing coded field
or code meaning changes, and no native-field omission remains unexplained.

Two full candidates remain rejected and retained:

- `malformed-dates-first/`: removing partial label/date layouts hid useful subject
  fields and left year-first shapes in free text. The accepted implementation
  keeps those fields active and expands only the date component.
- `malformed-dates-preserved/`: the field audit found one lost independent
  identifier, `1235`, before a malformed date. The shared remainder fix preserves
  it, including constructed cases with malformed dates at both ends.

The focused failure logs, full outputs, source snapshots and rejected-run reasons
remain in the comparison cache. `iteration-differences.jsonl.gz` contains all 435
before/after outputs. `candidate-review.json`, `field-review.json`,
`omission-audit.json` and the retained reviewer script record the field accounting.
The validation manifest records exact source hashes and tests.

This is an improvement on reused development evidence, not complete semantic
coverage. Names, local identifiers, titles and other recurring wording still need
review. A new inventory contains 424 filenames with first/second/third-degree
wording, whose context and numbering are the next comparison target; that count
is not yet a count of confirmed defects. Application consumers remain unchanged.
Work is local and uncommitted; no documents were downloaded.
