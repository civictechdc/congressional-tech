# Category wording: accepted improvement

Three supplemental catalog rules add **470 literal wording fields to 466
filenames**. All previous extraction output remains identical after removing
only those added observations. The comparison covers all 333,368 retained
filenames; it does not establish complete semantic interpretation.

| New rule | Observations | Representative capture |
| --- | ---: | --- |
| `managers-amendment-wording` | 108 | `ManagersAmendment`, `Manager's Amendment`, original `Managers_Amendement` spelling |
| `notice-agenda-wording` | 184 | `hybrid_hearing_notice`, `forum_announcement`, leading dated `Agenda` |
| `summary-component-wording` | 178 | `SummaryOfChanges`, `bill_summary`, `Section-by-Section Summary`, `Joint Explanatory Statement` |

The rules preserve original text and exact offsets. They add no official codes,
exclusive document categories, event access or author identity. Existing
generic labels and more specific wording can coexist. `Trade Policy Agenda`
topics do not receive agenda-document labels; structured witness identifiers
remain protected. The two `VoteSummary` examples already have that complete
literal document token and are left unchanged.

## Evidence

- **2,216 tests pass**, including 59 new positive, boundary, protected-slot and
  mixed-document controls.
- All **333,368** inputs retain their previous observations, strict results,
  diagnostics, suppressed candidates and source-character reconstruction.
- The typed adapter agrees with the engine on every input.
- The corpus checks **2,575,620 field spans**, reports zero rule collisions and
  passes its mechanical gate with unchanged source hashes during execution.
- The native omission audit remains unchanged, including the five previously
  reviewed sponsor/amendment refinements.
- Every changed filename and new field agrees with the reviewed discovery;
  no changes occur outside that set. Two formerly opaque suffixes are now fully
  covered by the new manager's-amendment wording.
- Generated schemas, portable-regex checks and `git diff --check` pass.

The first focused run caught four boundary/overlap failures. The first full
suite then caught eleven regressions from selecting contextual rules too
broadly. Both are retained. The corrected implementation restores explicit
supplemental-rule selection and passes the original acceptance criteria.

All evidence is under `.cache/filename-engine-comparison-20260929/`:
`category-wording-discovery.json`, `category-wording-probe.json`,
`category-wording-final/wording-review.json`,
`category-wording-final/iteration-summary.json`,
`category-wording-final/validation-manifest.json`, and
`category-wording-corpus-final/coverage.json`. Interrupted outputs in
`category-wording/` and `category-wording-corpus/` are rejected trials.

## Remaining source problems inspected directly

The four remaining unparsed legislative payloads include three cut-off names
and one damaged URL basename ending in `xmlhttps:`. All three cut-off strings
are present verbatim in retained House meeting XML, so the filename reader did
not introduce that loss.

The source review inspected **12 document entries** from meetings 105682 and
119246. One truncated basename is reused for ten different amendments. Their
XML supplies distinct sponsor IDs and amendment numbers; three entries also
link a separate, more informative filename. Those distinctions cannot be
recovered from the identical truncated basename alone. Preserve source record
associations and explicit metadata instead of reconstructing missing characters.

The raw evidence, source hashes and associations are retained in
`remaining-structured-raw-xml.json` and `remaining-structured-origins.json`.
These findings guide the next review; they do not make the truncated names
complete or justify a new global abbreviation rule.

Changes remain local and uncommitted. The broader goal remains unfinished:
local shorthand, ambiguous free text and damaged source inputs still need
review without converting retained text into invented metadata.
