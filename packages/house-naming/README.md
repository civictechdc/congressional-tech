# House Naming Guide

Extract metadata from congressional document filenames while preserving exactly
what the source says. The package also validates structured naming records and
renders filenames for supported conventions.

It combines the House's **Document Naming Conventions, version 1.2.1
(April 24, 2012)** with layouts observed in document inventories, including
Government Publishing Office (GPO) hearing, report and committee-print identifiers.
One bundled catalog owns the rules, definitions and source examples. Runtime
operations work offline and do not read or download documents.

A filename can supply useful evidence without proving a document's contents,
identity or legislative status. The APIs keep those distinctions visible.

## Choose an API

| Task | API | Result |
| --- | --- | --- |
| Read metadata from an actual source filename | `Engine.extract(name)` | Literal observations, original text and offsets, plus any validated naming records. |
| Recognize a supported naming convention | `Engine.parse(name)` | Validated records, canonical filenames, ambiguity and rejected candidates. |
| Check a structured record | `Engine.validate(record)` | A fresh validated record, including established defaults and derived fields. |
| Generate a supported filename | `Engine.render(record)` | A filename, or the supplied URL for a link-only kind. |
| Get typed extraction results | `house_naming.filenames.parse_filename(name)` | Pydantic models over the same literal reader. |
| Audit a saved filename inventory | `house-naming-corpus` | Extraction, recurring-token and residual-text review artifacts. |

Use `extract()` for ingestion. A source filename may contain readable metadata
even when `parse()` cannot validate its overall layout. Both methods return the
same strict parsing results; literal observations do not change `valid`.

## Install and try it

From this package directory, with Python 3.10 or newer:

```bash
python -m pip install .
house-naming check
house-naming extract 'Opening Statement-Hassan-2020-06-03.pdf'
house-naming render examples/witness.json --plain
```

The last command prints `HHRG-112-ED-WState-IveyB-20110922.pdf`. Install this local
project rather than assuming a public registry package exists. Installation may
download dependencies; runtime operations remain offline. The sole direct
runtime dependency is `jsonschema>=4.18,<5`.

```python
from house_naming import Engine

engine = Engine()
source = engine.extract("Opening Statement-Hassan-2020-06-03.pdf")

# The wording is readable even though the filename is not a strict convention.
assert not source["valid"]
assert any(
    item["rule"] == "labeled-subject-date"
    for item in source["observations"]
)

for observation in source["observations"]:
    print(observation["rule"], {
        field["name"]: field["raw"]
        for field in observation["fields"]
    })

assert "".join(piece["raw"] for piece in source["pieces"]) == source["input"]
```

Optional interfaces:

```bash
python -m pip install '.[typed]'   # Pydantic result models
python -m pip install '.[corpus]'  # Typed models and Parquet inventory reader
```

The core engine does not require Pydantic, PyArrow or `congress_api`.
Applications should import filename parsing, corpus tooling, naming lookups and
bill-code definitions from `house_naming`. The former `congress_api.filenames`,
`filename_corpus`, `naming` and `bill_codes` modules have moved here.

## Read source filenames without losing evidence

The literal reader accepts basenames with spaces, repeated extensions, unknown
text and incomplete conventions. It separates extensions and query-shaped
suffixes, recognizes structured fields, then examines eligible text for further
references and wording. Assigned identifiers remain protected from unrelated
date, bill and document-label searches.

### Extraction results

In addition to the strict parsing results, `extract()` returns:

| Field | Meaning |
| --- | --- |
| `stem_end` | End offset before recognized extensions or query-shaped suffix text. |
| `observations` | Rule, scope, matched span and captured source fields. |
| `pieces` | Word, number and separator spans that reconstruct the exact input. |
| `suppressed` | Candidate matches and their fields, with reasons they were not selected. |
| `source_url` | Optional caller-supplied provenance, returned when supplied; never fetched or treated as document identity. |

