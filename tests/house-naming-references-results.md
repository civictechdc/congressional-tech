# House naming references and observed layouts — implementation results

Implemented the six approved changes in `packages/house-naming`. The final run
processed all **333,368** retained names. Acceptance increased from **246,213**
to **251,612**, adding **5,399** supported names. All prior accepted records and
fields survived; no ambiguous results or parser exceptions occurred in this corpus.

## Implemented behavior

- A typed `references` list exposes measures, Rules Committee Prints and fiscal
  years within recognized subject, description, amendment-ID, vote-ID and suffix
  fields. Each reference retains its literal text, source field, and character
  offsets. Original text and primary fields remain intact.
- Measure references support observed joined titles, local suffixes, separators
  and padded numbers. A reference never replaces the primary measure. The
  ambiguous `HR575921stCentAct` suffix remains unparsed.
- Fiscal-year references preserve printed two/four-digit values. A descriptive
  year never fills an absent appropriations routing year.
- Three observed layouts retain incomplete source information without inventing
  it: `bill-untyped-numbered`, `bill-untyped-draft`, and `appropriation-routed`.
  Numeric tokens retain leading zeros and placeholders. Explicit routing-prefix
  bill types/numbers and stages are extracted; unknown prefixes remain raw.
- Catalog definitions, observed examples, portable schemas, runtime validation,
  documentation and tests now include the new fields/layouts. Nested reference
  types reuse the existing vocabulary definitions during schema generation.
  Supplied references that contradict source fields are rejected.
- Full-corpus preservation and reference audits provide repeatable checks, using
  the retained pre-change outputs/candidate inventory as independent controls.

## Measured results

| New accepted layout | Names |
| --- | ---: |
| Numeric token without a measure type | 3,425 |
| Descriptive PIH draft without a measure type | 1,741 |
| Observed appropriations routing | 233 |
| **Total additional acceptances** | **5,399** |

PDF/XML coverage is now **216,920 / 240,623 (90.15%)**. Across all document
extensions it is **251,612 / 275,676 (91.27%)**. There remain **2,609 PDF/XML**
outer layouts recognized by the internal extractor and rejected by House naming;
other internal results can be partial captures or raw-only names.

The implementation exposes **540 reference occurrences in 539 names**:
**300 measure**, **146 fiscal-year**, and **94 Rules Committee Print** references.
It recovered all reviewed RCP references and all 17 previously identified
additional fiscal-year mentions. It recovered 164 reviewed measure occurrences
across 163 names, while excluding the predeclared ordinal false positive. These
are literal references, not verified legislative identities or document relations.

The raw review caught and corrected 31 draft boundaries: for example,
`BILLS-1134565pih-StartupCapitalModernization.pdf` now gives Congress `113`,
`numberToken="4565"`, and `stage="pih"`, rather than treating all digits as
Congress. PIH stays a House consideration marker; the GovInfo version vocabulary
is unchanged. All 5,399 newly accepted Congress values were then compared with
independent internal captures. Twenty-three AP routing names also expose their
explicit numbered-measure prefixes.

## Direct examples

```text
BILLS-116HR3401EAS-RCP116-21.pdf
  Primary: HR 3401, Congress 116, stage eas
  Reference: rules-committee-print, Congress 116, number "21"
  Source: versionSuffix[1:10] == "RCP116-21"

BILLS-118-HR7159-F000471-Amdt-HR7156.pdf
  Primary: HR 7159
  amendmentId: "HR7156"
  Reference: HR 7156, sourceField amendmentId

BILLS-116--AP--AP00-FY2020EW_Bill.pdf
  routing: "-AP--AP00-FY2020EW_Bill"
  committeeCode: AP00; subject: "FY2020EW_Bill"
  Reference: fiscal year "2020" within subject
  No invented measure type, stage or routing fiscalYear
```

## Verification and scope

- **963 tests passed**, covering the package and repository filename modules.
- Node compiled **83** schema regexes; **48** positive filenames and **48**
  trailing-newline rejection checks passed.
- Every accepted corpus record passed canonical render/reparse checks.
- All **246,213** old accepted records retained their original field values.
- All **333,368** internal extractor outputs stayed unchanged.
- Original guide text, definitions, examples, references, committee directory and
  footnotes remain unchanged. New patterns are explicitly observed additions.
- All returned reference spans were checked against their retained source field.
- Final source hashes matched before and after the run and subsequent audits.

This is filename-level verification on previously used development data. It does
not certify document contents, identities, availability, or unseen-corpus accuracy.
No documents were downloaded. Changes are local and uncommitted.

## Reproduce and inspect

Final artifacts: `.cache/filename-engine-comparison-20260929/references-final/`.
The earlier diagnostic run remains in `references-current/`, including its raw
review of the draft boundary bug; it is not the final accepted result.

```sh
.venv/bin/python tests/compare_filename_engines.py NEW_RUN_DIRECTORY \
  --inventory .cache/filename-engine-comparison-20260929/inventory.parquet
.venv/bin/python tests/check_house_naming_upgrade.py \
  .cache/filename-engine-comparison-20260929/metadata-upgraded-final NEW_RUN_DIRECTORY
.venv/bin/python tests/check_house_naming_references.py NEW_RUN_DIRECTORY \
  .cache/filename-engine-comparison-20260929/metadata-head-to-head-current/reverse-useful-candidates.json
```

The final directory contains native paired outputs, the comparison Parquet,
source snapshots, `upgrade-regression.json`, `references-audit.json`, and
`references-records.jsonl.gz`. Test/build logs are under the sibling
`references-work/` directory. The original head-to-head scalar mapping predates
nested references; the dedicated reference audit checks those explicitly.
