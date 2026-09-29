# Filename regex corpus

`congress_api.filenames` extracts the information **written in a filename**.
`congress_api.filename_corpus` builds a searchable set of recurring-token regexes
and checks the parser against every literal spelling in a saved inventory.
Neither command downloads documents or modifies publisher metadata.

```python
from congress_api.filenames import parse_filename

parsed = parse_filename('HHRG-113-AG00-Wstate-ColbyJ-20130314.pdf')
for match in parsed.matches:
    print(match.rule, {field.name: field.raw for field in match.fields})
```

The named captures include the Congress (`113`), committee routing code (`AG00`),
document marker (`Wstate`), subject token (`ColbyJ`), date token (`20130314`), and
extension (`pdf`). Every capture retains its original spelling and start/end
character offsets. Calendar validation supplies candidate date readings without
assigning a role such as hearing date or publication date.

## What is preserved

- Published-package prefixes, Congress numbers, publication codes and numbers.
- Committee routing codes, document markers and document identifiers, including
  vote ranges and references embedded in those identifiers.
- Subject/name strings and Bioguide-shaped identifiers, without resolving people.
- Measure references, including multiple measures in one filename; amendment,
  print, fiscal-year, revision, part, exhibit and agenda-item tokens.
- Explicit document wording and joined lowercase conventions, such as
  `testimonysenatebudgetcommittee` and `supportfor`.
- Date-shaped strings, ambiguous date readings, UUID-shaped and hexadecimal
  identifiers, stacked extensions, and unrecognized suffixes.
- Every remaining character through lossless `pieces`; no unrecognized text is
  silently discarded. These pieces reconstruct the exact input filename.

`Bio` remains `Bio` even if the linked PDF contains testimony. `BILLS` remains
a naming prefix even if the PDF is an amendment. A committee routing code is
not a resolved committee identity. Unknown fields remain unknown.

## Bill types, versions and filename modifiers