Every observed field carries `name`, `raw`, zero-based `start` and `end`
offsets, `candidates`, `note`, and optional `code`, `label`, `context` and
`vocabulary_url`. Offsets use the half-open interval `[start, end)` in the
original filename. Snake-case observation names describe source text:
`measure_number` retains printed digits, whereas a validated record's
`measureNumber` is an integer.

A `context` and `code` resolve through `lookup()` to a catalog definition.
Labels can also explain a literal reading without assigning a vocabulary code.
For example, the explicit spelling alias `Tesitmony` retains its raw spelling
and receives the label `Testimony`. This is bounded alias recognition, not
general fuzzy correction or verification of the document's contents.

The typed adapter exposes these observations as `ParsedFilename.matches`.
Those matches are literal observations; they are distinct from the validated
record candidates in `Engine.parse()["matches"]`.

### What the reader extracts

| Filename information | Preservation rule |
| --- | --- |
| House routing and document slots | Keep Congress, committee codes, meeting/document markers, witness strings and identifiers in their source roles. |
| Bills and amendments | Keep measure references, versions, consideration markers, placeholders, amendment degrees, substitute targets and local identifiers separately. |
| Reports, hearings and prints | Keep package identifiers, citation numbers, parts, volumes and publication suffixes without conflating their numbering systems. |
| Descriptive wording | Recognize statements, testimony, biographies, questionnaires, remarks, notices, agendas, lists, summaries, drafts and other explicit phrases. Multiple labels can coexist. |
| Actions and relationships | Preserve support/opposition, offered-by, filed-by, reported/amended-by, result and access wording as source claims. |
| Dates and periods | Retain complete, short, partial, named-month, fiscal-year and date-range forms with supported readings and warnings. |
| Filename mechanics | Preserve opaque IDs, local numbers, stacked extensions, internal format wording, query-shaped text and readable fragments of damaged names. |

Representative distinctions:

- `h6323fs_rh_xml.pdf` supplies a short measure code, number, local modifier,
  version and internal `xml` wording. The extension remains `pdf`; no Congress
  is invented.
- A bill-to-bill comparison retains separate source and target spans. References
  within one side do not replace metadata on the other.
- `S. Hrg. 115-693` contains a printed hearing citation number. A `CHRG`
  package contains a GPO jacket identifier. They are different identifiers.
- `CRPT-112hrpt332.pdf` establishes report notation, not conference status.
  Loose `HRPT`/`SRPT` subjects remain literal when their role is uncertain.
- `HAmdt2` denotes an interchamber amendment degree in its defined slot.
  A generic `2nd Degree` phrase does not inherit that meaning or establish an
  amendment sequence number.
- `FLO23798` remains an intact drafting identifier. Its digits do not become
  an unrelated short date; suppressed alternatives remain inspectable.
- `202103xx` can supply year/month precision. A prefix such as `0205` can remain
  both a generic identifier and a possible month/day, with no chosen year.
- `Public Health Questionnaire` does not acquire a Public qualifier.
  Printed `Final`, `Modified` or `Signed` wording does not verify a document's
  publication, revision or signature.
- `TT`, `SxS`, local `MA` and other abbreviations retain their printed roles
  where recognized. Unestablished expansions remain absent.
- `Services` is not silently shortened to manufacture an `es` version.
  An ordinal-shaped boundary such as `HR2534116thCongress` remains ambiguous.

Dates never supply a missing event role, timezone or century. Complete date
shapes take precedence over misleading fragments. Invalid dates and malformed
year lengths keep their original text and warnings; the reader does not repair
them. An explicit convention can establish a date role, such as the Monday
week-start date in a weekly notice.

The final fallback considers plausible dates and timestamps before generic
numeric identifiers, then labels remaining text as an assumed name. These fields
explicitly identify the reading as a fallback assumption. Hanging `pdf` and
recognized trailing wording remain separate; ZIP stems never become assumed
person names. Bounded refinement can expose components at both ends of a
remainder while retaining the parent text.

