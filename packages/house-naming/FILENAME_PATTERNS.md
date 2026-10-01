# Filename extraction and corpus audits

This guide explains what `house_naming` reads from filenames, how to audit a
saved inventory, and how to interpret the resulting coverage and gaps. For
installation, API selection, record validation and runtime limits, see the
[README](README.md).

All literal extraction rules live in the package's `guide.json`.
`Engine.extract()`, its typed adapter `parse_filename()`, and the corpus
builder use the same reader. They do not download documents, inspect file
contents or change publisher metadata.

## Read a filename

```python
from house_naming.filenames import parse_filename

parsed = parse_filename("HHRG-113-AG00-Wstate-ColbyJ-20130314.pdf")
for match in parsed.matches:
    print(match.rule, {
        field.name: field.raw
        for field in match.fields
    })

assert "".join(piece.raw for piece in parsed.pieces) == parsed.filename
```

This filename supplies Congress `113`, routing code `AG00`, document marker
`Wstate`, subject `ColbyJ`, date text `20130314` and extension `pdf`.
Each field retains its original spelling and `[start, end)` character offsets
in the filename. Calendar validation can add candidate readings; only an explicit
convention establishes a date role.

The reader preserves structured fields, descriptive text, unknown tokens,
empty slots, suppressed alternatives and every original character. A `Bio`
label remains `Bio` even if the linked file contains testimony. A routing code
does not resolve a committee, and a witness string does not resolve a person.

`Engine.parse()` separately returns validated convention records.
`Engine.extract()` includes those same strict results plus literal observations.
The typed adapter exposes the observations as `parsed.matches`. Successful
extraction does not make a malformed or unsupported convention valid.

A filename such as `01 19 2021 Nominations -- Blinken Part 1.pdf` separates
`Nominations` as its label, `Blinken` as its `subject_token`, and `1` as its
`part_number`. The same layout supports comma-separated subjects, URL slugs
with `__`, and trailing publisher UUIDs. It does not turn the subject into a
verified witness, nominee identity, or person record.

`label` preserves the wording found in the filename. `document_kind` collects
normalized kinds from that wording and recognized filename layouts. The
`document-categories` vocabulary in `guide.json` owns the spelling mappings;
`categories.py` selects document wording rather than contextual mentions. The
same selection drives subject trimming and public kinds. Source-page link text
is separate metadata (`source_document_label`) and is not copied into filename
facts.

For example, `Written Testimony` maps to `testimony`, `STMNT` to `statement`,
and `rules_memorandum` to `rules-memorandum`. `Business Meeting` and `Nominations`
provide broad fallback kinds when no more specific genre is present. A business
meeting transcript stays `transcript`, and GSA resolutions for a business meeting
stay `committee-resolution`. Raw labels survive these choices. An explicit list
such as `Testimony, Summary, and Bio` can retain multiple kinds.

The reader also distinguishes amendment collections from amendment lists, mark
descriptions from the marks they describe, and questions from responses for the
record. A report mentioned in testimony, a policy response, a bill-title word,
or a structured witness identifier does not supply a new primary kind. These
are filename readings, not verification of the linked file's contents. Numeric
capture names, ambiguous local codes and the generic word `Documents` remain
unclassified without additional evidence.

## Bill types, versions and modifiers

