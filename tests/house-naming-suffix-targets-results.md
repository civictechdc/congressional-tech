# Legislative suffix targets: verified improvement

Existing readers now recover 30 additional fields across ten filenames. The
full comparison preserves every previous complete result after removing only
these additions; all other 333,358 outputs are identical.

- Six reported-bill filenames expose the literal p marker and numeric suffix
  identifier. The reader does not assign an official report, part or page
  identity. Their three XML bodies and PDF opening pages identify different
  committee versions of H.R. 3 and leave the report number blank.
- Four filenames expose explicit substitute targets, including AINStoHR1759,
  AINStoHR1994, the spelled-out substitute to HR207, and ANStoHR3633.
- The last target also exposes offeredby and ChairmanThompsonofPennsylvania as
  separate literal fields. Its PDF heading confirms the wording; the meeting
  description says withdrawn. Neither offering history nor person identity is
  inferred from the filename. The existing U1 revision field remains intact.

The change reuses substitute-target and publication-suffix-marker. It adds no
parallel rule family. Target numbers are captured before generic dates, and
owned person/amendment slots remain protected. Existing target-rule callers
were independently checked over 33,859 source slots; the extended grammar adds
no other matches there.

## Verification

| Check | Result |
| --- | --- |
| Full fixed corpus | 333,368 filenames |
| Added fields / affected inputs | 30 / 10 |
| Previous complete outputs preserved | All 333,368 |
| Typed adapter versus engine | All 333,368 equivalent |
| Raw field spans checked | 2,578,147 |
| Full regression suite | 2,939 passed, including 36 new cases |
| Native omission and fallback details | Identical to the previous accepted run |
| Corpus mechanical checks | Passed; zero collisions; four incomplete source payloads remain |
| Catalog / portable regex checks | Three artifacts; 100 regexes; 54 positive and 54 rejection cases |

Source review read seven original meeting-document XML entries, three cached
bill XML openings and four PDF first pages through native text extraction. Two
first pages were also rendered and inspected. The cached body hashes were
verified. No downloads or OCR were used; this was not an every-page review.

Some high-ranking text residuals need no parser change. Direct inspection shows
that hanging pdf text in the reviewed transcript slug is already captured as
ignored_suffix. The residual word of in a meeting-results heading is not a
standalone name field: the parser retains the full heading and the separate
recognized wording. Residual rankings identify review candidates, not a count
of missing metadata.

Evidence is under `.cache/filename-engine-comparison-20260929/`:
`suffix-targets/`, `suffix-targets-corpus/`, the pre-edit expected fields and
candidate rule, caller audit, raw source records, XML/PDF review records,
rendered first pages, focused/full preservation checks, test logs and validation
manifest. `fallback-wrapper-probes.json` preserves the residual counterchecks.
The existing Congress-boundary correction remains the sole strict-baseline
exception.

These reused inputs provide development evidence, not complete semantic
validation. Changes remain local and uncommitted; the overall goal remains
unfinished.
