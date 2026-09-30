# Source context and corpus helpers

Decision: port the native parser's optional surname boundary recognition and
shared-token/residual analysis into house-naming so source interpretation and
corpus review do not require the native parser.

Hypotheses: Congress-keyed surname references recover explicit Rep/name/title
boundaries without a built-in surname list. Token and residual helpers expose
recurring syntax and unexplained text without counting a broad capture or a
user assumption as complete semantic understanding.

Arms: frozen native outputs and the previous extraction-named-dates output versus
the current package. Re-run native member extraction with the same supplied names
because the saved comparison omitted that optional input.

Cases: all 333,368 retained basenames for default extraction and token checks;
all relevant legislative basenames for reference-assisted extraction; retained
legislator service records plus existing raw regression examples. Constructed
boundary and negative cases remain explicitly test fixtures. The reused corpus
is development data, not an unseen accuracy benchmark.

Held constant: strict parsing/rendering, guide text and codes, native parser,
corpus, source reference bytes. No network, hardcoded surnames or inferred person
identities. Record source hashes and complete changed outputs. Bound each pass
to 30 minutes and the retained inventory.

Decision rule: default extraction must remain exactly unchanged. Supplied names
must apply only to their Congress and retain exact spans; compare each native
split and inspect additional/missing splits. Token regexes must recover every
observed occurrence with no extras in tested token/name pairs. Residual spans
must partition all alphanumeric source text independently of overlapping fields;
literal recurrence and lack of residual text are not semantic accuracy claims.

Revision after context-corpus-first: requesting a review of complex amendment
fields also excluded simple, already parsed amendment IDs from the coverage
calculation. Keep simple numeric/alphanumeric amendment and document IDs as
specific fields while reviewing complex values. This changes the residual report,
not source extraction. Retain the first run and repeat the complete audit.