No URL decoding, transliteration, Unicode normalization, arbitrary separator
repair or numeric-padding repair occurs. An extension or internal `XML` marker
does not verify content format. Multiple observations may describe the same span,
and complete character retention does not imply complete semantic interpretation.

See [Filename patterns and corpus tooling](FILENAME_PATTERNS.md) for worked
examples, vocabulary sources and detailed naming behavior.

### Optional source context

```python
source = engine.extract(
    "TT_Doar_3.15.18.pdf",
    source_url="https://edworkforce.house.gov/UploadedFiles/TT_Doar_3.15.18.pdf",
)
```

The source URL qualifies a few reviewed local conventions. On the Education
and Workforce publisher, `TT` receives the label `Truth in Testimony disclosure`.
On the Joint Economic Committee publisher, `SFR` receives `Written witness
statement`; its note identifies “Statement for the Record” as an inferred
expansion. Unknown publishers keep the literal codes without these labels.
Exact reviewed mirror URLs can qualify an occurrence without extending the
convention to every file on that mirror. The publisher does not identify the
issuing committee, person, meeting, or completeness of a document.

`parse_filename(..., source_url=...)` and `house-naming extract NAME --source-url
URL` accept the same context. Supply the source of that particular occurrence;
the reader does not discover provenance from a basename. The names-only corpus
command therefore leaves these publisher readings unqualified.

Legislative fields distinguish `ANS` substitute wording from `AANS` and `toANS`
target wording. The latter expose `target_amendment_marker`, retaining local
numbers and revisions separately. A trailing `ih` version does not erase a
substitute reading. `MGR` receives a manager-amendment label only in the reviewed
legislative layouts or source occurrences; `FC_MGR_02` and an `MGR` in a support
letter retain no such expansion. These labels do not add official vocabulary
codes or certify PDF contents.

A filename is not a document identifier. The reviewed `MGR_01.pdf` occurrences
have different bodies and bills. Keep the source URL, meeting context, capture
time and body hash in the capture layer; this reader never fills in a bill or
edition from the basename or URL. See the 78-case fixture in
`tests/fixtures/verified_local_conventions.json` for the bounded source review.

### Optional surname context

Supply a Congress-specific surname vocabulary when a filename joins a printed
`Rep` marker, surname and title:

```python
source = engine.extract(
    "BILLS-119HR9269RepClyburnRenewingtheAfricanAmericanCivilRightsNetworkActih.pdf",
    member_surnames={"119": ["Clyburn"]},
)
```

This can add `member-title` or `member-reference` observations while preserving
the original description and validated record. The longest supplied surname
wins; omitted surname spaces, apostrophes and hyphens are tolerated. Title and
reference boundaries must remain recognizable. Missing or wrong-Congress
vocabularies leave the text unsplit.

A surname match does not establish person identity, office or sponsorship.
Vocabulary acquisition and service-date selection belong to the caller. The CLI
accepts the same mapping with `--member-surnames FILE.json`, or `-` for stdin.

## Validate and render naming records

The engine exposes **56 kinds**: 54 filename conventions and two link-only kinds.
A record selects its convention through `kind`.

```python
record = {
    "kind": "witness-statement",
    "congress": 112,
    "committeeCode": "ED",
    "witnessId": "IveyB",
    "meetingDate": "20110922",
    "extension": "pdf",
    "revision": 1,
}

filename = engine.render(record)
assert filename == "HHRG-112-ED-WState-IveyB-20110922-U1.pdf"

validated = engine.validate(record)
parsed = engine.parse(filename)
assert validated in [match["record"] for match in parsed["matches"]]
```

Validation returns a fresh record and does not mutate the input. It fills
declared defaults and derives metadata established by retained fields, rejecting
contradictory supplied values. For example, omitted witness `meetingType`
defaults to `HHRG`, and an omitted hearing `publicationSuffix` defaults to an
empty string. `render()` validates first and returns text; it does not create,
rename, upload or fetch a file.

### Strict parsing results

