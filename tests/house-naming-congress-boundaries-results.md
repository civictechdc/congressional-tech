# Congress references and joined-number corrections

The comparison found and corrected two false bill-number interpretations:

| Filename | Previous interpretation | Corrected behavior |
| --- | --- | --- |
| `BILLS-118HR2534116thCongressih.pdf` | Primary bill number 2534116 | Descriptive draft retains `HR2534116thCongress`; digits remain `ambiguous_number_token` with an explicit boundary diagnostic |
| `BILLS-115HR5759ih-HR575921stCentAct.pdf` | Secondary bill number 575921 | Primary H.R. 5759 remains; the joined secondary digits are retained as uncertain |

The retained Congress.gov meeting 115754 record names H.R. 2534 from the 116th
Congress. Retained House XML for meeting 108746 names H.R. 5759 and the 21st
Century Integrated Digital Experience Act. These sources establish that the
old numbers were wrong. They do not make the omitted filename separators
recoverable without external evidence, so the reader does not choose a split.
It also retains the printed `ih` even where the source description says
Engrossed in House; filename wording and source claims remain distinct.

Strict validation and literal extraction share the ordinal-boundary check.
Ordinary titles beginning `the`, `Stephen`, `Third`, or uppercase words retain
their numbered interpretation. The existing descriptive-draft fallback handles
the corrected strict result; no new catalog kind was introduced. The same check
applies to free-text measure references and retained suppressed candidates.

Three other filenames gain eight Congress-reference fields: a joined
`forthe115thCongress`, `119th Congress1`, and a separated non-ordinal `115 Congress`.
These references do not replace a primary Congress. Witness identifiers and
larger numeric runs remain protected. The shared rule description now includes
non-ordinal wording; 54 other filenames change only that description.

## Verification

| Check | Result |
| --- | --- |
| Fixed corpus | 333,368 filenames |
| Focused boundary inventory | 746 filenames |
| Total changed outputs | 59: two number corrections, three reference additions, 54 description-only changes |
| Strict records | 333,367 unchanged; one exact, reviewed correction |
| All other complete output | Identical outside the explicitly reviewed changes |
| Typed adapter | All 333,368 equivalent to engine output |
| Reconstruction / field spans | 333,368 / 2,577,448 checked |
| Tests | 2,650 passed |
| Corpus mechanical gate / collisions | Passed / zero |
| Native omission audit | Two raw numeric spans retained under their new role; 19 older review flags unchanged |
| Catalog and portable regex checks | Three artifacts; 100 regexes; 54 positive and 54 rejection cases |

The strict comparison remains closed to unreviewed changes. Future comparisons
against `drafts-final` must pass
`--strict-corrections tests/house-naming-congress-boundaries-corrections.json`.
That file retains the exact before/after strict results and reason for the one
corrected filename. The harness rejects unlisted changes, altered expectations,
and stale or unused corrections; its default still requires strict equivalence.

Evidence under `.cache/filename-engine-comparison-20260929/` includes:

- `congress-boundaries/validation-manifest.json`: accepted checks and source hashes.
- `congress-boundaries/wording-review.json`: every changed result and allowed difference.
- `congress-boundaries/native-omission-changes.json`: the two reviewed field-role changes.
- `congress-boundaries-source-review.json` and `ordinal-reference-source-review.json`:
  the retained Congress.gov and House XML records.
- `congress-boundaries-partial-source-check.json`: recheck of the four incomplete
  structured names and the fields already retained from them.

This is reused development evidence, not an unseen accuracy estimate. Correcting
these errors does not establish complete semantic interpretation of every name.
The four damaged or truncated source names remain incomplete. Changes remain
local and uncommitted.
