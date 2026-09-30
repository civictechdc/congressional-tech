# House version components: verified improvement

The full comparison adds 16 fields across nine filenames. Another 12 filenames
receive only the declared reader-name or description updates. All previous source
fields and strict parsing results remain intact; the other 333,347 complete
outputs are identical to the accepted print-wording run.

- Four filenames now expose separated `IH` as Introduced in House. The two
  PDF/XML pairs also have explicit `legis-stage=ih` in their original House XML.
- Two of those names now expose terminal `Filed` wording. It establishes no
  verified filing action.
- Four RSC/SCP filenames now expose the local marker and adjacent `ih`.
  The shared local-component reader uses visible uppercase/lowercase structure,
  without expanding the acronyms or adding their names to an allowlist.
- `BILLS-117OAWPih.pdf` now exposes OAWP plus ih. Its original XML explicitly
  records those two fields. The previous ambiguous Pih reading remains available;
  consumers must preserve separate observations rather than flatten field names.

CPT's existing spelling and numeric forms remain supported. Local numbers are
reserved before date/member scans, including calendar-plausible numeric controls.
Ordinary word endings, unrelated person/amendment identifiers and query text
remain outside the new readings.

## Validation

| Check | Result |
| --- | --- |
| Fixed comparison corpus | 333,368 filenames |
| New fields / names receiving fields | 16 / 9 |
| Metadata-only changed names | 12 |
| Previous source fields and strict results | Preserved across all inputs |
| Typed adapter versus engine | All 333,368 equivalent |
| Source-field spans checked | 2,578,117 |
| Full test suite | 2,903 passed, including 40 new tests |
| Native omission/fallback details | Identical to the previous accepted run |
| Corpus checks | Passed; zero structural collisions; four incomplete payloads remain |
| Generated catalog / portable regex checks | Three artifacts; 100 regexes; 54 positive and 54 rejection cases |

The first full test run caught a test that collapsed repeated field names into a
dictionary and selected only the last version observation. The corrected test
checks the retained uncertain Pih reading and the added OAWP/ih observation
separately. The failure log remains retained. No parser change was needed after
the full run. The full comparison and corpus outputs therefore use the same
verified implementation as the final test suite.

The first discovery scan was interrupted for repeatedly copying the guide inside
its loop. The retained scan caches the guide once and reads the unchanged frozen
outputs; it recorded the expected additions before implementation edits.

Evidence is under `.cache/filename-engine-comparison-20260929/`:
`version-components/`, `version-components-corpus/`, the proposed rules and
pre-edit expected outputs, original XML subtrees, source inventory observations,
focused/full preservation reviews, both test logs and the validation manifest.
The existing Congress-boundary correction remains the sole strict-baseline
exception. Source hashes and the changed regression test are retained.

This is development evidence on reused inputs, not complete semantic validation.
Source status and acronym expansions still require independent context. No
downloads or new PDF content review were performed. Changes remain local and
uncommitted; the overall goal remains incomplete.
