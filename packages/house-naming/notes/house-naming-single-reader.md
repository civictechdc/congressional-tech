# One literal filename reader

Decision: make `congress_api.parse_filename` a typed adapter over
`house_naming.Engine.extract`, after fixing reference/date precedence.

Hypothesis: reserving explicit measure, amendment, exhibit and document
identifiers before generic dates removes false date interpretations without
losing actual adjacent dates, structured identifiers or original source text.
The adapter should preserve every engine observation and suppressed candidate.

Arms: frozen native outputs and accepted SENR extraction outputs versus the
shared engine and its typed adapter. The native parser is a comparator, not an
oracle: it sometimes emits both a reference and a conflicting date.

Cases: the retained 333,368-name development corpus; the feedback's HR111111,
H.R. 12345 and S.Hrg.119-12345 examples; all four reference families with
date-shaped numbers, adjacent real dates, UUIDs and structured witness slots;
strict structural matches rejected for calendar/schema validation.

Held constant: inventory, guide definitions, strict matching priorities and
rendered records. No source fetches. Preserve the old implementation and outputs
in the existing cache before deleting the production duplicate. Each corpus run
has a 30-minute bound. Reused examples are not unseen accuracy evidence.

Decision rule: adopt when regression tests pass, corpus inputs/spans reconstruct
exactly, the adapter preserves every engine field, and changed extraction
outcomes have an inspected explanation. Strict accepted records and priority
selection must remain unchanged. Additional rejection codes are intentional;
they must come from an actual structurally matched candidate's validation error.
New extraction rules belong only in guide.json. Complete text retention is not
complete semantic parsing.

After the first full comparison: unconditional reservation cut complete separated
dates after Attachment wording into an item number plus numeric suffixes. Reject
that run. Reserve complete compact identifiers, but suppress a reference that
would consume only the prefix of a complete separated date. For ambiguous
compact amendment suffixes, preserve the reference syntax and the alternative
date as a suppressed candidate, without claiming a verified official number.

The adapter also exposed source-label differences and the extra GovInfo RHUC
code. Preserve House labels with their guide-page URLs; move the existing
GovInfo vocabulary into house-naming and re-export it from congress_api so RHUC
keeps its label and source. Literal grammar still has one owner in guide.json.

The first downstream corpus rebuild found ten pre-existing overlapping layouts:
five whole document labels also split into subject plus label; five malformed
sponsor amendments also match the broad measure-list layout. Prefer the complete
known label and exclude explicit sponsor-amendment slots from measure-list.
Check that other subjects and measure lists retain their fields. Keep the first
run and its failed corpus gate for comparison.
