# Extracted metadata comparison — 2026-09-29

Decision: Identify what each filename parser adds, loses, or obscures before
deciding how to use their outputs together. This comparison changes no parser.

Hypothesis: `house_naming` assigns clearer field roles on accepted names;
`congress_api.filenames` extracts additional structure and covers more names,
but overlapping substring rules can also add misleading candidates. Consistent
extra semantic detail without noise would weaken the second part.

Arms: The complete native outputs of the current internal parser (A) and House
engine (B), retained in `implemented-final/paired-outputs.jsonl.gz` under
`.cache/filename-engine-comparison-20260929/`. Check saved source hashes against
the working files before treating this as a comparison of current code.

Cases: All 333,368 recovered literal filenames/URL basenames. Compare metadata
in both directions on the 202,063 B acceptances; account for rejected names
separately, by extension. This is filename evidence, not content-verified truth.
The recovered inventory is not an exact restoration of the deleted inventory.

Held constant: Reuse frozen native outputs, original spellings and existing
scalar-field alignment. Deduplicate identical A field spans, preserve rule
provenance, and distinguish implicit B kind meanings from missing information.
Use one offline inventory pass plus bounded manual reviews; stop once every
reported difference category has counts and raw examples. No downloads or
production changes.

Decision rule: Separate equivalent values/renamed fields, clearer roles,
additional structured detail, opaque retained text, and conflicting or noisy
candidates. Count affected filenames, not duplicated overlapping captures.
Inspect all small disagreement groups and representative recurring groups.
Report unaligned fields explicitly rather than equating them with data loss.
Do not infer accuracy from scalar containment or claim an independent gold set.

## Follow-up diagnostics after the first inventory

Manual inspection found seven Senate-bill candidates crossing a witness-token
boundary into the meeting date, in addition to candidates inside Bioguide IDs.
Count this separately using the retained native field spans and B date value.
Also count the `conference-numbered` kind as a classification risk: it matches
the generic numbered House-report layout. GovInfo's CRPT help page confirms
that conference status is separate metadata. This count does not establish
how many of the 1,051 reports are actually conference reports. The reference
lookup adds no corpus documents or parser changes.
