# Single-reader cutover: feedback addressed

All four findings are addressed. The changes remain local and uncommitted.

| Finding | Implemented change |
| --- | --- |
| 1: duplicate literal readers | `congress_api.filenames.parse_filename` calls `HOUSE_NAMING.extract`. Removed application `RULES`, `UNMATCHED_RULES`, compiled regex lists and interpretation logic. The 112-line module contains typed results and small adapters. Corpus token helpers and rule discovery use house-naming. |
| 2: numeric references treated as dates | Measure, amendment, exhibit and document references reserve complete numeric tokens before generic date scans. Structured witness IDs, citations and UUIDs retain precedence. References cannot consume only the prefix of a complete separated date. |
| 3: stale API documentation | Updated naming.py, FILENAME_PATTERNS.md and package READMEs to describe the shared literal reader and 56 strict record kinds. |
| 4: hidden validation failures | `Engine.parse` keeps the first priority with a valid candidate. `rejected_candidates` records failed kinds, priorities, codes, messages and details; `issues` includes their codes. Later valid priorities still work. |

## Corrections to the feedback and first implementation

The native parser sometimes returned both an identifier and a date, so it was
not a correctness oracle. Frozen outputs remain available independently of the
new adapter.

Unconditional early reference reservation hid real separated dates such as
`Attachment 3-27-19`. That trial was rejected and retained. The final guard keeps
the complete date. Compact `Amendment111111` remains literal reference syntax;
its calendar interpretation is retained as a suppressed candidate. Neither
interpretation proves an official amendment number or event date.

The downstream rebuild exposed ten existing overlapping layouts. The catalog
now prefers complete labels such as `Opening Statement` over a partial subject
split, and malformed sponsor amendments over the broad measure-list layout.

The adapter retains every engine field, including vocabulary contexts and URLs,
scopes, descriptions and suppressed alternatives. Labels use their House-guide
wording and source pages. The existing GovInfo vocabulary moved into house-naming
and is re-exported by congress_api; the additional `RHUC` code keeps its label
and GovInfo URL.

## Verification

- **2,006 tests pass**, including direct engine-to-adapter equality, corpus CLI
  failure checks, date/reference boundaries and strict validation diagnostics.
- All **333,368 filenames** pass engine-to-adapter equality and exact character
  reconstruction; **2,574,367 extracted source spans** checked.
- Strict accepted records and priority outcomes remain unchanged for all inputs.
  **9,248 inputs** gain validation diagnostics.
- The actual corpus command processes all 333,368 inputs with **zero structural
  collisions**, a passing mechanical gate and no source changes during the run.
- **163 inputs** change raw field sets relative to the saved SENR extraction.
  The review accounts for every removed field: 234 date interpretations replaced
  by explicit references; 20 partial exhibit fields rejected in complete dates;
  93 fallback text fields retained in broader text; 10 partial label/subject fields
  replaced by complete known labels; five measure-list fields retained under a
  more specific field name; five suffixes split into sponsor/amendment fields.
- No coded field was removed and no existing shared field metadata changed,
  apart from adding source URLs. The native omission audit left five suffixes for
  manual review; all five are fully represented by the new specific fields.
- Generated JSON, ECMAScript regex checks and `git diff --check` pass.

Evidence is under `.cache/filename-engine-comparison-20260929/`:
`single-reader-final/` contains frozen source, comparisons, field review and
manual native-omission review; `single-reader-final-corpus/` contains the real
corpus outputs. Earlier rejected runs remain in `reference-reservation/` and
`single-reader/`. The pre-cutover native implementation remains in `drafts-final/`.

This validates the cutover on reused development data. It does not establish
complete semantic understanding of arbitrary filenames or source-document truth.