The retained `bill_codes.py` vocabulary contains the eight bill types and
53 common version codes from
[GovInfo's Congressional Bills help](https://www.govinfo.gov/help/bills),
checked September 29, 2026. Recognized fields retain `raw` and offsets alongside
a normalized `code`, readable `label` and `vocabulary_url`.

The House's [Document Naming Conventions, page 6](https://www.govinfo.gov/content/pkg/GOVPUB-Y1_2-PURL-gpo156119/pdf/GOVPUB-Y1_2-PURL-gpo156119.pdf#page=6)
separately defines `PIH` as a pre-introduced measure. It receives the House
definition without entering the GovInfo version vocabulary. A numbered PIH
filename retains both claims; its number is not erased. `PIS` remains literal
without receiving the same meaning by analogy.

| Filename | Reading |
| --- | --- |
| `BILLS-115hr1892eas2.pdf` | Congress `115`, measure type `hr`, number `1892`, version `eas`, numeric modifier `2`. The modifier has no inferred chronology. |
| `BILLS-113-HR4660ih(asfiled).pdf` | Measure `HR4660`, version `ih`, annotation `asfiled`. |
| `BILLS-1172126r4ih.pdf` | Congress `117`, number `2126`, prefix `r4`, version `ih`; measure type remains absent. |
| `BILLS-119HR2162HoneyIntegrityActih.pdf` | Number `2162`, descriptor `HoneyIntegrityAct`, version-shaped suffix `ih`. |
| `BILLS-118 hres_44HR277HR288HR1615HR1640_xml.pdf` | Resolution `hres44`, all four following measure references, internal `xml` wording and actual extension `pdf`. |
| `BILLS-118 hres_HR2670_2_xml.pdf` | Unnumbered resolution type, reference `HR2670`, unexplained numeric suffix `2` and internal `xml` wording. |
| `BILLS-115HR__-RCP115-77.pdf` | Measure type `HR`, placeholder `__`, print Congress `115` and print number `77`; no bill number invented. |
| `BILLS-113hrFARMEXT-SUS.pdf` | Type `hr`, title `FARMEXT`, House consideration marker `SUS` (suspension of the rules), separate from a text version. |
| `h6323fs_rh_xml.pdf` | Short measure code, number, local modifier `fs`, version `rh` and internal `xml` wording. No Congress or undocumented code expansion is supplied. |

Bill type and text version are independent: a House bill can have a Senate
edition. Multiple references such as `HR6147HR6258` remain a measure list.
An internal format marker never changes the extension or verifies file contents.

### Local conventions and amendment roles

`Engine.extract(name, source_url=...)` and the typed `parse_filename()` adapter
can qualify local filename readings with the caller's source URL. Exact hosts
and reviewed mirror URLs live with the patterns in `guide.json`; extraction
does not fetch them. Without qualifying context, `TT` and `SFR` remain literal.
Qualified TT denotes a Truth in Testimony disclosure. Qualified SFR denotes a
written witness statement, with its full acronym expansion explicitly inferred.

`ANS` substitute form and `AANS`/`toANS` amendment targets retain different
field roles. Bare numeric targets do not acquire a measure type. Legislative
`MGR` layouts can supply a manager-amendment label, while `FC_MGR_02` remains
unexpanded. A publisher or shared basename never establishes document identity.
The source review is recorded in `tests/fixtures/verified_local_conventions.json`;
its eleven ANS examples are a structural sample, not a full-corpus accuracy claim.

### Version boundaries

A vocabulary hit does not establish a word boundary. In `ANSServices` or
`HR1Services`, the whole `Services` descriptor survives and `es` is only a
candidate, without an official version label. A separated version can resolve
the boundary: `ANSServices-ES` retains `Services-` and the printed `ES`.

The reader recognizes explicit slots, separators, numeric boundaries, visible
acronym/code case boundaries and reviewed joined IH/PIH/PIS forms. The explicit
`Interiorih` rule separates `Interior` and `ih`; it does not redefine bare
`rih`. Ambiguous `OAWPih` retains the whole descriptor and both candidate
endings. Optional identifier letters cannot consume the start of PIH/PIS and
manufacture an IH/IS reading.

Consecutive digits remain intact unless the syntax establishes their roles.
Unknown boundaries remain visible rather than becoming a guessed bill identity,
publication date or current legislative status.

Compact dates also need a supported year position. Trailing four-digit years
and unpadded seven-digit forms use the observed `19xx`/`20xx` conventions;
`transcript-07282103` does not establish July 28, 2103. Explicit separated
dates such as `2103-07-28` remain calendar candidates. Two-digit years never
acquire a century. Lowercase drafting IDs reserve their digits just as uppercase
IDs do, and explicit clock wording takes precedence over a date-shaped number.

`metadata` describes one filename and its supplied context. Applications may
deduplicate identical document bytes, but should retain each filename's values
with its source URL. A shared transcript can cover multiple hearing dates, and
a joint statement can legitimately appear under several people's filenames.

## House conventions and source definitions

The package retains the Clerk's naming guide, version 1.2.1 (April 24, 2012).
Its definitions, examples and source anchors are available locally through
`house_naming.naming.HOUSE_NAMING`:

```python
from house_naming.naming import HOUSE_NAMING

definition = HOUSE_NAMING.lookup("version", "RH")
name = "HRPT-112-HR123-p2.pdf"
record = HOUSE_NAMING.parse(name)["matches"][0]["record"]

assert record["partNumber"] == 2
assert HOUSE_NAMING.render(record) == name
source_examples = HOUSE_NAMING.examples(name)
```

`lookup(context, code)` returns attributed definitions and source references;
`source(id)` resolves their local text. Context matters: `SC` denotes
subcommittee consideration in appropriations routing and sponsor change in a
bill-version slot. Section anchors identify sections; their child nodes contain
the source paragraphs.

| Fragment and context | Meaning retained |
| --- | --- |
| `HRPT-112-HR123-p2` | Congress `112`, covered measure `HR123`, report part `2`; no report number supplied. |
| `BILLS-112s365-HAmdt2` | Second-degree House amendment to the referenced Senate measure; `2` is a degree, not a sequence number. |
| `Amdt-001-Enbloc-002` | Individual amendment identifier `001` and en bloc group `002`. `Amdt-Enbloc-001` supplies only a group. |
| `HR-SC-AP-FY13-suppl-02` | Subcommittee consideration, printed fiscal year `13`, supplemental sequence `02`; no century inferred. |
| `HRes-ORH-Rule-HR10` | Originally reported Rules resolution covering `HR10`; the covered number is not the resolution number. |
| `CRPT-112hrpt-HR2055-DivisonA-som` | Report division and joint statement of managers, preserving the printed `Divison` spelling. |
| `HMTG-112-HMKP-BU-20110215-2-SD001` | Markup, second meeting on that date, general meeting supporting document `001`. |
| `WState-IveyB-20110922-SD001` | Witness statement and witness supporting document `001`, distinct from a meeting attachment. |
| `CPRT-112hrpt-activities-Q4-RU` | Committee activity report for quarter `4`, routed to `RU`. |
| Terminal `-U1` | First update since the document's original posting. |

Literal extraction preserves source spelling and malformed values. It does not
turn `KOOO395` into a Bioguide identifier, fill an empty appropriations slot or
use the retained historical directory to resolve a current committee.

## Descriptive filenames and audit gaps

The literal reader also recognizes explicit wording and local filename
structures. These observations do not broaden strict `parse()` acceptance.

| Example | Information retained |
| --- | --- |
| `BILL-TO-BILL_h2868_rh_xml_to_RCP_H2868etc_xml.pdf` | Separate `comparison_source` and `comparison_target` spans, each side's references, and unexpanded `etc` modifier. |
| `RCP_277_xml.pdf` | RCP marker, local identifier `277` and internal `xml` wording; no official print number or Congress inferred. |
| `PortmanOpeningStatement.pdf.pdf` | `OpeningStatement` label and both extensions. CamelCase does not authorize arbitrary substrings such as Statement in `reStatementSuffix`. |
| `Smith-Tesitmony.pdf` | Raw spelling `Tesitmony`, explicit alias reading `Testimony` and original offsets; no general fuzzy matching. |
| `Welch2ModifiedSigned.pdf` | Printed `Modified` and `Signed` qualifiers; neither a verified signature nor a numbered revision. |
| `Treaty Doc. 115-31.pdf` | Citation Congress `115`, intact document number `31` and normalized citation code `tdoc`; no primary document type inferred. |
| `CDOC-111tdoc8.pdf` | Package Congress `111`, treaty-document type `tdoc` and document number `8`. |
| `CRPT-117-hrpt261.pdf` | Report Congress `117`, House report type and number `261`, with separators preserved. |
| `CRPT-117hrptPIH-american-rescue-plan_portion_1.pdf` | Report context, printed `PIH`, title and portion `1`; no report number or bill stage invented. |
| `Clements Responses to Supplemental QFRs.pdf` | Response label and subject `Clements`; `Supplemental` qualifies the questions rather than naming a questioner. |
| `Blumenthal Amendment to S. 1494 - MDM19899.pdf` | Literal name, amendment wording, target measure and drafting identifier; no resolved sponsor identity. |
| `S. 1303 Cruz-Cantwell_Substitute.pdf` | Measure reference, name slot and Substitute wording; no official version assigned. |
| `Exhibit03202024.pdf` | Explicit exhibit identifier `03202024`, protected from date scans. Bare `Exhibits` does not acquire an item number. |
| `addendum_b_undesser_07192023pdf` | Addendum identifier `b`, subject `undesser` and date candidates; no official report part inferred. |
| `eapheaa-letter` | Complete letter label and literal subject; no author or recipient inferred. |
| `09-09-21_meuser_2v1_tally_sheet.pdf` | Tally-sheet wording and subject/local text `meuser_2v1`; a source amendment association does not retype this file. |
| `GAO-24-107597.pdf`, `JCX1022.pdf`, `FLO23798.pdf` | Intact identifiers without invented date or number/year splits. Suppressed date readings remain inspectable. |
| `202103xx.pdf` | Year/month candidate `2021-03`, with unknown day preserved. |
| `0205-Smith.pdf` | Generic identifier and possible month/day prefix, with no chosen year or date order. |
| `TT_Smith.pdf` | Literal local code and subject; expansion requires publisher context. |
| `rev_Q1a Data China_Redacted1.pdf` | Literal Q component `1a` and redaction wording. Q stays unexpanded because other files use Q4 for a quarter. |

Longer phrases distinguish an amendment list from an individual amendment, or a
description of a mark from the mark itself. Generic Responses does not
automatically mean questions for the record. Opaque prefixes do not prevent
reading wording in the descriptive remainder. Examples and ambiguity controls
are exercised in [test_sparse_corpus.py](tests/test_sparse_corpus.py).

Compact transcript names retain their numeric date candidates when nomination
wording or a trailing counter follows `transcript`. Five- to eight-digit prefixes
can remain ambiguous; neither that wording nor source meeting metadata establishes
a date. Recognized outline and addendum components stay in their own fields and
are removed from the remaining subject text. These boundaries are exercised in
the `test_experiment_*` regression modules.

### Surnames and title boundaries

Callers can supply surname spellings scoped to Congress:

```python
parsed = parse_filename(
    "BILLS-119HR9269RepClyburnRenewingtheAfricanAmericanCivilRightsNetworkActih.pdf",
    member_surnames={"119": ["Clyburn"]},
)

fields = {
    field.name: field.raw
    for match in parsed.matches
    for field in match.fields
}
assert fields["member_surname_token"] == "Clyburn"
assert fields["title_token"] == "RenewingtheAfricanAmericanCivilRightsNetworkAct"
```

The full descriptor remains available. The longest supplied surname wins;
omitted spaces, hyphens and apostrophes inside that surname are tolerated.
A following title must have a recognizable capital boundary. This supports
spellings such as `VanDrew` and `BluntRochester` without name-specific rules.

The same vocabulary can expose internal or terminal `Rep` references and
suffixes such as `-RepMoylanih`. Missing or wrong-Congress names stay unsplit.
No first name, title, chamber, identity or sponsorship is inferred. Shared
surnames remain unresolved, and CamelCase does not reconstruct missing spaces
inside words such as `Renewingthe`.

Vocabulary acquisition and service-date selection belong to the source-data
application. The parser performs no file or network lookup.

## Generate a corpus audit

From the repository root, using a saved inventory and the project's environment:

```bash
.venv/bin/python -m pip install './packages/house-naming[corpus]'
.venv/bin/python -m house_naming.filename_corpus \
  filenames.parquet output/filename-regex \
  --member-surnames member-surnames.json
```

The inventory includes representative `filename` values and every original
`variants` spelling. Only the Parquet reader requires PyArrow.
`build_corpus(filenames, output_directory)` accepts literal names directly,
with a `pathlib.Path` for the output directory.

The optional surname file is a Congress-keyed JSON object such as
`{"119": ["Clyburn"]}`. The command uses the shared strict 64 KiB JSON reader;
duplicate keys are errors. Audit evidence records the reference file's hash.

### Output files

| Output | Contents |
| --- | --- |
| `coverage.json` | Input/code hashes, audit counts, review categories, acceptance status and measurement limits. |
| `structural-rules.json` | Catalog regexes, scopes, flags, counts and actual extraction examples. |
| `member-title-rules.json` | Congress-scoped surname/title patterns; empty without supplied reference data. |
| `shared-tokens.jsonl.gz` | Regexes for recurring token/kind pairs, exact case variants, counts and examples. |
| `collisions.json` | Competing full-layout or payload interpretations; ordinary field overlap is separate. |
| `review.jsonl.gz` | Names lacking a full layout, retaining an unparsed structured payload or lacking recurring lexical tokens, with extracted fields and review categories. |
| `residual-fields.jsonl.gz` | Each nonempty descriptor/suffix, its covering captures and exact remaining spans; fully explained fields have empty residuals. |
| `residual-patterns.jsonl.gz` | All residual shapes, ranked by distinct literal filenames, with examples. |
| `residual-summary.json` | Counts by rule/field and recurring shapes, separate from layout coverage. |
| `other-text-fields.jsonl.gz` | Other opaque fields and unstructured stems with remaining spans; excludes structured enclosing payloads and simple numeric amendment/document IDs. |
| `other-text-patterns.jsonl.gz` | Remaining shapes in those fields, with examples and distinct-stem counts. |
| `other-text-summary.json` | Other-text counts by rule and field. |
| `capture-review.json` | Counts and up to three examples per rule/field/status/code group, including vocabulary labels, uncertain readings and literal syntax. |
| `unmatched-rules.json` | Ordered date/time rules followed by identifier/name fallback rules. |
| `unmatched-resolutions.jsonl` | Originally unmatched names and their fallback readings or ZIP exclusions. |
| `unmatched-names.txt` | Names still unresolved after fallback assumptions; regenerated each run. |

Summary `filename_review_categories` and row-level `review_category` separate
extracted syntax, generic identifiers, unclassified names or titles, opaque
identifiers/text, web endpoints, metadata files, media/streams and ZIP containers.
They describe filename syntax, not verified content types. An unclassified name
alone does not demonstrate a missing document-type rule.

## Interpret the audit

Three measurements answer different questions:

| Measurement | Question answered | Limit |
| --- | --- | --- |
| Layout coverage | Did a structural naming family match? | A broad matched field can still contain unexplained text. |
| Shared-token coverage | Does the name contain wording or numbers seen in other literal filenames? | Recurrence does not establish document type or meaning. |
| Residual coverage | Which source spans remain after specific captures are removed? | Free-text titles and names can be appropriate residuals. |

### Recurring tokens

Recurrence requires at least two distinct literal filenames. Tokens are maximal
Unicode letter runs, ASCII digit runs and ASCII CamelCase parts. Known extensions
do not count. Case variants group together, while generated regexes match only
the observed spellings. There is no stemming, synonym merging or arbitrary
substring matching.

Joined lowercase words require explicit structural rules; a letter run alone
does not establish word boundaries. Repeated surnames and IDs are not document
types. PDF/XML spellings of one document can establish recurrence, so these
counts do not measure distinct documents.

Compile a shared-token `pattern` without extra flags, search
`parsed.filename[:parsed.stem_end]`, and read its named `token` group.
For batches, `house_naming.filenames.filename_tokens(parsed)` and a lookup by
`(token.kind, token.raw.casefold())` avoid running every regex against every file.
The audit checks the lookup's expected spans against regex results.

### Residual text

The residual audit examines matched layouts too. It subtracts specific captures
from every nonempty descriptor and suffix: `-U1` is explained by its revision
fields, while `-FreeText-U1` leaves `FreeText`. Broad enclosing fields and
fallback assumptions cannot hide that remaining text.

Residuals preserve exact spelling and offsets. Review shapes fold case and
replace digit runs with `<number>` to expose repeated structures; they are not
new extraction rules or classifications. Every shape, including singletons,
remains in the compressed outputs.

Alphanumeric characters receive complete, nonoverlapping accounting between
covered and residual spans. Ambiguous version endings cannot hide unexplained
words. Candidate dates and identifiers count as extracted syntax, with their
uncertainty available in `capture-review.json`. Distinct-stem counts collapse
case/format variants for review without asserting document identity.

### Fallback assumptions

For names left after recurring-token and recurring-layout matching, the corpus
uses these explicitly labeled assumptions:

1. Plausible leading dates and timestamps take precedence. Short years retain
   their unspecified century and ambiguous order.
2. Otherwise, leading digits become generic identifiers, preserving zeros.
3. Remaining text is treated as an assumed name. A separated numeric suffix,
   such as `04061` in `Doraiswamy.04061.pdf`, remains a generic identifier.
4. Hanging `pdf` and terminal `-testimony`/`-tedtimony` artifacts are separated
   from the assumed name as `ignored_suffix`; legitimate name hyphens remain.
5. ZIP stems are excluded from assumed person names.

`resolve_unmatched_filename(parsed)` selects an already extracted fallback;
it does not run another parser. The builder reports that reading separately
without changing shared-token counts or treating the assumption as verified
metadata. Original text and observations remain intact.

## Rule dispatch and acceptance checks

Use `Engine.extract()` or `parse_filename()` to apply structural rules.
Exported patterns have different scopes and are not interchangeable searches:
stem and payload rules use full matches; search rules inspect eligible regions.
Published-suffix rules operate inside publication suffixes, while legislative
text rules inspect their assigned descriptors or suffixes. Returned field offsets
always refer to the original filename.

For legislative payloads, catalog priorities select the first matching tier:
primary layouts, explicit notation, local/type-plus-title forms, then introduced
draft suffixes. Multiple matches within the selected tier remain visible as
collisions. This literal dispatch is separate from strict `parse_priority`,
which selects the first tier producing validated records.

Specific publication components, references and identifiers reserve their spans
before generic date searches. Field-level overlap can be intentional; competing
full layouts require review. Unparsed payloads remain visible even when an outer
family matches.

### Add a catalog rule

Add ordinary filename rules to `extraction_rules` in
[`guide.json`](src/house_naming/data/guide.json). For example:

```json
{
  "id": "witness-declaration",
  "pattern": "(?P<label>Witness[ _-]+Declaration)",
  "scope": "document-wording-search",
  "priority": 0,
  "description": "Explicit witness declaration wording.",
  "field_readings": {
    "label": {
      "label": "Witness declaration",
      "note": "Literal filename wording; contents are unverified."
    }
  }
}
```

This rule runs in the supplemental wording pass without a Python allowlist.
Test `Witness Declaration.pdf`, separator and case variants, the exact captured
span, and a negative example such as `WitnessDeclares.pdf`. Run `tools/build.py
--check` and the package tests before accepting the change. New corpus-derived
rules also need a comparison against the retained corpus.

Use these settings when a pattern needs more context:

| Setting | What it controls |
| --- | --- |
| `field_readings` | Literal labels, notes and provenance keyed by capture. A note alone is valid. Computed calendar or boundary warnings can refine these readings. |
| `field_vocabularies` | Ordered lookups by raw token. `house:measure`, for example, reuses the source guide; observed and GovInfo tables live in `extraction_vocabularies`. `fallback: true` applies a lookup only when no code has been assigned. |
| `searchable_fields` | Fields whose text permits further scanning. Other fields remain protected. This includes descriptive fields generated by a declared algorithm, such as the two sides of support/opposition wording. |
| `scan_order` and `reserve` | Search ordering and whether the whole match or a named capture reserves its span. These are separate from full-match `priority`. |
| `scan_stage` | Explicit supplemental or contextual use. A rule can also be selected by a parent for nested extraction. |
| `refine` | Child rules or scopes eligible inside a capture, with `search`, `match` or `fullmatch` behavior. Child offsets are translated back to the original filename. |
| `processors` | Existing Python operations for calculations or contextual checks, such as `numeric-date` or `congress-ordinal`. Their required inputs are checked when the catalog loads. |

For example, this entry in a parent rule searches its `suffix` with the existing
witness-suffix rules:

```json
{
  "field": "suffix",
  "stage": "scopes",
  "mode": "search",
  "scope": "witness-suffix-search"
}
```

`refine` runs at fixed points in the extraction pipeline: `before-search` and
`local-reference` before broad scanning; `fields`, `match` and `scopes` after it;
then `targets` and eligible `supplemental` refinements. Each pass uses the
observations available at that point. It is not a recursive expansion engine.
Overlapping scope selections retain catalog order. Conditions, whole-slot
restrictions and duplicate handling are explicit catalog settings; invalid
references and cycles fail before any filename is read.

`extraction_patterns` holds shared regex components, including joined measure
lists and separated version suffixes. `extraction_roles` connects algorithms to
their required rule inputs. Renaming a rule requires updating its references,
but does not require editing Python. The catalog schema lists all supported
settings; it does not permit executable expressions or arbitrary processors.

The audit checks:

- Exact reconstruction of every filename and every captured substring.
- Token boundaries, expected recurring-token spans and extra hits from applied
  token rules.
- Residual-span accounting and competing structural matches.
- Input, reference and installed Python/JSON source hashes, including changes
  during execution.

Acceptance checks remain active under `python -O` and `PYTHONOPTIMIZE`.
A failed invariant raises `NamingError("audit-failed", ...)`. Structural
collisions or changed inputs/code fail the command's mechanical gate. A failed
run is not accepted coverage evidence.

The audit does not evaluate the entire absent-rule-by-filename cross product or
certify document contents. New conventions require another audit.

## Compare parser changes

`Engine.extract()` includes flat `metadata` alongside its source observations.
Field `role` and `category` readings live in the same catalog as extraction
rules. The values collector does not maintain another regex registry. Useful
fields survive unsupported extensions and incomplete conventions; strict
`parse()` validity stays independent.

`tests/test_sample_regressions.py` covers the three 500-row manual reviews:
subject boundaries, UUIDs and qualifiers, missing amendment numbers, `Rev`
suffixes, descriptive conference reports, QFR/member-roster categories, and
DOCX/ZIP classification. It also checks rejected interpretations and exact
source spans. Storage sentinels, source URL resolution and alias attribution
remain indexing concerns.

`tests/test_stratified_regressions.py` covers the follow-up review of 100 rows
per document kind: compact-date counters, drafting IDs, report descriptions,
multiple measure references, explicit document categories, and subject text
beside qualifiers or fiscal years. Negative controls preserve structured IDs,
literal short years and unknown publisher abbreviations.

Run focused tests from the repository root:

```bash
.venv/bin/python -m pytest packages/house-naming/tests \
  tests/test_filename_patterns.py tests/test_filename_audit_fixes.py -q
```

Tests exercise source definitions and examples, exact fields and offsets, and
negative controls. Full-corpus comparisons provide a separate check on coverage
and regressions.

`tests/test_top500_*.py` covers the follow-up null-kind token audit. Explicit
tally sheets, numbered exhibits and appendices, participant/panelist lists,
observed statement spellings, legislative degree/substitute layouts, comparisons
and standalone publication citations receive kinds without changing strict
convention validation. A citation inside testimony remains a reference. A tally
sheet about an amendment retains the amendment fields without becoming an
amendment document. Literal support wording does not establish a letter genre.

Ambiguous publisher abbreviations require the reviewed source and filename
structure; their original wording remains available. Processing qualifiers
remain separate from document kinds. Cache-path aliases, missing capture
metadata and document grouping remain index responsibilities.

`tests/test_event_vote_wording.py` covers panel-discussion and field-hearing
context, including camel-case wording and existing notices/transcripts. The
literal `meeting_wording` and normalized `meeting_wording_code` remain available
alongside a specific genre; the event category is used only as a broad fallback.
It does not establish a transcript, witness identity, or an event's occurrence.
Publisher-supplied document types remain separate source metadata.

The complete `07.21 11-9 vote.pdf` layout retains `07.21` as a possible month/day
token and `11-9` as `vote_tally_token`. The tally cannot supply a date's year.
Neither date order, year, yes/no allocation nor outcome is inferred. The original
filename and all captured substrings remain unchanged.

The repository's
[comparison tool](../../tests/compare_filename_families.py) replays a frozen
baseline against current code, distinguishing new useful fields from new layout
matches. Keep the baseline reader, vocabulary, dependencies and input hashes
together; replacing any of them invalidates the comparison. Historical setup and
results are recorded in the
[filename-family experiment](../../tests/filename-family-experiment.md).

For deliberate interpretation corrections, `--expected-changes` accepts reviewed
exact before/after match hashes keyed by filename. Undeclared changes are first
saved for inspection and fail acceptance. A different result, stale expectation,
collision or input/code change also fails. This permits a justified correction
without weakening checks on unrelated captures.

Retained text, passing tests and broader coverage are useful evidence. None alone
proves that every filename's meaning has been resolved.
