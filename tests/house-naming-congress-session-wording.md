# Congress references and executive-session wording

Decision: expose explicit Congress and executive-session wording left in broad
filename text by the current shared reader.

Hypothesis: two supplementary catalog rules recover useful literal metadata
without changing primary Congress numbers, guessing meeting access, declaring
events to have happened or losing dates, references or original source text.

Arms: frozen native/strict results in `drafts-final`; accepted shared-reader
results in `single-reader-final`; the two wording rules below. Keep strict
record validation, existing definitions and existing extraction fields fixed.

Cases: retained discovery has 53 filenames with 54 Congress phrases and 372
filenames with executive-session wording, including 242 with explicit Open.
The executive-session names all came from finance.senate.gov. No observed Closed
example exists in this discovery; Closed cases are constructed controls, not
measured corpus coverage. Include repeated references, primary/reference Congress
disagreement, plural sessions, case and separator variants, URL-shaped query
suffixes, hanging pdf, malformed ordinals, concrete witness IDs and word fragments.
These inputs are reused development evidence rather than unseen evaluation.

Intervention: capture `referenced_congress`, `congress_ordinal`, `congress_marker`
from explicit ordinal-plus-Congress wording. Preserve printed digits, zeroes and
ordinal spelling; warn on a malformed ordinal without repairing it. Do not
assign the number to other objects or derive calendar years. Capture literal
`meeting_wording` and optional `access_wording` from executive-session phrases;
absence of access wording stays absent. Use the existing supplementary pass so
earlier fields, descriptions and fallbacks remain inspectable. Concrete IDs and
dates retain their protected spans. Rules belong only in guide.json.

Decision rule: review every changed input and new field against its source span;
require no removed fields or changed existing field metadata, unchanged strict
records/diagnostics, no unexplained native omissions, adapter equality, and
passing full tests and corpus checks. Each full run is bounded at 30 minutes.
Keep failed experiments and document any revised criteria. Do not interpret
complete character retention as complete semantic parsing.
