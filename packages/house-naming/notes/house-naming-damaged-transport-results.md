# Metadata retained from a damaged URL basename

The literal reader now extracts the visible `rfh`, `xml` and `https:` fields from
`BILLS-115s585rfh.xmlhttps:`. Its previous Congress, Senate measure, number and raw
payload remain intact. The complete source basename still fails strict validation
and remains on the incomplete-payload review list.

The retained download receipts establish the source of this malformed text:
two GPO URLs were concatenated. Original attempts returned error JSON; a later
malformed GovInfo candidate returned HTML. All retained response bytes were
checked against their receipt hashes. The filename's `xml` text does not
establish a successfully retrieved XML file.

One new guide rule identifies a trailing HTTP protocol marker only when the
existing extension recognizer finds extension-like text immediately before it.
For previously unparsed structured payloads, the reader reuses existing rules
against that prefix. New fields appear in fragment observations, without copying
regexes, rewriting the filename, fetching a replacement, or creating canonical
records. Existing fields are not repeated. The three other truncated structured
names remain unchanged; absent source characters cannot be reconstructed.

## Verification

| Check | Result |
| --- | --- |
| Fixed corpus | 333,368 filenames |
| Changed filenames / new observations / new fields | 1 / 2 / 3 |
| Every previous complete output after removing additions | Identical |
| Typed adapter versus engine | All 333,368 equivalent |
| Reconstruction / field spans | 333,368 / 2,577,783 checked |
| Tests | 2,715 passed; 49 focused existing/new cases passed |
| Native omission and fallback detail files | Identical to the accepted prior run |
| Corpus mechanical gate / structural collisions | Passed / zero |
| Incomplete structured payloads | Four, deliberately still reported |
| Catalog and portable regex checks | Three artifacts; 100 regexes; 54 positive and 54 rejection cases |

The first test trial caught the missing catalog-scope declaration; the next caught
a test comparing Pydantic tuples with JSON lists. Both failed logs remain saved.
The final test uses the actual JSON serialization boundary. No parser expectation
was relaxed to hide an extraction difference.

Evidence is under `.cache/filename-engine-comparison-20260929/`: the
`damaged-transport` comparison/manifest, `damaged-transport-corpus`, discovery,
source receipt/body checks, focused preservation report and test logs. The full
comparison retains the previously accepted exact strict correction for the
unrelated joined bill/Congress digits; this iteration changes no strict result.

These are reused development inputs, not unseen accuracy evidence. Fragment
recognition does not establish complete semantic coverage. Changes remain local
and uncommitted.

## Next source question

A separate inventory found 70 numbered-looking HRPT names. The first retained
House XML sample, meeting 104284, names a Committee Report - USSS: An Agency in
Crisis and uses `1` in its `legis-num` field for `HRPT-114-1.pdf`. This does not
establish an official report number. Preserve that uncertainty while reviewing
repeated-Congress and Part forms next. Discovery and the exact XML sample are
saved in `numbered-hrpt-discovery.json` and
`numbered-hrpt-source-discovery.json`; no HRPT interpretation changed here.