| Field | Meaning |
| --- | --- |
| `input` | Original basename. |
| `valid` | At least one supported interpretation passed validation. |
| `ambiguous` | More than one validated interpretation remains. |
| `matches` | Candidates containing a validated `record`, `canonical_filename` and `matched_conventions`. |
| `found_in_source`, `source_example_ids`, `source_issues` | Evidence from retained guide examples, separate from validity. |
| `rejected_candidates` | Structural matches that failed validation, including kind, priority, error code, message and details. |
| `issues` | Parsing diagnostics, including rejected-candidate codes. |

Parsing keeps every validated candidate at the first `parse_priority` that
succeeds. A failed candidate does not block a later priority. Conventions that
explicitly share a record are combined; distinct interpretations remain separate.
An empty rejection list distinguishes no matching layout from a rejected layout.

Fixed tokens, codes, extensions and revision markers accept ASCII case variants.
Free text retains its spelling. The canonical filename uses the declared
rendering layout, and parsing it again retains the validated record:

```python
parsed = engine.parse("HMTG-113-AP06-Wstate-BrewerB-20130424.PDF")
match = parsed["matches"][0]
assert match["record"]["meetingType"] == "HMTG"
assert match["record"]["witnessId"] == "BrewerB"
assert match["canonical_filename"] == "HMTG-113-AP06-WState-BrewerB-20130424.pdf"
```

Important record semantics:

- Missing bill types, member IDs and other required metadata are not invented.
  Observed fallback kinds can retain untyped numbers, descriptions or routing
  strings without asserting the missing fields.
- Numbered reports parse as `published-report` with `documentType: "report"`.
  `conference-numbered` remains available for rendering a known conference
  report and can appear in `matched_conventions`; conference status needs
  separate evidence.
- Detailed appropriations conventions share `appropriation-described` records.
  The original description remains alongside explicit fiscal-year, routing,
  subject and sequence fields. Short years do not acquire a century.
- Publication suffixes retain unknown or repeated components. An empty part,
  volume, addendum or errata value means the marker was present without an
  identifier; an absent field means no unique marker was extracted. Hearing
  `err` remains ambiguous between addendum and errata.
- String identifiers preserve leading zeros. Bare numeric amendment subjects
  remain literal, and combined measure lists do not select a primary measure.
- `witnessIdType: "bioguide"` describes identifier syntax, not a verified person.
- Descriptive IH/PIH fallbacks preserve ambiguous stage and number boundaries.
  A recognized outer layout can still contain uninterpreted description text.

### References inside records

Validated records can contain a typed `references` array for explicit measure,
Rules Committee Print and fiscal-year references. Each reference retains
`raw`, `sourceField` and `[start, end)` offsets **within that field**, rather
than within the whole filename.

```python
record = engine.parse("BILLS-116HR3401EAS-RCP116-21.pdf")["matches"][0]["record"]
assert record["references"] == [{
    "type": "rules-committee-print",
    "congress": 116,
    "number": "21",
    "raw": "RCP116-21",
    "sourceField": "versionSuffix",
    "start": 1,
    "end": 10,
}]
```

References never replace primary metadata or fill missing routing slots.
Repeated references retain separate locations. Person IDs, dates and publication
numbers are protected from unrelated reference searches. Validation derives
references when omitted and rejects supplied references that disagree with the
retained text.

## Audit a filename corpus

The corpus command reads `filename` and `variants` columns from a saved Parquet
inventory. It does not fetch documents or change publisher metadata.

```bash
house-naming-corpus filenames.parquet output-directory/
house-naming-corpus filenames.parquet output-directory/ \
  --member-surnames member-surnames.json
```

For in-memory input, use
`house_naming.filename_corpus.build_corpus(filenames, output_directory)`.
The output directory argument is a `pathlib.Path`.

The smaller helpers in `house_naming.corpus` operate on an extraction result:

```python
from house_naming.corpus import (
    filename_tokens,
    shared_token_pattern,
    residual_fields,
    filename_review_category,
)

tokens = filename_tokens(source)
pattern = shared_token_pattern(("Statement", "statement"), "word")
remaining = residual_fields(source, include_unstructured=True)
category = filename_review_category(source)
```

