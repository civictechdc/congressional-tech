# House Naming Guide

A self-contained JSON catalog, JSON Schemas, Python API and CLI for extracting
metadata from House document filenames and GPO hearing/report/print identifiers. It includes
**Document Naming Conventions, v1.2.1, updated April 24, 2012**, plus layouts
observed in retained document inventories. One bundled convention set; no network
access at runtime or document conversion.

**Scope:** recognizes the cited conventions and explicitly documented observed
layouts. Successful parsing is not certification of current House posting
requirements or an official schema.
The retained committee directory is historical reference data, not an allowlist.

## Install and use

From this directory, with Python 3.10 or newer:

```bash
python -m pip install .
house-naming check
house-naming render examples/witness.json --plain
```

Output: `HHRG-112-ED-WState-IveyB-20110922.pdf`

Install this local project, not an assumed public registry package. Installation
may download dependencies; runtime operations remain offline. The sole direct
runtime dependency is `jsonschema>=4.18,<5`.

Optional interfaces are owned by this package too:

```bash
python -m pip install '.[typed]'   # Pydantic result models
python -m pip install '.[corpus]'  # Typed models and Parquet inventory reader
house-naming-corpus filenames.parquet output-directory/
```

`house_naming.filenames.parse_filename` returns typed results from
`Engine.extract`. `house_naming.filename_corpus.build_corpus` builds review
artifacts from literal names; its command reads `filename` and `variants`
columns in a Parquet inventory. Both use the same extraction rules and residual
reader. See [filename tooling](FILENAME_PATTERNS.md).

Supply optional surname context as `--member-surnames member-surnames.json`,
containing a Congress-keyed object such as `{"119": ["Clyburn", "Miller-Meeks"]}`.
Prepare that vocabulary in the source-data application; this package does not
depend on `congress_api` or parse raw legislator records. Imports from the former
`congress_api.filenames`, `filename_corpus`, `naming` and `bill_codes` modules
must use `house_naming` instead. Bill definitions live in `house_naming.bill_codes`;
the House guide URL and lookups live in `house_naming.naming`.

```python
from house_naming import Engine, NamingError

engine = Engine()
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
result = engine.parse(filename)
assert result["valid"]
assert engine.validate(record) in [match["record"] for match in result["matches"]]

validated = engine.validate(record)  # fresh dict, or NamingError
stage = engine.lookup("version", "RH")
contexts = engine.contexts("SC")
committee = engine.committee("AG00")

# Literal source metadata, even when the name is not a renderable convention.
source = engine.extract("Opening Statement-Hassan-2020-06-03.pdf")
assert not source["valid"]
assert any(item["rule"] == "labeled-subject-date" for item in source["observations"])
```

`Engine()` exposes **56 kinds**: 54 filename conventions and two link-only
kinds. `render()` returns a filename, or the supplied URL for a link-only record.
It never creates, renames, uploads or fetches documents. `validate()` and `render()`
do not mutate inputs. Validation fills declared defaults: older witness records
without `meetingType` receive `HHRG`; a hearing without a publication suffix
receives an empty `publicationSuffix`. Validation also fills derived metadata
from the retained filename fields, rejecting contradictory supplied values.
`NamingError` exposes `code`, `details`
and `as_dict()`.

## Reading literal source filenames

`extract()` reads source basenames, including spaces, stacked extensions, Word
and image files, and extensionless publication IDs. It performs no I/O. Its
`valid`, `matches` and `issues` fields have exactly the same meaning and values as
`parse()`: they describe validated naming records. Additional source observations
do not turn a nonconforming filename into a valid rendering convention.

The extra fields are:

| Field | Meaning |
| --- | --- |
| `stem_end` | End offset before recognized extensions or query-shaped suffix text. |
| `observations` | Rule, scope, raw match location and captured fields, including literal unknown tokens. |
| `pieces` | Word, number and separator spans whose concatenated text exactly restores the input. |
| `suppressed` | Candidate matches and their full fields, withheld because of an assigned slot, invalid calendar reading or date following revision wording. |

Each observed field contains `name`, `raw`, zero-based character offsets
`start`/`end`, `candidates`, `note`, and optional vocabulary `code`, `label` and
`context`. These source-slot names follow the native extractor's snake_case
names, separately from validated record fields. For example, a printed
`measure_number` is source text; the validated record's `measureNumber` is an
integer. A `context` and `code` resolve through `lookup()` to the retained guide
definition, including its examples and source references. Field labels can be
more specific than the printed catalog label: `HAmdt2` has the field label
`House amendment (second degree)`, while lookup retains the original `HAmdt2`
entry. Report parts and component spellings absent from the catalog have no
context. A shared prefix only receives a meaning in an appropriate filename
slot; a committee-vote `CRPT` prefix does not establish a published report.

