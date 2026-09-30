# Completion audit after the amendment-form comparison

The ownership migration and the retained-corpus preservation checks pass.
Complete semantic interpretation of every filename remains unproven. Filename
text sometimes admits multiple readings or omits information present only in
its source record. The user's earlier clarification about accepting explicit
uncertainty versus requiring source-assisted resolution remains unanswered.

## Requirements and current evidence

| Requirement | Evidence and result |
| --- | --- |
| Use House naming as the single filename reader | `Engine.extract` owns extraction; its typed adapter and corpus command reuse it. No active application/package imports of the removed `congress_api` filename modules remain. Historical baseline loaders remain independent. |
| Preserve the native parser's useful observed fields | The latest full native comparison has zero unreviewed field omissions. All 31,761 omission-audit rows and 10,659 fallback-comparison rows remain unchanged from the accepted audit. This does not prove all semantic interpretations. |
| Preserve exact source characters and typed output | All 333,368 retained literal inputs and 2,579,439 field spans are checked; typed results match the engine. The recent 251 added labels preserve every previous complete result. |
| Cover shared filename tokens accurately | All 88,227 regexes match exactly the independent token spans across the corpus, including absent-token and substring boundary checks. The latest rule addition leaves that token inventory unchanged. |
| Test current inputs rather than an obsolete snapshot | All 14 original inventory/association/receipt files still have the recovery manifest's hashes, the discovered file list is unchanged, and the tested Parquet digest still matches. |
| Keep definitions, strict validation, and regression behavior | The last complete run passed 3,143 tests, generated-artifact checks and canonical-regex checks. No package source changed during this audit. |
| Work as an independent install | A newly built wheel contains all 20 package files, byte-identical to current source and the isolated install. The base engine works without Pydantic/PyArrow; the typed API and both commands work with `congress_api` blocked. |
| Recover missing or ambiguous information from every filename | Not proved, and contradicted if this requires a unique value from filename text alone. The examples below establish an information limit rather than a missing native rule. |

These inputs include document filenames and extensionless URL basenames. Counts
are names, not distinct document bodies. The corpus is reused development data,
not an unseen semantic benchmark. Residual free text is not itself a parsing
failure; it can be a legitimate title, name or unexpanded local code.

## Direct source checks of the remaining limitations

The original House XML files for meetings 105682 and 119246 still match their
retained hashes. All 12 reviewed document entries match the current XML and
their typed `HouseDocumentXML.filename_fields` values.

- Three incomplete names terminate at 145 characters in the original XML.
  The reader did not introduce those cutoffs.
- The filename ending `RepealandReplaceofHealth-RelatedTa` is attached to ten
  document entries with ten distinct sponsor/amendment-number combinations.
  The exact same filename cannot determine which one applies. All ten remain
  separate in the source model.
- The filename ending `ConsumerTaxes-B0005` contains only a partial sponsor
  token. Its source XML separately supplies `B000574` and amendment number `1`.
  Filling the token would require that particular source association.
- The filename ending `additionalreso` preserves Congress 119 and H.R. 8432;
  the source XML separately supplies the `ih` stage. That stage is absent from
  the filename and cannot be presented as extracted filename text.
- `BILLS-115s585rfh.xmlhttps:` retains its recognizable Congress, measure,
  version, embedded extension and protocol marker. The full input remains
  malformed; no missing final filename is reconstructed.
- `01 12 2022 -- Business Meeting.pdf` admits January 12 and December 1 from
  its text. Both candidates remain available. Choosing one requires additional
  evidence about the date convention or associated source record.

Existing source models already retain the external metadata needed for some
of these distinctions. Adding a global filename exception would discard context
or invent source characters. Local abbreviation expansions likewise require
qualified committee/source context; a matching token alone does not establish
that meaning.

## Verification receipts

New evidence is under `.cache/filename-engine-comparison-20260929/`:

- `completion-source-model-review.json`: twelve source/model comparisons and
  the ten distinct metadata records associated with one filename.
- `completion-ambiguity-examples.json`: current outputs showing multiple date
  candidates on actual corpus inputs.
- `completion-inventory-currency.json`: current source-list and digest checks.
- `completion-source-model-tests.log`: eight focused source-model tests pass.
- `completion-audit-amendment-forms/wheel-source-equality.json` and
  `installed-smoke.json`: rebuilt wheel, source equality, optional-dependency
  isolation, typed API and command checks.
- `completion-installed-smoke-strict.log`: confirms optional dependencies were
  not already imported before blocking them.

The first XML review compared serialization strings and failed on the harmless
`/>` versus ` />` difference between XML libraries. Parsing both snippets and
comparing their serialized element trees verifies the same subtree; original
file hashes also remain unchanged. No source or parser correction was needed.

The goal remains open. The remaining acceptance decision is whether complete
parsing includes explicit unresolved readings, or must resolve them using
document associations and other source evidence. This audit does not substitute
either interpretation for the user's goal. Changes remain local and uncommitted.
