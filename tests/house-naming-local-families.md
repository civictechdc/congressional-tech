# Recurring local legislative components

Decision: expose repeated printed components within assigned legislative fields:
numbered CommitteePrint identifiers, mixed-case prefixes before ANS/AINS, local
AMD/AMDT/AINS/ANS numeric components, and DiscussionDraft/SubcommitteeDraft
wording. Do not expand unexplained codes such as CP, NA, BVE, SPF or MLP.

Hypothesis: these explicit boundaries add reusable metadata without changing
strict records, person identity, primary bill numbers or official version codes.
Use generic spelling/layout rules, not a surname list or individual filenames.
Local marker/number pairs remain components of the complete original identifier.

Compare the candidate against saved native/strict results in drafts-final and
the previous House extractor in filed-targets-first. Hold the 333,368-basename
inventory, source definitions and native code fixed. The pre-change inventory is
local-families-inventory.json in the comparison cache. Inspect every matching
family, including false substring candidates, and all removed or changed fields.

Include real CommitteePrint119-A and CommitteePrint2 subjects, GrijalvaANS and
GrijalvaANStoCommitteePrint, CMT-AMD_01 and D_AMDT_01, repeated local numbers and
format/filing suffixes, and drafts before/after descriptive titles. Construct
controls for EVANS/Evans, capitalization without a clear marker, AMD inside a
word, number/title runs, draft/drafter boundaries, unrelated scopes and long
invalid inputs. Do not infer a surname from the prefix or Congress from a print
identifier. Existing tests that forbid interpreting a numeric prefix as an
official amendment number remain in force; a newly recognized explicit local
component such as AINS_01 may now expose 01 separately.

Accept only if all prior useful fields remain, strict results and catalog
meanings remain unchanged, source spans are exact, and raw review supports the
new interpretations. Broad descriptions remain in residual analysis. Count new
field signatures separately from duplicate observations. Run focused tests then
one full comparison and omission audit, each bounded to 30 minutes. Retain failed
runs and source hashes. Reused corpus cases are development evidence, not an
independent accuracy estimate. No downloads.

Focused-test finding: the new local-component rule repeated existing fields for
bare ANS_02 in a filing identifier. Retain this failed run in
local-families-focused.log. The candidate now omits that added observation when
all its fields already occur with identical metadata elsewhere; it preserves the
existing whole-slot interpretation and all unique new components.
