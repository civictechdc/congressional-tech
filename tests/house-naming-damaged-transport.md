# Readable filename prefixes before damaged URL text

Decision: preserve metadata that is explicitly present before an extension-like
string followed by an HTTP protocol marker. Do not repair the source basename.

Discovery: a scan of every retained literal filename found one protocol-marker
case, BILLS-115s585rfh.xmlhttps:. Raw download receipts contain two concatenated
GPO URLs; the attempted fetch failed. The current reader retains s585 but misses
rfh and the visible xml/protocol boundary. The three other incomplete structured
names end at 145 characters in source XML; do not manufacture their missing ends.

Hypothesis: the existing extension recognizer can bound a printed protocol suffix.
A supplemental transport observation can retain the embedded extension separately
from a real final extension. For a previously unparsed structured payload, reuse
existing payload rules against only the prefix before that boundary. Label any
result as a fragment and retain only new nonempty fields. Do not add regex copies,
new canonical kinds, recursive parsing, repaired URLs or downloads.

Keep all previous observations, strict results, original stem boundary, payload
bytes and pieces unchanged. Fragment readings must not make corpus coverage claim
the complete structured payload was parsed. Test general supported extensions,
HTTP and HTTPS case variants, whitespace/query offsets, absent/unsupported
extensions, unsupported prefixes and complete names. Test the real rfh vocabulary
meaning and the typed adapter. Boundaries must use the same extension rules as
ordinary extraction.

Compare against executive-business on all 333,368 inputs and against the frozen
native/strict baseline with the existing exact strict correction file. Require
all previous complete outputs to match after removing only the approved new
transport/fragment observations. Run focused/full tests, typed-adapter comparison,
full corpus checks and native omission audit. Retain source hashes and any failed
trials. Full runs have a 30-minute limit. These reused inputs are development
evidence, not unseen semantic accuracy evidence.
