# Repeated labels and date gaps

Decision: close the repeated source-structure gaps found by the context/corpus
audit, without changing strict convention validation or inferring file contents.

Hypotheses: literal Statement/meeting/nomination wording, bounded committee-print
subjects, seven-digit calendar candidates, and searching overlapping date shapes
recover useful fields currently left in broad text. When competing numeric dates
cross mixed delimiters, prefer consistent delimiters while retaining rejected
alternatives. Never turn that preference into an asserted meeting date.

Arms: frozen extraction-named-dates output and unchanged native parser versus
updated house-naming. The immediately previous context-corpus stage proved that
default extraction equals this frozen baseline on every input.

Cases: all 333,368 retained literal basenames; direct examples from next-cases.json;
counterexamples for words containing Statement, opaque IDs, invalid dates,
ambiguous date order, and labels embedded in unrelated prose. Preserve every
changed output. Reused corpus inputs are development cases.

Held constant: input inventory, source guide definitions/codes, native comparator,
strict parse/render results and optional member reference behavior. No network.
Bound full comparisons to 30 minutes and the retained inventory.

Decision rule: exact text/span retention and every prior strict result must pass.
Inspect every change family and any removed native field. Calendar candidates
must be real dates, short years remain unexpanded, rejected alternatives remain
inspectable. Literal labels do not certify document contents or witness identity.
Measure actual corpus changes and residual reductions separately from accuracy.

Revision after recurring-gaps-first: newly recognized Statement layouts retained
their full subject but could hide a previously separate date or numeric prefix.
Reuse existing date/identifier rules inside explicit document subject fields;
retain the broad field and the more precise remainder without asserting a person
identity. Keep the first comparison, then rerun all input and omission checks.
