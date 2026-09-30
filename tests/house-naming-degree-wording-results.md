# Degree wording, local numbers and measure placeholders

Accepted run: `.cache/filename-engine-comparison-20260929/degree-wording-preserved/`.
Previous accepted extractor: `malformed-dates-remainders/`.

**House extraction now exposes degree wording in 424 filenames, 392 adjacent
local numbers in 371 filenames, and explicit target wording in 23 filenames.**
It also exposes 373 previously unreported measure/placeholder pairs in 372
filenames. These groups overlap. Including three improved addendum remainders,
662 filenames gain or refine fields. Another 91 outputs change only observation
or suppressed-candidate information.

All **333,368 strict parsing results remain unchanged**. All **2,563,780 observed
field spans** match the literal input. **1,719 tests pass**, including 47 new
observed and constructed cases. Generated schemas, ECMAScript checks and
`git diff --check` pass. The native comparator, existing extraction rules and
official guide definitions remain unchanged.

## Direct comparison

| Source filename | Earlier native/House behavior | Added House fields |
| --- | --- | --- |
| `H.R.260_Shaheen_2nd_Degree_1_to_Shaheen_1st_Degree_3.pdf` | Both exposed bill 260; House retained the rest as assumed name text and a generic trailing number. | Two degree clauses, local numbers `1` and `3`, target text `Shaheen`. |
| `S.1462_Boozman_2nd_Degree_to_Schiff_1st_Degree_1.pdf` | Both exposed bill 1462; neither exposed the degree or target fields. | Two degree clauses and target `Schiff`; only the target clause has a printed local number. |
| `S.__Bennet_1st_Degree_11.pdf` | Native exposed only the extension; House used name/number fallbacks. | Senate measure type, complete `__` placeholder, first-degree wording and local number `11`. No bill number or Congress inferred. |
| `s-3199-rounds-first-degree-1032922` | Both exposed bill 3199; House treated the trailing digits as a generic identifier. | First-degree wording and whole local component `1032922`. No split into an assumed number and date. |
| `s-704-murphy-1st-degree-amendment-121119-15` | Native treated `121119` as both date-shaped text and an amendment number. House already suppressed the amendment interpretation. | First-degree wording, with the existing date candidate and independent `15` preserved. |

Degree wording stays separate from the House guide's interchamber `HAmdt2`
notation. A printed local number is not an official amendment sequence number.
Target names stay literal; these fields do not resolve people or establish a
verified amendment relationship. General phrases such as `first-degree murder`
receive no amendment role.

The 53 degree filenames without a directly adjacent number were also inspected.
They use a separate explicit amendment marker/number, have intervening wording,
or lack that local component. No local number is invented for them. Existing
dates, UUIDs, witness identifiers, revision markers and amendment/agenda numbers
keep their roles. Third-degree wording has constructed tests but no observed
example in this discovery set.

## Field preservation and rejected candidate

The full field review checks every old field and its metadata. Exactly 304
generic-number fields become local-number fields with identical source text and
spans. **Every other existing field remains, with unchanged metadata.** No coded
field or vocabulary meaning is lost; the native omission audit has no unexplained
case. The shared remainder fix additionally preserves text outside an already
recognized addendum number in three filename variants.

The first full candidate, `degree-wording-first/`, remains rejected and retained:
eight existing tests found duplicate placeholder fields, and the field audit
found two lost `pdf` suffixes. The accepted implementation lets existing whole-slot
placeholder rules take precedence and retains fallback text/suffix fields when
their generic number gains an explicit local-number role. The initial focused
suffix assertion was corrected after direct baseline inspection: the old output
had separate `pdf` and copy-number `1` fields, not one combined `pdf-1` field.

Full paired outputs, source snapshots, failure logs, target examples, all changed
fields and their explanations remain in the comparison cache. The accepted run's
`validation-manifest.json` records source hashes and validation; its
`field-review.json` and `candidate-review.json` account for the changes.

This is a bounded improvement on a reused development corpus, not proof of
complete semantic parsing. Descriptive names, titles and other local syntax
remain for further review. Changes are local and uncommitted; application
consumers remain unchanged. No source documents were downloaded.
