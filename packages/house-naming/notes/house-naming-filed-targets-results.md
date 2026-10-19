# Compound amendment filing text: results

House naming now separates local identifiers, format wording, filer text and
explicit target measures in compound legislative filenames. The accepted run is
`.cache/filename-engine-comparison-20260929/filed-targets-first/`.

The full comparison covers **333,368 retained basenames**. Strict results remain
unchanged for every input; all **2,557,303 extracted field spans** match the source
text. **1,368 tests pass**, including 41 new tests. No previous House field or
field metadata changed or disappeared, and no existing native code meaning
changed. The native omission audit has no unexplained omissions.

## Direct source review

A case-insensitive scan found 44 filenames containing `filedby`, `XMLto` or
`XMLfiled`. Each has the expected new extraction, with 46 occurrences because two
filenames repeat their compound text in separate slots. Compared with the prior
House extractor, the new fields include:

- 43 explicitly numbered target references and three targets with number
  placeholders and descriptive titles;
- 34 filer fields: 20 with printed member/name wording and 14 with Majority or
  Minority wording;
- 46 local file identifiers, 44 XML format markers, and two numeric modifiers
  after XML.

Counts overlap and refer to field occurrences, not distinct documents.

| Source text | Newly extracted components |
| --- | --- |
| `H4814_ANS_01XMLfiledbyRepSototoHR4814` | Local ID `H4814_ANS_01`, format wording `XML`, filer `RepSoto`, name wording `Soto`, target `HR4814` |
| `TRAHAN_041XMLfiledbyRepsTrahanandObernoltetoHR6544` | Plural marker `Reps`, combined name wording `TrahanandObernolte`, target `HR6544`; no guessed split into person identities |
| `BILIFL_046_XML002filedbyRepBilirakistoHR2365` | Local ID `BILIFL_046`, format wording `XML`, literal modifier `002`, filer and target |
| `DINGMI_096filedbyRepDingelltoHR____AmericanPrivacyRightsActdiscussiondraft` | Filing text without an XML marker; target type `HR`, placeholder `____`, descriptive title and no target bill number |

`Crdenas` stays exactly as printed. `RepSoto` does not become plural `Reps` plus
`oto`. All-uppercase or lowercase filer text stays whole when the marker/name
boundary is ambiguous. A spelled-out substitute phrase after `RepFry` is kept
separate from the name. XML wording never becomes a file-extension or content
verification claim. Local numbers never become official amendment numbers.

The native parser preserves these compound fields but does not expose their
filing roles or joined target references. In the Soto example, its generic
measure search also reads the person identifier `S001200` as a Senate measure;
the existing House field protection prevents that interpretation. Full native
and House outputs for all 44 names are retained in `direct-head-to-head.json`.

## Validation and remaining work

The implementation reuses the existing whole-field measure and placeholder
rules for targets. Negative tests reject ordinals, missing target types, ordinary
XML words, incomplete filing text and non-legislative filenames. A bounded
long-input test passes. Every changed filename retains its original complete
subject and amendment fields; target references do not populate primary fields.

Source guide definitions, examples, committee references and strict schemas are
unchanged. Generated JSON and ECMAScript checks pass. The source hashes match the
comparison snapshot. This corpus is reused development evidence, not an unseen
accuracy benchmark or proof of full semantic interpretation.

The refreshed legislative residual inventory contains 10,236 filenames with
remaining text and 5,111 distinct residual strings. These are review candidates,
not counts of parsing errors: they include untyped numbers, literal local codes,
proper names and titles. Attached names such as `GrijalvaANS` still need a
separate boundary decision. The native corpus consumer is unchanged. Work
remains local and uncommitted.
