# Shared-token rules pass exhaustive literal-boundary checks

All 88,227 saved shared-token regexes match exactly the independently tokenized
spans across 333,368 retained filenames. Each pattern also equals both the current
House generator and the frozen native generator. No production parser or rule
changed; this closes a validation gap in the existing corpus evidence.

| Check | Result |
| --- | ---: |
| Filenames | 333,368 |
| Shared rules | 88,227 |
| Literal candidate positions checked | 25,734,867 |
| Expected and actual accepted spans | 3,265,644 |
| Literal occurrences rejected at token boundaries | 22,469,223 |
| Missing or extra spans | 0 |
| Rules with incorrect saved occurrence counts | 0 |
| Unicode character classifications verified | 1,114,112 |
| New audit tests | 43 passed |
| Full audit elapsed time | 20.7 seconds |

The audit indexes every rule's exact literal variants in a prefix tree. It visits
every occurrence, including occurrences inside longer words and numbers, and
applies the actual compiled regex at that position. Before pruning, it verifies
that every rule consumes only its listed literal and uses the approved zero-width
boundary expressions. Therefore, an absent literal cannot hide a regex match.
This checks the possible matches for 29,412,058,536 rule/filename pairs without
performing that many regex scans.

Expected spans come from a character scanner that does not import the production
lexer or CamelCase splitter. Character classification agrees with the relevant
Python Unicode character class over all code points. Indexed matches equal direct
all-rule scanning on the first 12 corpus names and 32 constructed boundary cases.
Controls cover substrings, repeated tokens, ASCII CamelCase, Unicode letters and
digits, case variants, and the supplied extension/query boundary. Mutations show
that the independent oracle detects weakened boundaries and a multi-part word
incorrectly supplied as a single CamelCase part.

The 1,000-name benchmark completed in 4.9 seconds before the full run. Both runs
retain exact input/implementation hashes and source copies. Together their output
directories occupy about 88 KiB, within the declared time and storage bounds.
The predeclared criteria did not change, and neither run failed.

## Limits and evidence

This verifies shared literal token recurrence on a repeatedly used development
corpus. It preserves the accepted extraction's stem boundary instead of
independently requalifying extension or query parsing. It does not validate
document categories, committee context, semantic meanings, or future filenames.
The four incomplete source payloads and unresolved interpretations remain.

Plan: `tests/house-naming-token-boundaries.md`.
Harness and controls: `tests/audit_filename_token_boundaries.py` and
`tests/test_filename_token_boundaries.py`.
Receipts: `.cache/filename-engine-comparison-20260929/token-boundaries-benchmark/`
and `token-boundaries-full/`, with logs beside those directories.
Changes remain local and uncommitted.