- `filename_tokens()` returns literal words, numbers and ASCII CamelCase parts,
  excluding extensions and separated query text. `RepClyburn` yields `Rep`
  and `Clyburn`; `Renewingthe` remains one part.
- `shared_token_pattern()` builds a regex for the caller's observed spellings
  using those token boundaries. Recurrence does not establish a document type.
- `residual_fields()` subtracts specific captures from descriptions and suffixes.
  Results retain the original field, covering fields and unexplained spans.
  Use `field_names` for other slots and `include_unstructured=True` for stems
  without a recognized outer layout.
- `filename_review_category()` separates extracted syntax, generic identifiers,
  unclassified names or titles, opaque identifiers/text, web endpoints, metadata
  files, media/streams and containers.

Residual text can be a legitimate name or title. An empty residual does not prove
semantic completeness, and a filename alone cannot reliably distinguish a bare
name from a title. Corpus summaries expose `filename_review_categories`; gap
rows expose `review_category`. These are review categories based on syntax,
not verified content types.

See [the corpus reference](FILENAME_PATTERNS.md) for output artifacts and audit
interpretation. Full-corpus evidence and source hashes are separate from unit-test
results.

## Catalog, definitions and schemas

All four JSON artifacts live in `src/house_naming/data/`:

| File | Purpose |
| --- | --- |
| `guide.json` | Patterns, field definitions, extraction rules, code meanings, source examples, provenance and committee lookup. |
| `guide.schema.json` | Closed catalog structure; runtime checks also enforce cross-references and dispatch requirements. |
| `record.schema.json` | Structured input records selected by `kind`. |
| `filename-lexical.schema.json` | Candidate filename shapes; weaker than full runtime validation. |

The schemas use JSON Schema Draft 2020-12 and internal references only.
Other languages can consume them directly. The literal extraction rules use
Python `re` with ASCII case-insensitive structural matching; they are separate
from the portable rendering schemas.

```python
stage = engine.lookup("version", "RH")
contexts = engine.contexts("SC")
committee = engine.committee("AG00")
examples = engine.examples("HRPT-112-HR123-p2.pdf")
source_text = engine.source("table-8491-row-3")
kinds = engine.kinds()
```

Codes are keyed by context and case-folded token. Committee lookup uses exact
folder codes: `AG` is not rewritten to `AG00`. Unknown entries return `None`;
unknown code contexts raise `NamingError`. The retained committee directory is
historical reference data, not a current allowlist. The member appendix on source
pages 30–40 is intentionally omitted.

Guide definitions, source spellings, duplicate examples and documented
inconsistencies remain available through local source anchors. `observed_examples`
documents additional corpus layouts separately from original
`source_example_ids`. Observed layouts do not acquire invented guide citations.

Pattern entries include templates, field definitions, source references and
implementation decisions. `parse_templates` lists supported alternate layouts;
`derived_fields` describes metadata inside retained fields; `parse_as` identifies
a shared parsed record. `decisions` and `requires_interpretation` document
interpretations—the latter is descriptive, not an enable/disable switch.

`load_guide()` and `engine.guide` return independent mutable catalog copies.
`engine.extraction_rules()` also returns copies. Editing a returned value does
not modify the engine. Bill definitions live in `house_naming.bill_codes`;
the guide URL and shared lookup interface live in `house_naming.naming`.

## Command-line interface

```bash
house-naming kinds
house-naming validate examples/witness.json
house-naming render examples/witness.json --plain
house-naming parse HHRG-112-ED-WState-IveyB-20110922.pdf
house-naming extract 'Opening Statement-Hassan-2020-06-03.pdf'
house-naming lookup version RH
house-naming contexts SC
house-naming committee AG00
house-naming source table-8491-row-3
house-naming schema
house-naming schema --filename-lexical
```

`validate` and `render` accept `-` for JSON from stdin. Results are JSON on
stdout; errors are JSON on stderr. `render --plain` prints only the filename or
URL. Help and version output are text.