`bill_codes.py` retains the eight bill types and 53 common version codes listed
in [GovInfo's Congressional Bills help](https://www.govinfo.gov/help/bills),
checked September 29, 2026. Recognized fields carry a normalized `code`, the
published `label`, and `vocabulary_url` alongside the unchanged `raw` text and
offsets. This table is a vocabulary, not an exhaustive list of valid filenames.
The House's [Document Naming Conventions, page 6](https://www.govinfo.gov/content/pkg/GOVPUB-Y1_2-PURL-gpo156119/pdf/GOVPUB-Y1_2-PURL-gpo156119.pdf#page=6)
separately defines `PIH` as a pre-introduced measure. It receives that label and
the House guide's source URL, without changing the 53-code GovInfo vocabulary.
The guide describes unnumbered measures, but actual House names such as
`BILLS-115hres5-PIH-FINAL.pdf` also print a number. Both claims survive; this parser
does not erase the number or infer current bill status. `PIS` is not assigned the
same meaning by analogy. Other tokens without an implemented vocabulary mapping
remain available without an invented label.

| Filename | Extracted parts |
| --- | --- |
| `BILLS-115hr1892eas2.pdf` | Congress `115`, bill type `hr`, number `1892`, version `eas`, numeric modifier `2`. |
| `BILLS-113-HR4660ih(asfiled).pdf` | Congress `113`, bill type `HR`, number `4660`, version `ih`, annotation `asfiled`. |
| `BILLS-1172126r4ih.pdf` | Congress `117`, number `2126`, prefix `r4`, version `ih`; no bill type supplied. |
| `BILLS-119HR2162HoneyIntegrityActih.pdf` | Number `2162`, descriptor `HoneyIntegrityAct`, version-shaped suffix `ih`. |
| `BILLS-118 hres_44HR277HR288HR1615HR1640_xml.pdf` | Resolution type `hres`, number `44`, all four following measure references, filename format marker `xml`; actual extension `pdf`. |
| `BILLS-118 hres_HR2670_2_xml.pdf` | Resolution type `hres` without a number, reference `HR2670`, unexplained numeric suffix `2`, filename format marker `xml`. |
| `BILLS-115HR__-RCP115-77.pdf` | Type `HR`, number placeholder `__`, print Congress `115` and print number `77`; no bill number invented. |
| `BILLS-113hrFARMEXT-SUS.pdf` | Type `hr`, literal title `FARMEXT`, local code `SUS`; no official version label inferred. |

GovInfo labels the actual `BILLS-115hr1892eas2` package as Engrossed Amendment
(Senate), confirming the `eas` base code. The help page does not define the
numeric modifier's meaning. Modifiers and annotations stay literal; they do not
become inferred publication dates, current bill status, or revision chronology.
A House bill can have a Senate edition: bill type and version are separate fields.

Descriptions are kept separate from version codes. Attached suffixes can have
ambiguous boundaries: in those cases `candidates` lists possible codes ending at
the captured field's end, and no single label is selected. The explicit
user-reviewed exception `Interiorih` splits into `Interior` + `ih`; it does not
change how a bare `rih` code is read. Consecutive digits without a separator remain
one literal numeric field; this parser does not resolve bill identity from an
ambiguous concatenated number.

A dictionary hit alone does not establish a version boundary. `ANSServices`
and `HR1Services` keep the whole `Services` descriptor; `es` remains only a
candidate, without an official code/label. The parser accepts explicit separated
versions, numeric boundaries, explicit marker/version slots, visible acronym/code
case boundaries, and the reviewed joined `ih`/`pih`/`pis` conventions. A separated
version wins over an earlier word ending: `ANSServices-ES` retains `Services-`
and the printed `ES`. Mixed-case `OAWPih` retains both `ih` and `pih` as candidates
alongside the whole descriptor. These conventions extract syntax, not bill status.

Multiple references such as `HR6147HR6258` remain a measure list, not a version
and numeric modifier. Case, parentheses, hyphens and all remaining text survive
in the original filename and lossless pieces.

The Congress number (`119`, for example) belongs to the outer `legislative-file`
match and stays separate from bill number and text version. For observed
`Rep` + surname + title descriptors, the parser also returns `member_marker`,
`member_surname_token`, and `title_token`. For example:

```text
BILLS-119HR9269RepClyburnRenewingtheAfricanAmericanCivilRightsNetworkActih.pdf
congress:             119
measure_token:        HR
measure_number:       9269
member_marker:        Rep
member_surname_token: Clyburn
title_token:          RenewingtheAfricanAmericanCivilRightsNetworkAct
version_token:        ih
```

The full descriptor also remains available. Name boundaries come from optional
legislator data, not a surname list in the parser. The builder reads existing
`Legislator` models and groups surnames by service-date overlap with each Congress.
The parser accepts this Congress-keyed mapping through `member_surnames` and
performs no file or network I/O. Without a reference match, it leaves the
combined descriptor intact.

Within a descriptor, the longest matching source surname wins. Spaces, hyphens
and apostrophes inside names can be omitted by the filename convention; an
ensuing title must begin with a capital letter. This retains `McClintock`,
`LaHood`, `VanDrew` and `BluntRochester` without name-specific parser changes.
The generated patterns and Congress scopes appear in `member-title-rules.json`.
This is a reference-assisted boundary reading, not proof of a person's identity.
Two members sharing a surname are not resolved to a particular member.

The same supplied surname vocabulary handles suffixes such as `-RepMoylanih`.
It retains the original suffix and adds member/version fields; no number or
title is invented. Without a supplied surname match the suffix remains raw.
When a title excludes an ambiguous version candidate, its note says so and the
whole descriptive text remains available.

`RepRadewagen` supplies a name without an invented title. The literal `Rep`
marker is retained even for `RepHoeven`; it does not verify chamber or
sponsorship. Title text stays verbatim:
CamelCase alone cannot restore every missing space in strings such as
`Renewingthe` or `Tocodify` with certainty.

## Generate and audit the corpus

From the repository root, with the project's Python environment:

```bash
.venv/bin/python -m congress_api.filename_corpus \
  output/filename-clustering/filenames.parquet output/filename-regex \
  --legislators .cache/source-models/legislators-current.json
.venv/bin/python -m pytest tests/test_filename_patterns.py tests/test_filename_families.py tests/test_filename_residuals.py tests/test_filename_audit_fixes.py -q
```

The inventory reader includes both representative `filename` values and every
original `variants` spelling. Only the Parquet reader requires `pyarrow`;
`build_corpus(filenames, output_directory)` accepts literal names directly.
`--legislators` is optional and accepts multiple retained JSON files, including
historical records when available. A current-member file contains prior terms
for those members, but is not a complete historical roster. Missing reference
names remain unsplit. The audit records every supplied reference file's hash.

| Output | Contents |
| --- | --- |
| `structural-rules.json` | Curated regexes, named captures, application scope, flags, counts and actual extraction examples. |
| `member-title-rules.json` | Optional reference-derived surname/title patterns, scoped to Congress; an empty list without supplied legislator data. |
| `shared-tokens.jsonl.gz` | One regex per recurring token/kind, exact case variants, occurrence counts and examples. |
| `coverage.json` | Input/code hashes, complete audit counts and the limits of those measurements. |
| `collisions.json` | Competing full-layout or payload interpretations; field-level overlap is intentional. |
| `review.jsonl.gz` | Every name without a full layout, with an unparsed structured payload, or without recurring lexical tokens; includes the fields that were extracted. |
| `residual-fields.jsonl.gz` | Every nonempty `descriptor`/`suffix`, the specific fields already extracted inside it, and exact remaining text spans. Includes fully explained suffixes with empty residual spans. |
| `residual-patterns.jsonl.gz` | All remaining text shapes, ranked by distinct literal filename count, with original examples. |
| `residual-summary.json` | Residual counts by rule/field and recurring shapes, separate from layout coverage. |
| `other-text-fields.jsonl.gz` | Other opaque fields and stems without a complete outer layout, with exact remaining spans. Structured enclosing payloads and simple numeric amendment/document identifiers are excluded from this text backlog. |
| `other-text-patterns.jsonl.gz` | All remaining shapes in those other fields, ranked with examples and distinct-stem counts. |
| `other-text-summary.json` | Counts for other text by rule and field; retained names, identifiers and descriptions are not automatically errors. |
| `capture-review.json` | Counts and up to three raw examples per rule/field/status/code group, including vocabulary labels, candidate interpretations, unlisted codes, dates without valid readings and literal syntax. |
| `unmatched-rules.json` | Ordered date/time patterns followed by identifier/name fallback regexes. |
| `unmatched-resolutions.jsonl` | Every originally unmatched name and its assumed interpretation, or ZIP exclusion. |
| `unmatched-names.txt` | Names still unresolved after the user assumptions; regenerated on every run. |

To use a shared-token rule, compile its `pattern` without extra flags, search the
stem (`parsed.filename[:parsed.stem_end]`), and read the named group `token`.
For batch matching, `filename_tokens(parsed)` plus a lookup by
`(token.kind, token.raw.casefold())` avoids running thousands of regexes per file.
The audit compares that lookup's expected spans against the actual regexes.

Structural rules use `re.fullmatch` for `stem` and nested payload scopes, and
`re.finditer` for `search` scope. Payload offsets are relative to the original
filename. `parse_filename` implements this dispatch; use it instead of treating
all exported patterns as interchangeable searches.

Scoped `published-suffix-search` rules inspect only published-package suffixes;
`legislative-text-search` rules inspect legislative descriptors and suffixes.
They recover literal `add`, `err`, volume/part markers, `ANS` and `HAmdt` without
assigning official expansions. Existing numeric part captures are reused.
`REVISED` and mixed print separators such as `RCP115- 13` have general bounded
search rules. Overlap between field searches is not a competing full layout.

Additional legislative families apply only when the existing inner layouts do
not match. The exported `fallback` value specifies their order: `0` is the
existing parser, `1` is explicit committee/amendment/print/type notation, `2`
is local identifiers or type-plus-title drafts, and `3` is an introduced-draft
suffix after descriptive text. Stop after the first tier with matches. Multiple
matches within that tier remain visible and fail the collision audit.

These rules preserve empty appropriations slots, absent bill numbers, literal
placeholders, compound local IDs, malformed sponsor slots and print/division
markers. `KOOO395` is retained as `sponsor_identifier_token`, not converted into
a Bioguide identifier. `PIH`/`PIS` remain whole; only `PIH` has a verified House
definition. Optional identifier
letters cannot consume their first character and produce an invented IH/IS
interpretation. An opaque descriptor still indicates uninterpreted text even
when the outer naming family is recognized.

The joined-title/local-code rule requires a visible lowercase-to-uppercase
boundary, such as `hrFARMEXT-SUS`. It does not guess where a type ends inside
an entirely uppercase string. Combined resolution/measure-list rules retain
each measure through the existing reference extraction. Neither a filename's
`_xml` marker nor an unexplained numeric suffix changes its extension or
establishes the document format, bill version, or amendment number.

## Measure text remaining inside matched layouts

Layout coverage and shared-token coverage do not measure how much text has
been separated into useful fields. The residual audit runs on every filename,
including names whose layouts already match. It subtracts specific captures
from each nonempty `descriptor` and `suffix`. For example, `-U1` is already
explained by its revision marker/number, while `-FreeText-U1` leaves `FreeText`.
Enclosing payloads and other broad text captures cannot hide those residuals.

Residuals retain exact source spelling and offsets. Their review shapes fold
case and replace digit runs with `<number>` to reveal repeated conventions;
these shapes are not new extraction regexes or document classifications.
Every shape, including singletons, remains available in the compressed output.
Recurrence counts literal filenames, so PDF/XML variants may count separately.

A title that remains free text is useful retained information, not necessarily
a missing field. Other opaque fields and unstructured stems are now audited in
separate artifacts. All residual spans have exact substring checks and complete,
nonoverlapping accounting of alphanumeric characters. Ambiguous version candidates
cannot hide residual words. Candidate dates and identifiers count as extracted
syntax without establishing their roles; `capture-review.json` exposes those
interpretations for review. Distinct stems collapse case/format variants for
recurrence analysis without asserting document identity.

## Frozen parser comparisons

The bounded comparison and its retained failed candidates are documented in
`tests/filename-family-experiment.md`. Replay with
`tests/compare_filename_families.py`; it uses the same parser on frozen and current
source, counts new useful fields separately from new layout matches, and checks
that every old capture survives unchanged.

The subsequent nine-name correction and residual audit are retained separately
under `output/filename-regex/residual-audit-20260929/`. Replay that comparison with:

```bash
.venv/bin/python tests/compare_filename_families.py replay \
  --root output/filename-regex/residual-audit-20260929 --minimum-useful 9
```

The output subdirectory must not already exist. This comparison requires all
previous matches and fields to survive and rejects changes outside the declared
nine filenames. The older experiment keeps its original baseline and results.

The subsequent combined-review fixes use the frozen parser and vocabulary in
`output/filename-regex/findings-fix-20260929/`. Comparison loads both frozen files;
it does not silently substitute the current bill-code vocabulary for the baseline.
Both audit commands record source/input hashes before work, verify them afterward,
retain their artifacts and exit nonzero when their acceptance checks fail.

For deliberate interpretation corrections, `--expected-changes` accepts reviewed
exact before/after match hashes keyed by filename. A different result, a stale
entry, a collision, or an input/code change during execution fails the comparison.
An initial comparison without that file intentionally fails on undeclared changes
and saves them for inspection; it is not an accepted run. This permits correction
of a wrong label without weakening unrelated regression checks.

## Assumptions for the unmatched remainder

After shared-token and recurring-layout matching, the remaining non-ZIP names
use the user's explicit assumptions:

- Recognizable leading dates and timestamps take precedence. Compact five- or
  six-digit dates retain their ambiguous order and unspecified century.
- Leading digits become generic identifiers only if date/time recognition
  fails. Preserve leading zeros; treat remaining text as a name.
- Other stems are names. Keep a separated numeric suffix as a generic identifier
  (`Doraiswamy.04061.pdf` → name `Doraiswamy`, identifier `04061`).
- Remove a hanging `pdf` and the terminal `-testimony` or `-tedtimony` artifact
  from the assumed name. Keep legitimate name hyphens such as `Caroline-Vicini`.
- Exclude ZIP filenames.

`resolve_unmatched_filename(parsed)` supplies this interpretation separately from
the literal syntax matches. It checks calendar plausibility before accepting a
date/time pattern, then uses the first applicable rule in `unmatched-rules.json`.
Every assumed field carries an explicit note, and removed artifacts keep their
own exact spans as `ignored_suffix`. No identity lookup or forced short-year
expansion is performed. The original filename and source observations remain intact.

The builder applies these assumptions only to the unmatched remainder. They do
not change shared-token counts or upgrade an assumption to a source-verified
fact. Known layouts and the unparsed portions of BILLS records retain their
existing treatment.

## What “all shared tokens” means here

Recurrence requires at least two distinct literal filenames. Token definitions
are explicit: maximal Unicode letter runs, ASCII digit runs, and ASCII CamelCase
parts. Known extensions do not count. Words, names, numbers and type markers are
all retained; common surnames and repeated IDs are not classified as document
types. Case variants group together, but the regex matches the observed spellings
exactly. There is no stemming, synonym merging, or arbitrary substring matching.

Joined lowercase phrases need a structural rule to identify their parts; a
single run of letters does not reveal word boundaries by itself. Those rules
are reported separately from lexical recurrence. Two formats of one document
can establish recurrence; these counts do not establish distinct documents.

The audit checks every filename's reconstruction, every captured substring,
every expected recurring-token occurrence, and extra hits by those applied
rules. It also tests token boundaries and records competing structural matches.
It does not execute the full absent-rule-by-filename cross product or certify
document-content labels. New filename conventions need a fresh audit.

This separation allows exact syntax checks without presenting assumptions as
source-verified metadata. Unparsed payloads and assumed names stay visible in
the review output.
