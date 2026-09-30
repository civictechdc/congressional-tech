# Structured source slots: results

The reviewed parser recovers supported metadata without repairing source spelling
or guessing unknown local identifiers. The accepted evidence is in
`.cache/filename-engine-comparison-20260929/structured-slots-reviewed/`.

The full comparison covers **333,368 retained basenames**. All strict results
remain unchanged, all **2,555,451 observed source spans** are exact, and no existing
native code meaning is lost or changed. **1,278 tests pass**, including real
source examples, misleading alternatives and a bounded long-input check.

Compared with the preceding House extractor, new fields expose five sponsor
slots, 256 measure types, 240 number placeholders, 58 descriptive titles and
564 amendment identifiers. No prior raw-field signature was removed. These
counts overlap across filenames. There are 2,705 changed outputs overall;
that total also includes observation order and explanatory-text changes.

## What changed

Specific legislative payload rules now run before generic token searches. The
existing malformed-sponsor rule can refine a broad measure-list match, and its
identifier cannot become a date. Valid Bioguide-shaped tokens do not acquire a
second malformed interpretation.

- All seven actual `KOOO395` sponsor slots are now exposed; five were previously
  buried in a suffix. The spelling stays `KOOO395`, with no person-identity claim
  or silent substitution of zeros.
- A subject such as `HR__` now separates the known measure type from its literal
  missing-number marker. No bill number is invented. The source rule recognizes
  418 subjects; some appropriations subjects already exposed those fields.
- Explicit underscores separate a measure type from following descriptive text
  in 58 filenames. The corpus includes ten American Privacy Rights Act examples
  and other pipeline safety, air-quality, public-health and legislative titles.
- A numeric amendment identifier is separated from a positive terminal update:
  `Amdt-15-U15` retains amendment 15 and update 15. Leading zeros stay intact.
  Existing amendment-tree and en bloc interpretations remain available.

For 23 appropriation filenames, a generic fiscal-year observation is now
suppressed because the same fields already occur in the more specific routing
observation. The values and spans remain available. The five generic amendment
references in malformed-sponsor filenames likewise give way to the more specific
source interpretation without losing their fields.

## What direct comparison rejected

An initial broader numeric rule added 13,398 fields that only duplicated complete
numeric amendment tokens. It also interpreted a numeric prefix in four compound
local IDs, including `1068_01_xml` and `033_ANS`. These are not safe amendment-ID
splits. The reviewed rule only adds the numeric refinement before an explicit
terminal positive U update; simple and compound local IDs stay intact.

The earlier `structured-slots-final` and `structured-slots-verified` candidates
are retained with rejection notes. They are not the accepted result. The
reviewed regex also avoids adjacent digit-consuming groups: a single local
12,000-digit invalid-token check took approximately 0.97 seconds with the broad
candidate and 0.00026 seconds with the reviewed rule. This measures that regex
case, not overall parser throughput.

Source guide definitions, examples, committee references, strict naming schemas
and native parser code are unchanged. Generated JSON and existing Node schema
checks pass. Complete outputs, previous-House differences, native omission
explanations, source snapshots and validation receipts are retained.

## Remaining work

This is reused development evidence, not proof of complete interpretation. The
next raw review has 77 `ANStoCommitteePrint` subjects whose internal substitute
and target wording remains in the broad subject field. Compound local amendment
IDs also need further review; preserving them whole is preferable to an
unsupported numeric split. The native corpus consumer is unchanged. Work remains
local and uncommitted.
