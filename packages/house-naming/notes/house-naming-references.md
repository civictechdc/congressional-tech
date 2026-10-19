# Scoped references and incomplete observed layouts

Decision: implement the six approved additions to House naming, preserving all
existing accepted metadata and source evidence.
Baseline: metadata-upgraded-final, 333,368 recovered names, 246,213 accepted.
Hypothesis: scoped references recover explicit RCP, measure and fiscal-year text
without reinterpreting person IDs or replacing primary measure fields. Explicit
incomplete layouts recover supplied data without inventing missing slots.
Cases: full retained corpus plus observed positive cases and constructed negative
controls. The corpus is development data, not an unseen accuracy benchmark.
Held constant: internal extractor, original source catalog text/examples, input
inventory. No downloads, parser fallback, external identities or name dictionaries.
Gate: preserve all old acceptances/fields and source evidence, inspect new
ambiguities, schema validation and canonical render/reparse, and reject supplied
references that conflict with retained fields. Compare the complete native outputs.

References retain type, extracted values, raw text, sourceField and start/end
character offsets within that field. Repeated occurrences retain separate offsets.
Only eligible description/subject/amendment/vote/suffix fields are searched.
Observed incomplete forms keep raw numeric/routing tokens and leave missing types
and stages absent. Coverage gains are measured, not assumed to equal every old
rejected internal layout.

Raw review after the first implementation run found 31 draft names whose
adjacent numeric token had been absorbed into Congress. The final rules fix the
Congress width and retain those digits as numberToken, allowing the House PIH
marker in that observed numbered layout. The corpus gate now also compares every
new-layout Congress against the independent internal capture. Twenty-three
numbered measure prefixes in AP routing also receive exact primary measure fields.
The first run and its raw review remain under references-current; final validation
uses a separate references-final directory.
