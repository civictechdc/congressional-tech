# Substitute targets and local numbers: results

House naming now extracts explicit substitute targets and local numeric
components while retaining the original subject and amendment identifiers.
The accepted comparison is in
`.cache/filename-engine-comparison-20260929/substitute-fields-first/`.

The full comparison covers **333,368 retained basenames**. Strict parsing results
remain unchanged for every input, all **2,556,912 extracted field spans** match
the source text, and no existing native code meaning changed. **1,327 tests
pass**, including 49 new positive and negative cases.

## What the new fields add

Compared with `structured-slots-reviewed`, **519 filenames** gain observations.
No previously extracted House raw-field signature was removed. The new rules
expose 158 explicit target observations: 72 measure references, 78 committee-print
references, five subtitle descriptions and three contempt-report descriptions.
They also expose 231 local numeric components. These counts overlap and include
separate occurrences within a filename; they are not document counts or an
accuracy percentage.

| Literal source text | Additional fields |
| --- | --- |
| `ANStoCommitteePrint` | Marker `ANS`, target wording `to`, label `CommitteePrint` |
| `ANStoCommitteePrint119-A` | The same fields plus print identifier `119-A`; this identifier does not supply Congress |
| `ANS1toHR2804` | Marker `ANS`, local component `1`, target wording `to`, measure type `HR`, measure number `2804` |
| `033_ANS` | Local component `033` and marker `ANS`; the complete local identifier stays intact |
| `6RevisedtoANS` | Local component `6`, revision wording `Revised`, target wording `to`, marker `ANS` |

All 77 previously identified `ANStoCommitteePrint` subjects now expose their
parts. A separate final check examined every changed output: every new measure
number has an explicit printed measure type and target marker, and every local
number remains inside its retained original subject or amendment field.

## Limits enforced by the rules

The rules operate within assigned legislative fields. Ordinary words such as
`TransHUD`, `Transportation` and `WASSERMANSCHULTZ` do not become substitute
markers. Unsupported forms such as `AANS2521`, attached names such as
`GrijalvaANS`, and ambiguous number/title boundaries such as
`ANStoHR575921stCentAct` receive no new interpretation from these rules.

Local numeric components are not asserted to be bill or amendment sequence
numbers. Marker spelling is retained without inventing an official vocabulary
definition. Broad target descriptions stay visible in residual-text analysis;
recognizing the surrounding phrase does not establish the meaning of every word
inside it.

The native omission audit has no unexplained omissions. Its existing categories
include invalid date candidates, overlapping assigned tokens, renamed fields
and separated extensions; this does not mean every native interpretation was
copied. Source guide definitions, examples, committee references and strict
schemas remain unchanged. The generated JSON check and the existing ECMAScript
checks pass. Source hashes match the retained comparison snapshot.

## Remaining work

Full semantic interpretation remains incomplete. The next review inventory,
saved from current outputs in `next-cases.json`, contains 26 attached-name and
substitute field occurrences, 16 with `XMLfiledbyRep` wording, and nine with
`XMLtoHR` wording. These need bounded splits that preserve author text, target
references and complete local identifiers without guessing person identities.

This reused corpus is development evidence, not an unseen accuracy benchmark.
The native corpus consumer is unchanged. Implementation and results remain local
and uncommitted.
