# Structured marker corrections: accepted

The full comparison corrects structured metadata in **20 filenames** and changes
only the explanatory description in another 16. Every other complete output is
identical to the accepted `legislative-wording` baseline.

| Cases | Earlier output | Corrected output |
| --- | --- | --- |
| 7 hanging-PDF basenames | Unknown version `ispdf` | Recognized `is` version plus retained `ignored_suffix="pdf"` |
| 6 joined `SUS` forms | Unknown version `SUS` | `local_code_token="SUS"`, with the existing House consideration definition |
| 7 joined `ANS` forms | Unknown version `ANS` | Literal `amendment_marker="ANS"`; separate `HAmdt` markers remain unchanged |
| 15 `SA` and 1 `or` forms | Unmapped version-shaped tokens | Values and fields unchanged; enclosing rule description clarified |

For example, `bills-118s3679ispdf` now exposes version `is` with the existing
"Introduced in Senate" label. It retains the final `pdf` characters separately
and still reports a missing or unsupported extension. It does not invent a dot,
rename the file or verify its contents.

`BILLS-117HR1443SUS-RCP117-7.pdf` retains H.R. 1443 and print RCP117-7 while
recognizing `SUS` as consideration under suspension. That definition already
exists in the catalog's retained House guide, table `table-8408-row-2`, page 7.
The existing marker readers provide these roles; no parallel vocabulary was
introduced. Joined `UConsent` is also supported and tested against the same
existing consideration reader. There are no such joined examples in this corpus.

## Verification

- **2,382 tests pass**, including 87 new source, known-version, exact-boundary,
  protected-slot, annotation, numeric-modifier and format controls.
- The earlier test that incorrectly treated `SUS` as an unmapped version was
  replaced with source-definition and role assertions. Unknown `SA` and `or`
  remain covered by the original negative controls.
- All **333,368** inputs were compared against the accepted extraction and the
  frozen native/strict results. Exactly 36 outputs changed as specified above.
- Every changed result equals its independently specified field correction or
  description-only update. Dates, identifiers, suffix text, diagnostics and other
  observations remain unchanged outside those explicit corrections.
- No coded field was removed and no existing code meaning changed. The typed
  adapter agrees with the engine for every input.
- The corpus checks **2,576,325 field spans**, reports zero structural collisions
  and passes its mechanical gate. Source hashes stayed stable during execution.
- Generated schemas, ECMAScript checks and `git diff --check` pass.

The older omission audit compares single fields and flags the seven split
`ispdf` tokens plus seven relocated empty suffix boundaries. Every new flag was
checked directly: adjacent `is` and `pdf` fields cover the entire old token, and
each empty suffix remains empty. The audit and its flags are retained unchanged,
with separate evidence in `native-omission-review.json`. The five previously
reviewed sponsor/amendment refinements remain unchanged.

## Evidence and remaining work

Artifacts are under `.cache/filename-engine-comparison-20260929/`:
`structured-markers-discovery.json`, `structured-markers-focused-review.json`,
`structured-markers/field-review.json`, `structured-markers/iteration-summary.json`,
`structured-markers/native-omission-review.json`,
`structured-markers/validation-manifest.json`,
`structured-markers-corpus/coverage.json`, and `structured-markers-tests.log`.

The four incomplete legislative payloads remain visible. This correction does
not settle joined action prose, bare manager shorthand, local abbreviations or
the meaning of unknown `SA`/`or` tokens. Those remain review work rather than
guessed metadata. The repeatedly used development corpus does not prove complete
semantic interpretation or accuracy on future filenames.

Changes remain local and uncommitted. The broader filename interpretation goal
remains active.
