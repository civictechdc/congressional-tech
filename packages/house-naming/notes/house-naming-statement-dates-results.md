# Statement abbreviations and incomplete dates: results

Accepted run: `.cache/filename-engine-comparison-20260929/statement-dates-reviewed/`.

The full comparison covers **333,368 literal names**. Strict parse results remain
unchanged for every input, all **2,558,190 field spans** match their source text,
and existing code meanings and official guide definitions are unchanged.
**1,514 tests pass**, including 57 added cases. Generated JSON and ECMAScript
checks pass. All comparison source hashes match the current implementation.

## Extraction gains

**154 filenames gain or refine fields**:

- **132 statement labels:** bounded Stmt/STMNT/SMNT wording, including joined
  uppercase suffixes after a recognized leading named date. These retain their
  literal spelling; they do not acquire an official document code or certify
  document contents. Six filenames also expose a trailing local numeric component.
- **22 yearless dates:** forms such as `13 APR`, `27 April` and `11May` expose
  printed day/month components without an inferred year, century or event role.
- **Three malformed years:** `16DEC202BATEMANSTMNT`, `16DEC202DOKHOLYANSTMNT` and
  `21JUL202MarshallSTMNT` retain year `202` with a warning and no calendar candidate.
  These three names also appear in the statement-label count.

Examples:

| Filename | Additional fields |
| --- | --- |
| `05JUN2019GraySMNT.pdf` | Literal label `SMNT`; existing date and remainder retained |
| `18JUN2020CASSIDYSTMNT1.pdf` | Label `STMNT`, local numeric component `1` |
| `BEGICH stmt.docx` | Literal label `stmt` |
| `18APR23_SECNAV Posture Statement_SASC_Final_Updated 13 APR.PDF` | Additional date `13 APR`; existing `18APR23` stays separate |
| `16DEC202BATEMANSTMNT.pdf` | Day `16`, month `DEC`, printed year `202`, warning, remainder `BATEMANSTMNT`, label `STMNT` |

Seven numeric-prefix assumptions now become printed day components. Their seven
name remainders lose only the newly recognized date prefix and separators.
Every removed field was checked against these exact transformations. No other
prior fields or shared field metadata change. Another **103 outputs change only
the day/month rule's description** to acknowledge optional and malformed years;
there are 257 changed outputs in total.

All 132 abbreviation discovery candidates were reviewed against their raw names.
Of the 70 broad day/month discovery matches, the only four left without a named
date are UUIDs containing month-like hexadecimal fragments. They remain protected
identifiers. This is a discovery subset, not a coverage claim for unseen names.

## Rejected candidate and retained controls

The first full run is retained as rejected in `statement-dates-first/`. An overly
strict month-first boundary removed 18 useful date candidates before following
time, upload-suffix or range-like digits. It also misread `%20Feb` inside one
literal Content-Disposition string as `20 Feb`.

The accepted version preserves all 18 existing month/day readings and prevents
percent-prefixed byte fragments from becoming day tokens. It does not decode or
repair those inputs. Focused tests also cover complete/short/absent years, invalid
calendar dates, structured witness IDs, uppercase suffix boundaries, duplicate
compound labels and bounded long-input execution. Two initial negative fixtures
were corrected to preserve the existing possible `DEC2`/`DEC 2` readings; their
failure and the reason are retained separately from the rejected corpus run.

`candidate-review.json` contains every field addition/removal for the 154 names.
`iteration-differences.jsonl.gz` retains complete before/after outputs for all
257 changes. `omission-audit.json` has no unexplained native omissions, and
`validation-manifest.json` records counts and source hashes.

This is a bounded improvement on reused development data. Full semantic filename
interpretation remains incomplete; name assumptions and retained raw characters
do not establish identity or complete meaning. Native consumers are unchanged.
Work remains local and uncommitted; no downloads were needed.
