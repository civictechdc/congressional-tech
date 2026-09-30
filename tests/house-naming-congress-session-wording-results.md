# Congress references and executive-session wording: results

Accepted a bounded improvement: 402 of 333,368 retained filenames gain 779
literal fields. All existing observations, strict records, validation
diagnostics, suppressed candidates and source text remain unchanged.

| Wording | Filenames | Observations | New fields |
| --- | ---: | ---: | ---: |
| Ordinal Congress references | 54 | 55 | 165 |
| Executive session | 372 | 372 | 614 |

The groups overlap. Executive-session fields include 242 explicit Open tokens;
the remaining 130 do not acquire access wording. Closed/plural examples are
constructed controls, not observed coverage in this inventory. Congress wording
uses `referenced_congress`, separate from the primary `congress` field.

For example, `BILLS-119pih-116th-Congress-vs-118th-Congress.pdf` retains primary
Congress 119 and exposes references to 116 and 118. `11-15-18 -- Open Executive
Session.pdf` retains its date and adds the literal session/access words. Neither
case establishes a document identity, event occurrence or verified access status.

The discovery review contained 425 rows for 401 distinct names. The full run
also found `help-rules-119th-congresspdf`, covered by the predeclared hanging-pdf
boundary. Its additional Congress reference was checked directly. Every changed
record retains its earlier observations exactly; only the two intended rules
add observations. The five previously reviewed native suffix differences remain
unchanged and fully represented by specific sponsor/amendment fields.

Validation:

- 2,045 tests pass, including 39 new wording cases.
- All 333,368 engine results equal the typed application adapter.
- All 333,368 filenames reconstruct exactly; 2,575,146 source spans checked.
- Full downstream corpus rebuild passes, with zero structural collisions.
- Generated JSON, ECMAScript regex checks and `git diff --check` pass.
- No source changed during either full run.

Evidence: `.cache/filename-engine-comparison-20260929/congress-session-wording/`
contains source snapshots, outputs, comparisons, source review, preservation
review and the validation manifest. `congress-session-wording-corpus/` contains
the downstream outputs. The independent native comparator remains in
`drafts-final/`; the preceding accepted extraction is `single-reader-final/`.

This is reused development data, not an unseen accuracy benchmark. Complete
semantic parsing remains unproven. The subsequent check against GovInfo's CPRT,
CRPT and CHRG help pages exposed additional gaps, recorded separately in
`govinfo-help-coverage.json`; this wording change does not fix them.