Original spelling, whitespace and punctuation remain in `input` and `pieces`.
No extension is invented for `CHRG-106hhrg53880`; the publication fields are still
extracted. Literal media suffixes (`mp3`, `mp4`, `m3u8`) and server-endpoint
suffixes (`aspx`, `cfm`) are preserved separately from the stem. They do not
identify the returned content: an ASPX/CFM handler can serve XML or PDF, and a
playlist-looking URL can return an empty response. Canonical House filename
formats remain limited to their declared extensions.
Terminal `SxS` and Senate-bill `MA` companion markers are exposed as
`document_abbreviation`, including filenames with copy numbers or UUID tails.
The marker stays literal and unexpanded; it is not an official bill version.
`MA` elsewhere, including Massachusetts references and assigned amendment IDs,
does not receive this companion interpretation.
`Committee Print`, `Rules Committee Print` and related literal wording receive
a `print_token` when not already captured. A mention in a tally-sheet title does
not make that file a print. In legislative descriptor/suffix slots, `CPT` stays
an unexpanded `local_identifier`; any local number stays separate from bill or
print numbers, and an adjacent `ih` receives its existing version definition.
That reader also separates uppercase local markers followed by lowercase `ih`,
such as `RSCih`, `SCPih` and `OAWPih`, without expanding the marker. Separated
`IH`/`PIH` and terminal `Filed` wording retain their own fields. These filename
tokens do not verify the document's current legislative stage or filing history.
Reported-bill suffixes such as `rh-p1` expose the literal `p` and numeric
identifier without assigning an official report, part or page identity.
Explicit substitute targets also survive inside legislative suffixes, including
`AINStoHR1759` and `ANStoHR3633offeredbyChairmanThompsonofPennsylvania-U1`.
The latter preserves the offering wording and raw offerer text separately;
it does not resolve a person or establish that an offering occurred.
Explicit `Act of 2024` wording, including joined `NetworkActof2024`, exposes
`reference_marker` and `reference_year_token`. Each printed reference stays
separate, including when a filename mentions multiple Acts. These years do not
establish enactment dates, event dates or Congress numbers. Longer digit runs
such as `Act-of-20182` remain intact; no trailing digit is treated as a copy
number. Assigned witness names and amendment identifiers remain protected.
Terminal bracketed numbers such as `(002)` and `[1]` expose a
`local_number_token`, preserving leading zeros. Their role as a copy, revision
or document number remains unverified. Existing plausible dates and concrete
identifiers take precedence over this supplementary reading.
Query-shaped text such as `&download=1` is reported separately without
asserting that the input is a URL. No URL decoding or file-content validation is
performed. Calendar candidates do not establish meeting dates, timezones or the
century of short years. Invalid dates in explicit date slots retain their text and
an explanatory note. Dates with written month names also receive calendar checks;
their printed year is not reused as a generic numeric identifier.
Complete named-date shapes such as `5APR22` take precedence over their contained
`APR22` fragments. Invalid complete dates retain their calendar warning, and
overlapping alternatives remain inspectable without selecting a century.
Text after a leading named date is retained through the existing name or subject
fallback; recognizing the date does not discard the remaining text.
Yearless day/month forms such as `13 APR` retain no year or event role.
Month/year wording such as `April 2021` has a separate `month_year_token` with
candidate `2021-04`, plus the original month and year components. No day is
invented. Written `Fiscal Year 2024` and `FiscalYear2024` use the same fiscal
marker/year fields as `FY2024`; short fiscal years retain their unspecified
century. These supplementary readings preserve previous fallback assumptions
for inspection and skip fragments inside concrete dates or assigned source IDs.
Three-digit year spellings such as `16DEC202` retain their printed components
with a warning and no calendar candidate; the extractor never repairs them.
Complete numeric shapes such as `03.01.20231` and `9-25-191` likewise remain
whole with an unsupported-year-length warning. Their components do not become
independent short dates or generic identifiers. No corrected year or upload
suffix is inferred; earlier fragment candidates remain inspectable in
`suppressed`. This recognition requires consistent punctuation and possible
month/day components, and respects already assigned source identifiers.
Generic label/date layouts also keep complete numeric components, including
`2022-09-141`, with a warning rather than silently splitting a day from a suffix.
Their label and subject fields remain active; the previous split stays in
`suppressed` for inspection. Unlabelled year-first shapes receive the same
warning. The shared remainder extraction preserves independent names and numbers
before or after a malformed shape.
Degree phrases such as `2nd_Degree` expose their literal wording and ordinal in
`degree_token`. Adjacent numbers remain whole `local_number_token` values, with
dates and assigned identifiers taking precedence. In
`H.R.260_Shaheen_2nd_Degree_1_to_Shaheen_1st_Degree_3.pdf`, the two degree clauses
retain separate numbers and `target_subject` preserves `Shaheen`. These fields
do not resolve a person, establish an official amendment number or adopt the
guide's interchamber `HAmdt2` meaning. General degree wording also remains literal.
`S.__Bennet_1st_Degree_11.pdf` retains measure type `s` and the full `__`
placeholder without inventing a bill number or Congress. A single underscore
can be a separator and does not trigger the general placeholder search.
Questionnaire wording (`SJQ`, `APQ Responses`, `Senate Questionnaire`, including
plurals and full-word variants) and biographical wording (`Bio`, `Bios`, `CV`,
`Resume`) are exposed as literal `label` fields. Existing `Biography` labels
share the same qualifier and number handling without duplicate labels. Adjacent
`Public`, `Final`, `OCR`, `Redacted`, `Amended` and `Updated` words receive
`qualifier_wording` fields. A terminal qualifier group can follow the name when
only delimiters, digits, dates, opaque identifiers or a hanging pdf remain.
`Public Health Questionnaire` therefore does not acquire a Public qualifier.
These words do not establish access, publication state or verified file contents.
Digits directly after a recognized label or qualifier remain whole local-number
components; calendar candidates and source identifiers retain priority.
`Remarks`, including Opening, Prepared, Written, Oral and Closing Remarks, also
receives a literal label. Its qualifiers must precede the label in the same word
group or form a terminal group after it. `Remarks Public Health Hearing` does
not treat Public as a qualifier. Dates, other labels and source IDs remain
separate; remarks wording does not resolve a speaker or verify document contents.
Bounded statement abbreviations (`Stmt`, `STMNT`, `SMNT`) and uppercase terminal
`STMNT`/`SMNT` after a leading named date remain literal labels. Trailing digits
are local numeric components, not a revision or document sequence inferred from
the label. These observations do not certify a document's type or contents.
Explicit weekly notices identify a week-start date and flag non-Monday values
without changing them. Number notes distinguish report parts, covered measures,
appropriation sequences, en bloc groups, meeting sequences and activity quarters.
Uncertain word endings such as `Services`/`es` retain the
whole description and candidate code without a known-version label.