| Exit status | Meaning |
| --- | --- |
| `0` | Success, including an ambiguous valid parse or an empty lookup. |
| `1` | Invalid input or no valid parse match. |
| `2` | Usage, resource-limit, I/O or configuration error. |

`extract` succeeds when it processes the source, even if its strict `valid`
field is false. Python callers receive `NamingError` for raised errors, with
`code`, `details` and `as_dict()`.

## Maintain and verify

Edit `guide.json` for naming data and rules. Change `guide.schema.json` only
when changing the catalog structure. Both are trusted configuration.

```bash
python -m pip install '.[test]'
python tools/build.py
python tools/build.py --check
python -m pytest -q
node tools/check_ecmascript.mjs  # Optional; no npm dependencies.
```

The build deterministically regenerates lookup indices, code-linked field enums
and the two derived schemas. There is no source-document extraction step.

Catalog checks validate references, indices, templates and the rule IDs,
captures, scopes and priorities used by procedural handlers. Ordinary extraction
rules need no Python registration; specially dispatched rules require a matching
handler.

Tests cover every kind, source fidelity, malformed input, ambiguity, date and
identifier boundaries, references, revisions, deterministic builds, CLI behavior
and offline operation. `tests/records.json` contains constructed regression
fixtures; observed-name tests retain actual corpus cases and negative controls.
The repository's `check_house_naming_upgrade.py` and
`check_house_naming_references.py` compare saved corpus runs. Passing unit tests,
round-trips or coverage counts does not establish document-content accuracy.
The optional Node check verifies regex portability, not integration with a
JavaScript JSON Schema validator.

For compatibility, consumers should use the returned record's `kind`.
`conference-numbered`, detailed appropriations conventions and
`committee-rules` can parse into shared record kinds while retaining original
convention names in `matched_conventions`. Existing records still validate and
render. Derived values are optional on input and appear on validated output
when supported by retained text.

## Limits and integration responsibilities

| Boundary | Limit |
| --- | --- |
| Literal source basename | 16 KiB of UTF-8; paths and URLs are not accepted as basenames. |
| Remainder refinement | 128 steps and 262,144 retained field characters. |
| CLI JSON input | 64 KiB, including surname mappings. |
| Record | 32 fields; an optional reference array contains at most 64 flat objects. |
| Free text | 160 characters per ordinary token; 240 for observed draft/routing text. |
| Sequence identifier | 32 characters. |
| Positive counter | At most 2,147,483,647. |
| Rendered filename | At most 255 UTF-8 bytes. |

Exceeding refinement limits raises `NamingError("extraction-limit", ...)`
rather than silently truncating observations. Schema validation checks shape
and lexical constraints; runtime validation also checks real Gregorian dates,
Monday week starts, URL structure, byte lengths and unsafe filename characters.

Revisions render as `-U<number>` before the extension. Free tokens cannot end
in the reserved `-U<digits>` or `-u<digits>` suffix. Optional
`meetingOccurrence` starts at 2. House conventions use `pdf` and `xml`;
published GPO hearings, reports and prints also allow `htm` and `html`.
Rendering requires canonical codes and preserves caller-supplied free text.
Integral JSON numbers such as `112.0` render as `112`.

Keep installed catalog and schema files trusted and read-only to untrusted
callers; consistency checks do not sandbox malicious regexes. No external
schemas or URLs are fetched. URL validation checks ASCII HTTP(S) structure,
percent escapes, host and port, and rejects credentials. It does not verify
publisher identity or complete RFC compliance.

A downstream fetcher must enforce its own server-side request forgery (SSRF) and
redirect policy. Storage code must handle collisions, symlinks, permissions,
escaping and filesystem normalization. Escape source text before HTML display.
Rendered names do not prove existence, uniqueness, authority, legislative status
or compliance with current House posting requirements.

See [NOTICE](NOTICE) and [LICENSE](LICENSE) for attribution and licensing.
