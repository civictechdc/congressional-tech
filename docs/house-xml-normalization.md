# House XML normalization and unreadable decisions

House record builders use one opt-in repair helper, `parse_xml_with_repairs()`.
It parses the complete original document strictly first. On a syntax failure,
it can escape a clearly literal ampersand in text or a quoted attribute when
the next character is whitespace or the relevant delimiter. It then parses the
complete result strictly. Valid references, comments, CDATA and processing
instructions retain their original bytes. A document with a document type
declaration (`DOCTYPE`) stays strict. Unknown entities, encoding guesses,
missing text and broken nesting remain unreadable. General XML readings and
MODS retain their existing strict parser.

The helper returns the parsed tree, original and normalized SHA-256 hashes,
normalized bytes, and the applied rule/count. These are available for bounded
inspection; record tables do not add a separate repair column. Typed House
objects retain acquired bytes in `raw_content`; record identities still name
the original body. A successful repair does not replace a saved raw object.

All three House record versions explicitly hash the helper. Their intentional
pin change accepts two changed outcomes: supported repairs may produce records,
and remaining syntax failures reach the shared `unreadable_decision()` writer.
A durable decision settles that body/parser/version on subsequent staging runs.
Well-formed wrong roots and admitted blank bodies still complete empty. Missing
body files raise without writing a settled failure, so the input remains pending.

## Bounded source evidence, November 6, 2026

The retained readings import source named by `model/jobs/producers/readings.json`
contained two XML error rows. Both saved bodies matched their SHA-256 keys:

| Body prefix | Source | Observed pattern | Recovery |
| --- | --- | --- | --- |
| `4cad751b9ec4` | House `BILLS-117sconres5eas.xml`, 3,289 bytes | Ends inside a table-of-contents attribute | Obtain complete source bytes; do not invent the suffix |
| `9da6a0c457ee` | House `BILLS-117hresPIH-hres7.xml`, 3,411 bytes | Ends mid-sentence without closing elements; also has a valid UTF-8 byte-order marker | Obtain complete source bytes; removing the marker cannot restore missing content |

These are resolutions, not meeting or witness lists. This historical import
sample is not a census of the current release candidate. It establishes no
population repaired by the ampersand rule; synthetic fixtures qualify that rule.
The two historical empty witness lists, `105459` and `111420`, were reread from
their original bodies and preserved their selected empty results. Two retained
valid meeting bodies, `117955` and `118261`, also parsed strictly. Keep future
rules tied to observed patterns and literal content; do not infer a full tree
from a prefix.

Evidence lives under the main checkout's
`.cache/archive-release/implementation/reviewed-non-news-20261106/ct-yr9o/`.
The focused production-offline selection exercises repair, syntax failure,
durable import, a fresh-engine rerun, empty/wrong-root/blank controls and missing
bytes. It is a partial selection, not a full-lane qualification.

## Integration still required

The release owner must freeze the selected House candidates and active decisions,
inspect their XML/error scope, and qualify the source-scoped transition. Reuse
unchanged rows only after checking their exact input and producer identities,
compare retained values and failure/pending outcomes, then reconcile selected
tables and decision inputs before publication. Preserve existing reading
compatibility entries. The generic reading diagnostics match this branch's
base evidence; existing sniff/bundle drift is unchanged by this fix.

The completed-only document-reference backfill refuses new unreadable decisions
and requires unchanged values. Its earlier proof does not qualify this change.
No corpus replay, source acquisition, shared import or publication ran here.