Seven-digit date forms retain every supported calendar reading with an unpadded
month/day. Numeric date searches consider overlapping candidates and prefer
consistent separators when candidates compete for the same text. Other readings
remain inspectable in `suppressed`; a selected span still has no established event
role. Explicit document labels retain separate dates, numeric prefixes and subject
remainders when those components are recognizable. Committee-print wording and
subtitle identifiers are extracted inside recognized legislative subject slots.
Specific legislative slots are refined before generic token searches: malformed
sponsor spelling remains literal, and sponsor or amendment identifiers do not
become dates. A subject such as `HR__` retains the measure type and placeholder
without a bill number. Explicit underscore placeholders also separate subject
titles, and an amendment identifier remains separate from its update or en bloc
group number.
Measure references accept filename separators within abbreviations, including
`S-Res`, `S_Con_Res` and `H._Res.`, using the same measure vocabulary as `S.Res.`.
Supplementary amendment references retain identifiers before a hanging `pdf`
(`amendment-1pdf`) and whole compound values (`amendment_1v2`). The latter also
exposes its local numeric component and printed V-number. These readings do not
establish official amendment numbers, GovInfo text versions or revision history.
Dates and opaque IDs remain protected, earlier assumptions stay inspectable, and
already assigned references are not duplicated.
The `SENR` filename family exposes its committee, optional subcommittee,
nomination/field-hearing wording and meeting words separately. Source-backed
labels interpret `NP`, `PLFM`, `WP`/`W&P`, and `ENR`/`Energy` only in that
committee context. `ENR` in the subcommittee slot means Energy. Printed
`Cmtr`/`Submte` spellings remain unchanged. `Hrg`, `Bus Mtg` and `Roundtable`
do not establish a meeting date, occurrence or access status. No official
committee identifier or missing subcommittee is inferred; existing labels and
source text remain available.
Printed citations such as `S. Hrg. 115-693`, `S. Prt. 114-27` and `H. Rept. 118-XX` expose
`citation_marker`, `citation_congress` and either `citation_number` or a printed
`number_placeholder`. Marker codes `shrg`, `sprt`, `hrpt` and `srpt` identify Senate
hearing, Senate print, House report and Senate report references. These fields do not identify
the file's contents or supply a Congress for a separate bill reference. A printed
hearing number differs from the jacket number used in a GovInfo hearing package
ID; the extractor never substitutes one for the other. See GovInfo's
[hearing documentation](https://www.govinfo.gov/help/chrg) and
[report citation documentation](https://www.govinfo.gov/help/crpt).

GovInfo package fields cover `CHRG` hearings (`hhrg`, `shrg`, `jhrg`), `CRPT`
reports (`hrpt`, `srpt`, `erpt`) and `CPRT` prints (`hprt`, `sprt`, `jprt`, `wprt`).
The literal reader preserves Congress digits, publication codes and number
strings, including leading zeros. Number notes distinguish hearing jacket IDs,
report numbers and the ambiguous jacket-ID-or-print-number slot used by
[committee prints](https://www.govinfo.gov/help/cprt). A WPRT package denotes a
House Ways and Means print; it does not supply a committee identifier elsewhere.
Parts, volumes, addenda and errata are read inside the publication suffix before
generic date scans. Unnumbered markers differ from absent markers. The hearing
help page uses `err` for both addenda and errata; the literal observation retains
that ambiguity even though the existing strict field is named `errata`.

Loose `HRPT`/`SRPT` numeric subjects remain `report_subject_token`, distinct from
an official report number. Source examples use this slot for report numbers,
measure numbers and local identifiers, sometimes with joined or incorrect digits.
The reader preserves the whole printed subject and extracts explicit `Part` or
delimited `p` suffixes separately. These assigned numeric slots do not become
generic dates or member identifiers. No embedded Congress or missing measure
type is inferred.

Substitute wording inside legislative fields retains explicit targets such as
`ANStoCommitteePrint` and `ANStoHR6498`. Local forms such as `ANS_01` and `1toANS`
expose their literal components while preserving the entire identifier. Their
numeric components do not establish bill or amendment sequence numbers. Broad
target descriptions remain visible in residual analysis.
Compound filing text such as `ANS_02XMLfiledbyRepBluntRochestertoHR6571`
retains the local identifier, format wording, filer text and target reference.
`XML` does not establish the file's actual format. Printed `Rep`/`Reps` markers
can expose name wording without resolving a person; source misspellings and
combined names remain intact. Target references never replace primary metadata.
Support/opposition phrases expose `relation_wording` plus optional `subject_token`
before the phrase and `target_subject` after it. For example, a dated filename
containing `Group Letter of Support for Smith` retains `Group`, the complete
wording, and `Smith`, separately from an existing boundary date or UUID. The same
rule retains bill targets and ordinary title text; it does not certify a letter,
author, identity or actual position. Existing parent fields remain available.
Only assigned dates, opaque identifiers, numeric components and hanging suffixes
at the descriptive region's edges are trimmed. Interior tokens and complete
measure references remain part of the source text. Unassigned digits attached to
a target name stay intact, and absent sides remain absent.
Descriptive-side trimming preserves periods, including `U.S.`, `Inc.`, `Jr.`
and leading-dot names; spaces, underscores and hyphens serve as separators.
Numbered committee-print identifiers remain distinct from Congress and bill
numbers. Mixed-case prefixes such as `Grijalva` before `ANS` stay descriptive
text, without asserting a person identity. Delimited local forms such as
`CMT-AMD_01` expose their marker and numeric component while preserving the whole
identifier. Discussion/subcommittee draft wording stays separate from official
text-version codes.

Question/answer wording includes `QFR`, `QFRs`, `QFR's`, `Questions for the Record`
and explicit responses/answers to those questions. These phrases use the same
literal label and subject rules as testimony and statements; surrounding names
and titles do not establish a person identity. Labels joined to terminal `pdf`
text, such as `testimonypdf`, also remain discoverable. That text does not create
an extension or verify a file format, and ordinary response titles do not become
questions-for-the-record documents without the printed question wording.

Structured fields protect IDs and numbers from unrelated global searches.
Explicit text slots can still yield contained references, updates and document
markers. A joined measure list yields every occurrence, including after `SA`.
This prevents a witness ID from becoming a bill or date while retaining useful
references in amendment text. Multiple observations can describe the same span;
they are source observations, not independently verified document identities.
When a `BILLS` payload is incomplete, an explicit substitute phrase can still
expose its visible target through the same whole-slot rule. The enclosing raw
payload and validation issues remain; missing versions, sponsor IDs and amendment
numbers are not reconstructed. A target's free text can itself be cut off.

Damaged URL text such as `BILLS-115s585rfh.xmlhttps:` retains `xml` as an
`embedded_extension` and `https:` as a `protocol_marker`. Existing payload rules
can expose new fields from the readable prefix, such as the printed `rfh`
version. These fragment observations preserve the original malformed name,
payload and validation failure; they do not supply a repaired URL or clear the
incomplete-payload review flag. An embedded extension is not a final extension.

The final fallback follows the user's corpus policy: recognize plausible dates
and timestamps first, then generic numeric IDs, and only then assume the remaining
text is a name. Those fields explicitly say **fallback assumption**. A hanging
`pdf` or final `-testimony`/`-tedtimony` is retained separately. ZIP basenames never
become assumed person names; explicit appendix labels and other syntax can still
be extracted. A fallback, a recognized outer layout, or complete character
retention does not mean that all semantic meaning in the name has been resolved.
The same fallback runs on progressively shorter remainders to retain components
at both ends, such as the two numbers in `1-Smith-2`. Each parent string remains
available. Specific references found in free text protect their numbers from
being reinterpreted as generic identifiers.
Remainder dates also respect the main scan's selected dates: calendar-plausible
fragments cannot cross or replace an already assigned date or identifier.
An explicit addendum number followed by a date keeps those components separate.
Revision wording can precede a compact date as well as a separated date, retaining
all supported calendar readings. Same-month ranges such as `June 9-10, 2021`
expose both day tokens and the printed year. Their `date_range_token` has one
normalized start/end interval candidate (`2021-06-09/2021-06-10`); invalid ranges
keep their raw components and a warning without an interval candidate.

Printed phrases such as `119th Congress` yield a separate `referenced_congress`;
they do not set the file's primary Congress or assign one to other references.
Ordinal spelling and leading zeros remain visible, with warnings for malformed
values. Separated non-ordinal forms (`115 Congress`), joined `forthe`/`ofthe`
wording, and a trailing local digit (`119th Congress1`) also retain the explicit
reference. The trailing digit is not interpreted as a session or occurrence.
`Executive Session` wording yields `meeting_wording` and, when printed,
`Open` or `Closed` yields `access_wording`. These fields describe filename text;
they do not verify an event's identity, occurrence or access status.

Meeting/session headings can also expose `result_wording` for printed `Results`,
as in `Results of Executive Session`, `EBM Results`, or `Mark up 1.13.22 Results`.
Existing dates and access wording remain separate. The observed intervening
`Committee on Finance` title is accepted explicitly; arbitrary committee-name
prose is not. Literal `EBM` and the observed `Sessio` spelling are not expanded
or repaired. This wording does not verify a meeting outcome or a vote result.

`meeting_wording` preserves the full `Executive Business Meeting` heading.
Within a recognized results heading, `meeting_abbreviation` retains `EBM`
without expanding it or inferring access or occurrence. Explicit `Open` or
`Closed` wording remains a source claim.

Budget views/estimates and authorization/oversight-plan phrases also retain
their literal wording, including within amendment subjects. Existing notice or
shorter plan labels remain available. A visibly joined uppercase `FY`, as in
`ViewsandEstimatesFY2020`, exposes the fiscal marker and printed year without
interpreting lowercase words such as `testify2020`. Separate fiscal-year tokens
remain separate observations, including when they disagree. Short years keep
their unspecified century; these phrases do not establish adoption or contents.

Explicit filename phrases also expose literal `label` fields for manager's
amendments, hearing/markup notices, forum announcements, leading dated agendas,
summaries, fact sheets, section-by-section analyses, explanatory statements and
errata. Joined `ManagersAmendment`, the observed `Amendement` spelling and
`SummaryOfChanges` retain their exact spelling. Topic phrases such as Trade
Policy Agenda do not become agenda-document labels. Multiple labels can coexist
in one filename; none assigns an exclusive type or verifies file contents.
Concrete witness identifiers remain protected from these wording searches.
Manager's substitute, preamble, resolving-clause and title amendments retain
their complete phrases, as do manager's packages. The same amendment forms also
retain their full wording without a manager prefix, including joined, spaced,
hyphenated and underscored spellings. Existing numbered amendment references
remain separate; a longer manager's phrase is not repeated as a shorter label.
`As Reported`, `Reported Out`,
`As Amended`, `As Introduced` and `As Filed` become literal qualifier fields;
they neither replace an official filename version code nor verify an action.
Full-committee and subcommittee mark/markup phrases remain separate from source
scope codes, even when those two signals disagree. Capitalized joined phrases
such as `DefenseFullCommitteeMark` expose the phrase without expanding `Defense`
into a committee identity. Arbitrary joined lowercase prose remains whole when
its word boundaries are not established.

`Ordered Reported`, optional `As Amended` and `Voice Vote` wording also retain
their exact spans. `Legislative Text` can retain an attached `As Reported Out of
Committee` qualifier. Reported/amended-by phrases keep the text following `by`
without resolving a person or committee. That boundary requires a separator,
visible CamelCase transition or a comparison ending such as `_vs_rcp`;
`Reported Bylaws` therefore does not invent a reporting relationship. Hanging
`pdf` remains separate. These observations do not verify actions or vote results.

Committee-resolution and GSA-resolution wording remain literal labels. Numbered
GSA references such as `GSA2018-50` expose `reference_marker`,
`reference_year_token` and `reference_number`, including when a parsed local ID
is followed by a joined bill-version code. The year-shaped reference component
does not set an event date or fiscal year; its number is not reinterpreted as a
compact date. A distinct date form such as `GSA12-12-2018` retains its date reading.

GSA-style project references such as `PDC-0002-WA21` expose the printed prefix,
middle identifier, final letter code and two-digit year-shaped component. These
codes do not establish a location, century or project identity. The middle
identifier remains whole even when its digits resemble a date; slashes omitted
from the filename are not restored. An explicit `FY21` final segment also keeps
its existing literal fiscal-year fields.

A recognized legislative version followed by hanging `pdf` keeps the version
and a separate `ignored_suffix`; the hanging text does not become a file
extension. For example, `bills-118s3679ispdf` exposes `is` and `pdf` separately.
An exact `SUS` or `UConsent` in a short-marker slot uses the House consideration
meaning; `ANS` uses the existing amendment-marker role. Unknown `SA` and `or`
remain unassigned. The older `legislative-unlisted-version` rule ID remains for
compatibility, but its fields carry these more precise roles.

Digits joined to ordinal title wording have an uncertain boundary. For example,
`HR2534116thCongress` does not establish bill number 2534116. Strict parsing
rejects that numbered interpretation with `ambiguous-number-boundary` and uses
the existing descriptive fallback when available. Literal extraction retains
the digits as `ambiguous_number_token` without selecting a split. The same check
applies to secondary references such as `HR575921stCentAct`; an independently
printed primary bill number remains intact. Ordinary titles beginning `the`,
`Stephen` or `Third` retain their existing numbered reading.

The observed rules are `guide["extraction_rules"]`. They use Python `re` syntax
with ASCII case-insensitive structural matching, independently of the portable
rendering schemas. Lower-priority stem and legislative rules are fallbacks. The
runtime is self-contained and does not import `congress_api` or require Pydantic.
Source input is bounded to 16 KiB of UTF-8 and must be a basename, not a path;
the stricter 255-byte rendering limit still applies to validated filenames.

### Optional surname references

Callers can supply a surname vocabulary for each Congress without installing a
legislator data reader in this package:

```python
source = engine.extract(
    "BILLS-119HR9269RepClyburnRenewingtheAfricanAmericanCivilRightsNetworkActih.pdf",
    member_surnames={"119": ["Clyburn"]},
)
```

This adds a `member-title` observation with `Rep`, `Clyburn` and the literal title
as separate fields. It leaves the original description and validated record
unchanged. The longest supplied surname wins; omitted spaces, apostrophes and
hyphens inside that surname are tolerated. The title must start at an uppercase
boundary. Missing or wrong-Congress references leave the text unsplit. A surname
match establishes a candidate text boundary, not a member identity, office or
sponsorship. Reference acquisition and service-date selection belong to the caller.

The CLI accepts the same mapping through `--member-surnames FILE.json` (or `-`
for standard input), with its existing 64 KiB JSON input limit.

### Corpus analysis

The standalone helpers in `house_naming.corpus` consume an extraction result:

```python
from house_naming.corpus import filename_tokens, shared_token_pattern, residual_fields

tokens = filename_tokens(source)
pattern = shared_token_pattern(("Statement", "statement"), "word")
remaining = residual_fields(source, include_unstructured=True)
```

`filename_tokens()` returns literal words and numbers plus ASCII CamelCase parts,
excluding extensions and separated query text. For example, `RepClyburn` yields
the whole word and the parts `Rep` and `Clyburn`; `Renewingthe` stays one part.
`shared_token_pattern()` produces a regex bounded to those exact token rules.
The caller counts recurrence and supplies the observed spellings; the package
does not turn a repeated word into an inferred document type.

`residual_fields()` identifies text left inside descriptions and suffixes after
subtracting more specific source spans. Use `field_names` to inspect other text
slots and `include_unstructured=True` to include stems without a recognized outer
layout. Each result includes the original field, the fields covering portions of
it, and the remaining source spans. Broad text captures and fallback assumptions
cannot conceal that remaining text. Residual prose can be an appropriate title or
name; an empty residual does not prove complete semantic accuracy.

## Data and schemas

There is exactly one copy of each JSON artifact, under `src/house_naming/data/`:

| File | Purpose |
| --- | --- |
| `guide.json` | Canonical catalog: patterns, field types, codes, source examples, definitions, footnotes, committee lookup and local provenance. |
| `guide.schema.json` | Closed catalog structure; the runtime additionally checks cross-references, indices and templates. |
| `record.schema.json` | All typed input records, selected by `kind`, with shared field definitions. |
| `filename-lexical.schema.json` | Weaker candidate filter for existing basenames, **not** full runtime validation. |

Other languages can load these files directly. All schemas use Draft 2020-12 with
internal references only. Python consumers can call `load_guide()` or `engine.guide`
to obtain an independent mutable copy of the catalog. Neither modifies the
engine's catalog. `engine.kinds()` lists the available record kinds.

The catalog preserves **137 code entries in 16 contexts**, **160 source-example
occurrences**, **131 committee/subcommittee entries**, **nine footnotes**, and
**446 locally resolvable source anchors** across 45 retained sections. Source
references resolve in `guide["source_nodes"]`; original documents are unnecessary.
The member appendix on source pages 30–40 is intentionally omitted, including its
source anchors. Bioguide identifier fields and naming-rule examples remain.

`guide["patterns"][kind]` contains field definitions, required fields, a template,
source references, and implementation decisions. `observed_examples` contains
actual filenames that support additional layouts, separately from the guide's
unchanged `source_example_ids`. Patterns based entirely on the observed corpus
have no guide source references. `parse_templates` lists explicitly supported
alternative layouts with the same fields. `derived_fields` lists metadata
extracted inside a retained field rather than printed separately in the template.
`parse_as` names a shared record pattern for conventions whose filename alone
does not distinguish their source meaning. Codes are keyed by context and
case-folded token; committees use exact folder codes. `AG` is not rewritten to
`AG00`. Unknown entries return `None`; unknown code contexts raise `NamingError`.

## Validation and parsing contract

`parse()` returns `valid`, `ambiguous`, every matching candidate in `matches`, and
source evidence separately in `found_in_source`, `source_example_ids` and
`source_issues`. Invalid basenames return `valid: false`; non-string inputs raise
`NamingError`. `input` preserves the original spelling. Every candidate contains
a validated `record` and its `canonical_filename`; that rendered spelling may
differ in fixed-token case or use a declared canonical layout. Re-parsing the
canonical filename retains the record. `matched_conventions` lists the catalog
patterns supporting each result. Conventions that explicitly share a record
are combined; distinct interpretations remain separate candidates.

`parse_priority` lets observed fallback rules run after more specific conventions.
Zero is the default. Parsing retains all validated candidates at the first
priority with a valid candidate, so a broad draft rule cannot replace a recognized bill or
committee record. Ambiguity within that priority remains visible. Lexical schemas
only identify possible shapes; they do not implement this selection order.
Structural matches that fail validation remain in `rejected_candidates`, with
their kind, priority, error code, message and details. Their codes also appear
in `issues`. A failed candidate does not prevent a later priority from succeeding.
`extraction_rules()` returns copies of the literal rule catalog for corpus tools.

```python
result = engine.parse("HMTG-113-AP06-Wstate-BrewerB-20130424.PDF")
match = result["matches"][0]
assert match["record"]["meetingType"] == "HMTG"
assert match["record"]["witnessId"] == "BrewerB"
assert match["canonical_filename"] == "HMTG-113-AP06-WState-BrewerB-20130424.pdf"
```

Additional layouts include date-first `SD`, `QFR`, `MbrRoster`, `CPg`, and `TOC`
documents; committee transcripts; the CRPT vote layout without the literal HMTG
segment; and `CHRG` GPO hearing identifiers. Witness documents preserve HHRG,
HMTG, or HMKP as `meetingType`. GPO records expose Congress, publication type,
publication number, and the literal `publicationSuffix`, including part, volume,
addendum, or errata text. Separate `part`, `volume`, `addendum`, and `errata`
fields preserve printed identifiers such as `II`. An empty value means the
marker is present without an identifier; an absent field means no unique marker
was extracted. Unknown or repeated components remain in `publicationSuffix`.

Numbered reports parse as `published-report` with `documentType: "report"`.
The guide's page-12 `conference-numbered` convention remains available for
rendering known conference reports, and appears in `matched_conventions` when
its syntax matches. Conference status requires separate source evidence.

```python
report = engine.parse("CRPT-112hrpt332.pdf")["matches"][0]
assert report["record"]["kind"] == "published-report"
assert report["record"]["documentType"] == "report"
assert "conference-numbered" in report["matched_conventions"]

appropriation = engine.parse("BILLS-113HR-FC-AP-FY2014-AP00-Agriculture.pdf")["matches"][0]["record"]
assert appropriation["description"] == "AP-FY2014-AP00-Agriculture"
assert appropriation["fiscalYear"] == "2014"
assert appropriation["committeeCode"] == "AP00"
assert appropriation["subject"] == "Agriculture"
```

Appropriations conventions share `appropriation-described` records, preserving
the original `description` alongside the explicit two/four-digit fiscal year,
routing code, subject and optional descriptive remainder. No century is inferred.
A fiscal-year-looking token later in the description cannot fill an empty year
slot. Explicit `suppl` and `CR` forms also expose `appropriationType` and `sequence`.

Additional observed forms include alternate bill separators, version occurrences
and parenthetical annotations, amendments to literal subjects such as
`CommitteePrint`, committee-routed prints, and vote ranges/labels. Bare numeric
amendment subjects stay literal; they do not become bill numbers. Amendment and
vote identifiers preserve their spelling and are not expanded into inferred lists.
`witnessIdType: "bioguide"` identifies a whole witness token with that syntax;
it does not verify a person's identity. Extraction stays within known slots.

Embedded measure, Rules Committee Print, and fiscal-year references are returned
in a typed `references` array when present. Each reference keeps `raw` text,
`sourceField`, and zero-based character offsets `[start, end)` within that field.
References never replace primary bill fields or fill missing routing slots.
The original subject, amendment ID, vote ID, description or suffix remains intact.

```python
record = engine.parse("BILLS-116HR3401EAS-RCP116-21.pdf")["matches"][0]["record"]
assert record["references"] == [{
    "type": "rules-committee-print", "congress": 116, "number": "21",
    "raw": "RCP116-21", "sourceField": "versionSuffix", "start": 1, "end": 10,
}]
```

A `measure` reference supplies `measureType` and `measureNumber`; a `fiscal-year`
reference supplies the printed `year` string without expanding a two-digit year.
Repeated occurrences retain separate locations. Parsing does not search person
identifiers, dates or publication numbers for embedded references. Unknown word
boundaries remain unparsed, including the ambiguous `HR575921stCentAct` suffix.
Supplied references must agree with the retained fields; validation derives them
when omitted and rejects contradictory values. JSON Schema validates their shape;
the runtime checks their relationship to the retained text.

Three observed layouts retain information without inventing missing
fields: `bill-untyped-numbered` keeps a literal `numberToken` (including zero
placeholders); `bill-untyped-draft` keeps the House `pih` marker and description;
`appropriation-routed` keeps the original `routing` and extracts only the
measure type/number, stage, year and committee slots that are explicitly supplied.
These observed layouts use an explicitly three-digit Congress slot, including
draft names where another number immediately precedes `pih`.
These are observed naming patterns, not additional official guide conventions.

Further observed layouts separate named draft labels and local identifiers,
number placeholders, numbered subjects with intervening descriptions, combined
measure lists, descriptive IH/PIH drafts, and House amendment suffixes. They run
as fallbacks. `numberedSubject` preserves leading zeros while an explicit measure
type can also supply an integer `measureNumber`. Empty numbers and placeholders
never become bill numbers. Numbered PIH files retain the House marker without
adding it to the GovInfo version vocabulary.

```python
record = engine.parse("BILLS-115HR3798HR1150HR6718HR4616-RCP115-84.pdf")["matches"][0]["record"]
assert record["measureList"] == "HR3798HR1150HR6718HR4616"
assert [ref["measureNumber"] for ref in record["references"] if ref["type"] == "measure"] == [3798, 1150, 6718, 4616]
assert "measureNumber" not in record  # No primary measure is selected.
```

List references use `sourceField: "measureList"`; their offsets preserve each
occurrence. The optional `SA` prefix remains literal. In an interchamber amendment
marker, `HAmdt2` means second degree, not amendment number two. Known markers expose
`amendmentDegree`; an observed suffix such as `002` stays in `amendmentSuffix`
without an inferred degree. A bare numeric subject is still not a bill identity.

Descriptive fallbacks recognize IH/PIH only. A joined mixed-case ending such as
`OAWPih` returns `ambiguous-stage-boundary` instead of guessing whether `P` belongs
to the description or to PIH. Unknown or more detailed text can remain in a
description even when the outer layout matches; acceptance is not proof that all
meaning in that description has been interpreted.

```python
bad = engine.parse("HMTG-112--HHRG- AG03-20110705.pdf")
assert bad["found_in_source"] and not bad["valid"]

ambiguous = engine.parse("CRPT-112hrpt-HR2055-DivisonA-som.pdf")
assert ambiguous["valid"] and ambiguous["ambiguous"]
```

`engine.examples(value)` retrieves original example occurrences, including malformed
ones. `engine.source(source_id)` retrieves their local source text. Definitions,
source spelling, duplicate examples and documented inconsistencies are not repaired.
Interpretations stay visible in pattern `decisions` and `requires_interpretation`;
that flag is descriptive, not an enable/disable switch.

JSON Schema checks input shape and lexical constraints. The runtime additionally
checks real Gregorian dates, Monday week starts, URL structure, UTF-8 byte length,
unsafe filename characters. Parsing accepts ASCII case variations in fixed tokens,
code fields, extensions, and the revision marker. Free text such as witness names
retains its exact spelling. Rendering requires canonical code values; it does not
silently change caller-supplied free text. String identifiers retain leading zeros;
integral JSON numbers such as `112.0` render as `112`.

Revision suffixes render as `-U<number>` before the extension. Free tokens cannot
end in `-U<digits>` or `-u<digits>`, which are reserved for revisions. Optional `meetingOccurrence` values
start at 2. House posting conventions use `pdf` and `xml`; published GPO hearings,
reports and prints also support `htm` and `html`. An extension does not entail
reading or validating file contents. Tokens are prepared input: no transliteration,
name parsing, Unicode normalization, arbitrary separator repair or numeric-padding
repair is performed. Missing bill types, member IDs, and other required metadata
are not invented.

## CLI

```bash
house-naming kinds
house-naming validate examples/witness.json
house-naming parse HHRG-112-ED-WState-IveyB-20110922.pdf
house-naming extract 'Opening Statement-Hassan-2020-06-03.pdf'
house-naming lookup version RH
house-naming contexts SC
house-naming committee AG00
house-naming source table-8491-row-3
house-naming schema
house-naming schema --filename-lexical
```

`validate` and `render` accept `-` for JSON from stdin. Results are JSON on stdout;
errors are JSON on stderr. `render --plain` outputs only the name or URL. Help and
version output are text. Exit status: 0 for success, 1 for invalid input or no parse
match, 2 for usage, resource-limit, I/O or configuration errors. An ambiguous parse
with valid candidates succeeds; an empty lookup also succeeds.
`extract` exits successfully when the source was processed, including when its
`valid` field is false. This does not certify a convention or inferred identity.

## Maintain and test

Edit `guide.json` for data/rules; edit `guide.schema.json` only when changing the
catalog's structure. Both are trusted configuration. Then run:

```bash
python -m pip install '.[test]'
python tools/build.py
python tools/build.py --check
python -m pytest -q
node tools/check_ecmascript.mjs  # optional; no npm dependencies
```

The build regenerates lookup indices, code-linked field enums and the two derived
schemas deterministically. No source extraction pipeline is needed. Reusable field
definitions are stored once per generated record schema. `tests/records.json`
contains constructed regression fixtures for all kinds, not a source transcript.
Tests cover required fields, malformed inputs, ambiguity, source fidelity,
calendar checks, revisions, deterministic builds, CLI and network-free execution;
seeded tests exercise 1,440 additional filename round-trips. `test_observed.py`
checks exact metadata from actual corpus names and negative controls for missing
fields, malformed dates, and unsupported repairs. `test_metadata.py` checks the
new metadata, convention migrations, HTML variants and slot-boundary collisions.
`test_references.py` checks reference values/locations, incomplete records,
conflicting supplied references, and identifier/ordinal counterexamples.
`test_drafts.py` checks fallback precedence, placeholders, adjacent measure
references, degree markers and misleading word/code boundaries. The
repository's `check_house_naming_upgrade.py` and `check_house_naming_references.py`
compare complete saved corpus runs for preserved records and reference gains.

Compatibility: parsing `conference-numbered`, detailed appropriations conventions,
and `committee-rules` now returns their shared record kinds; original convention
names remain in `matched_conventions`. Existing records still validate and render.
Consumers should use the returned record rather than assuming that every old
rendering convention remains a distinct parsed kind. Derived values are optional
on input and present on validated output when established by the retained fields.

## Deployment boundaries

Installed catalog/schema files must be trusted and read-only to untrusted callers.
Consistency validation is not a sandbox for malicious regexes. Inputs are bounded:
64 KiB per CLI record, 32 fields per record (scalars plus an optional array of at
most 64 flat reference objects), 160 characters per ordinary free token and 240
for observed draft/routing text,
32 per sequence identifier, 2,147,483,647 maximum positive counter, and 255 UTF-8
bytes per output filename. No external schemas or URLs are fetched.

URL validation checks ASCII HTTP(S) structure, percent escapes, host and port,
and forbids credentials; it does not certify a publisher or complete RFC compliance.
A downstream fetcher must enforce its own SSRF/redirect policy. File storage must
separately handle collisions, symlinks, permissions, URL escaping and filesystem
normalization. Rendered names are not proof of identity, authority, existence,
uniqueness, legislative status or compliance. Escape source text before HTML display.

The corpus comparison under the repository's `tests/` directory retains measured
coverage and source hashes separately from unit-test results. Neither filename
coverage nor round-trips establish document-content accuracy. The optional Node
check tests regex portability, not JavaScript JSON Schema validator integration.
See `NOTICE` and `LICENSE` for source attribution and licensing.
