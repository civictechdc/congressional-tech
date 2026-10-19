# Reference-assisted extraction and corpus analysis

House naming now supports caller-supplied, Congress-specific surname references
and standalone token/residual analysis. The native parser remains an independent
comparator. No built-in surname list, data download or native-parser dependency
was added.

The final evidence is in
`.cache/filename-engine-comparison-20260929/context-corpus-final/`.
The saved `extraction-named-dates` outputs are the control for default behavior.
Both engines also received the same retained legislator references when checking
optional member/title extraction.

| Check | Result |
| --- | ---: |
| Default extraction results preserved exactly | 333,368 |
| Legislative inputs checked with surname references | 32,241 |
| Member/title splits recovered | 11 |
| Native member/title fields retained with identical spans | All 11 cases |
| Shared-token regexes generated | 88,231 |
| Observed token/name pairs checked | 3,215,523 |
| Token occurrences recovered with exact source spans | 3,265,670 |
| Token spelling and boundary controls | 102,926 |
| Tests passing | 1,131 |

## Surname references

`Engine.extract(filename, member_surnames={"119": ["Clyburn"]})` separates
`RepClyburnRenewingtheAfricanAmericanCivilRightsNetworkAct` into the printed
member marker, surname and title. It keeps the full original description and
strict naming record. The CLI accepts the same mapping with `--member-surnames`.

The supplied reference determines eligible surnames; source punctuation can be
omitted inside a surname. The longest eligible spelling wins at a capitalized
title boundary. Without a reference, or with a different Congress, the package
leaves the name/title boundary unresolved. Constructed tests cover multipart and
previously unseen surnames, missing titles, wrong Congresses and misleading word
prefixes such as `Smithsonian`.

The comparison used `.cache/source-models/legislators-current.json` and existing
service-date selection code. This retained file is a current-member dataset with
those members' service history, not a complete historical membership list.
The 11 matching filenames therefore establish parity for this supplied context,
not comprehensive member identification. Even `RepHoeven` stays a literal naming
marker; the package does not assert an office or sponsorship.

## Shared tokens and remaining text

`house_naming.corpus.filename_tokens()` preserves words, numbers and literal
CamelCase parts. `shared_token_pattern()` generates exact regexes for the observed
variants. The corpus contains 333,175 inputs with at least one shared token;
that measures recurrence, not document identity or parsing completeness.

Tokens match the native helper on 329,335 inputs. On the other 4,033, the new
extractor excludes separated query text or additionally recognized extensions.
Every retained token matches the native token and location inside the shorter
stem. Regex checks recover all observed occurrences with no extras in the tested
token/name pairs. The full absent-rule-by-filename cross product was not tested.

`residual_fields()` subtracts specific fields from broader text and reports the
remaining spans. It does not let a broad description or fallback name conceal
that text. The audit independently checks every alphanumeric character against
covered and remaining positions, including overlapping captures.

The first pass exposed an audit error: reviewing complex amendment IDs also
treated simple parsed IDs as unexplained. That is corrected and covered by a
regression test. The earlier run is retained as `context-corpus-first`.

## What the review found next

The new inventory exposes actionable gaps alongside legitimate free-text names
and titles. Direct native/House outputs are retained in `next-cases.json`:

- `brown-statement-040924`: the date is recognized, but bare `statement` remains
  inside an assumed name rather than becoming a literal document label.
- `official-hearing-transcript_1032018`: the label is recognized, but the seven
  digits need calendar candidate analysis without choosing a date ordering.
- `19-13_02-14-19`: a rejected numeric date candidate prevents the later
  `02-14-19` from being considered. Both parsers miss that useful candidate.
- `BILLS-119-CommitteePrintSubtitleD-A000370-Amdt-116.pdf`: the sponsor-shaped ID
  and amendment number are retained; the committee-print/subtitle wording remains
  inside the broad subject.

These findings keep the full filename-interpretation goal open. The new helpers
make those gaps inspectable; they do not establish complete semantic accuracy.
Changes remain local and uncommitted.
