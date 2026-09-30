# Bill companion abbreviations

Decision: expose the remaining SxS/MA filename markers without conflating them
with official bill versions or replacing source document types.

Discovery found 56 isolated SxS names and 69 isolated MA names. Every SxS name
comes from HELP; MA also occurs in Massachusetts references, a farm name and
House amendment IDs. Retained receipts and original link records are saved.
The first two pages of 104 cached PDFs were extracted; two first pages were
rendered and read, including a scanned MA substitute amendment. Extraction alone
does not establish the contents of the other scanned PDFs. SxS examples contain
section-by-section descriptions; reviewed MA bill files are amendments in the
nature of a substitute. This does not establish a universal expansion of MA.

Hypothesis: a terminal companion marker can become an exact raw field while all
existing fields and strict results remain unchanged. Treat MA only immediately
after an existing leading Senate bill reference, separated by whitespace,
comma, hyphen or underscore. SxS may follow an unnumbered bill title. Permit
retained copy-number/UUID tails and hanging pdf, but not arbitrary following
prose. Protect assigned person/identifier fields and query text.

Arms: accepted literal-suffixes extraction versus one supplementary catalog
rule and its context check. The frozen native and strict baseline remains the
independent historical comparison, with the existing exact Congress-boundary
correction. No other parser, strict schema or fallback changes are intended.

Cases: all 333,368 retained names, the entire SxS/MA discovery and constructed
negative controls for Massachusetts, MA'O, protected witness names, embedded
amendment IDs, percent-encoding and unsupported suffix contexts. Before editing,
record every expected eligible marker/span from existing outputs and review
exclusions. New fields are literal abbreviations, with no official version,
exclusive document category, sponsor or event assertions.

Adopt only if each eligible name gains the expected raw field, every other
complete output is identical, prior observations remain exact after removing
the additions, typed and engine outputs agree, and existing tests, native-field
audits and corpus checks pass. Any discrepancy requires review; retain failed
trials. Source hashes must remain stable during full runs.

Use cached sources, no downloads or new dependencies. Bound full execution to
30 minutes. This reused corpus is development evidence, not an unseen semantic
accuracy test.

## Inventory correction after the first full run

The initial discovery required a boundary after SxS/MA and omitted 86 URL names
ending directly in sxspdf/mapdf, although the planned rule explicitly permitted
hanging pdf. The first full preservation check correctly rejected those
unexpected additions. Every additional name has a retained redirect to one of
the original 110 reviewed PDF filenames. Preserve the original expectations and
failed check, expand the expected set to all 196 source-proven names, and add
direct sxspdf/mapdf regression cases. The parser and acceptance requirements
remain unchanged; repeat validation against this complete source inventory.
