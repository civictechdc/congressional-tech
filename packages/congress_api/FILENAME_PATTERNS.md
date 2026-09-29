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
Unlisted source tokens such as `pih`, `pis`, `or`, `SA` and `SUS` remain available
without an invented official label.

| Filename | Extracted parts |
| --- | --- |
| `BILLS-115hr1892eas2.pdf` | Congress `115`, bill type `hr`, number `1892`, version `eas`, numeric modifier `2`. |
| `BILLS-113-HR4660ih(asfiled).pdf` | Congress `113`, bill type `HR`, number `4660`, version `ih`, annotation `asfiled`. |
| `BILLS-1172126r4ih.pdf` | Congress `117`, number `2126`, prefix `r4`, version `ih`; no bill type supplied. |
| `BILLS-119HR2162HoneyIntegrityActih.pdf` | Number `2162`, descriptor `HoneyIntegrityAct`, version-shaped suffix `ih`. |

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
.venv/bin/python -m pytest tests/test_filename_patterns.py -q
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
