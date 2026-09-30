# Filename parser head-to-head — 2026-09-29

Decision: Determine whether house_naming.Engine.parse can replace
congress_api.filenames.parse_filename on the actual saved filename corpus, or
whether each contributes different coverage/information.

Hypothesis: The House engine supplies explicit, validated naming records but
rejects many observed spellings or families outside the cited conventions.
The existing extractor recognizes more actual names and preserves raw spans,
but an outer-layout match can leave opaque text and is not document validation.
This is weakened if the House engine covers the same names and useful fields.

Arms: A = current congress_api.filenames.parse_filename; B = current
house_naming.Engine.parse. Both run directly, with no normalization, repair,
external member reference, user-assumption fallback, or first-match selection.
A already uses B's code vocabulary; this compares parsing behavior, not two
independent sources of truth. No implementation changes/adoption during the run.

Cases: Every distinct literal filename and variant in
output/filename-clustering/filenames.parquet. Keep non-PDF names, whitespace,
source errors, exceptions, and every candidate. Inventory rows and exact spellings
are different denominators; report both. This corpus has already informed A's
rules and is not an unseen generalization test. It has no content-verified labels.

Held constant: One interpreter/process, one deterministic full pass, alternating
which parser runs first. No network calls or document downloads. Stop at the end
of the corpus or 30 minutes. Time only parser calls; separate serialization and
assessment. Timing is one warm-process observation, not a controlled hardware
benchmark. Hash source/data before and after, and retain native paired outputs.

Measures:
- A outer-layout recognition, unparsed inner payloads, partial-only extraction,
  meaningful fields beyond extension, exact reconstruction/spans, layout collisions.
- B whole-name acceptance, candidate kinds, ambiguity, validation/render round trips.
- Both/A-only/B-only/neither recognition, by printed filename family.
- Comparable scalar fields per B candidate: present, missing, or differently
  captured in A. Integer fields compare numerically; code fields compare without
  case. Identifiers, descriptions and date strings retain their spelling. Report
  unmapped fields explicitly. Scalar agreement does not verify field relationships
  or document contents. Additional A values are retained, not silently discarded.
- B rejection reasons and a diagnostic case-insensitive lexical check using B's
  own compiler. A lexical hit is not validation and does not change either arm.
- Parser exceptions, total call time, median/p95 call time, raw review of examples.

Decision rule: Recommend replacement only if B retains A's useful coverage and
metadata without unreviewed disagreements. Otherwise identify exact useful overlap,
unique contributions and remaining gaps; do not merge or modify parsers here.
Source labels and raw examples support manual interpretation, not an accuracy rate.

## Input recovery before either arm ran

The untracked `output/` directory was deleted externally while this experiment
was being prepared; the user confirmed that deletion. The original inventory
was readable at the start (275,489 rows, 275,654 exact spellings), but is no longer
available. Rebuild from the retained document URL inventory, linked-document
associations and document-recovery receipt journals. Hash and enumerate these
inputs. Preserve all nonempty URL basenames, explicit filename fields and
Content-Disposition filenames; label origins. Report extension-bearing names
separately because a URL basename without an extension may be a page/route ID.
The rebuilt population is not claimed identical to the deleted snapshot.
Use .cache/filename-engine-comparison-20260929/inventory.parquet for this run.

## Post-run diagnostic refinement

The primary run retained 46,688 rejected PDF/XML names that match a convention
lexically with case-insensitive regex flags. Check those retained candidates for
whether the package itself can validate/render a filename differing only in case.
This is a separate diagnostic, not an additional primary arm or accepted repair.
Keep all original results unchanged. Also manually inspect all three families of
field-comparison differences rather than treating representation differences as
semantic errors. No production parser changes are authorized by this comparison.

## Complete rejection inventory — follow-up

Decision: Determine how much of House-engine rejection is spelling/formatting,
and inventory the remaining shapes without changing production parsing.
Cases: All 268,187 rejected literal inputs from the retained primary run;
report the 210,495 document-extension inputs separately from URL routes.
Hypothesis: Case changes explain one subset; separators and numeric padding
explain some additional inputs, while other layouts need additional conventions.
Arms: Original rejection; case-only candidate; case plus separator candidate;
case/separator/numeric-padding candidate; relaxed date/integer lexical diagnostic.
Use the package's template/field schemas to generate diagnostic matchers and its
own render/parse to validate candidates. Preserve free text and field order.
Changes to hyphens, underscores and whitespace count as separator changes; they
are candidate interpretations, not proof that a repair is semantically correct.
Keep all matching candidates and exact original spellings. Do not invent missing
fields, rewrite dates, remove arbitrary suffixes, or rename a document extension.
Unsupported extensions and extensionless routes get separate inventory buckets.
Held constant: Frozen primary outputs and current matching parser/catalog hashes;
one offline pass, no downloads, 20-minute bound. Keep validation errors and all
failures. Derive remaining shape groups from the existing extractor's raw fields;
these observations do not certify the House engine could never parse a variant.
Decision rule: Count only package-validated rendered candidates as formatting
successes. Record ambiguous candidates. Everything else stays a validation
failure or an unmatched shape. Report exhaustive mechanical accounting and
manual examples; do not claim manual inspection of every file or content truth.

## Authorized implementation and regression run

The user authorized implementation of the four priority fixes and two follow-ups:
case-tolerant tokens/extensions, date-first committee documents, GPO hearing
identifiers, the observed vote layout, witness collection prefixes, and committee
transcript filenames. The preceding comparisons remain historical baselines.
Rerun the same 333,368 recovered literal inputs with the updated package. Keep
the baseline inputs and outputs unchanged and use a new output directory.
Require every formerly accepted record's fields to survive (additional explicit
defaults are allowed), no new parser exceptions, and successful canonical
render/reparse for every accepted record. The prior literal render-equality
check becomes a separately counted metric because spelling differences are now
deliberately supported. Fixed-token case and declared alternative layouts may
change rendered spelling; original input and free-text identifiers must survive.
Report measured coverage rather than the projected 84%, retain ambiguity, and
inspect cases where projections fail or additional candidates appear.
