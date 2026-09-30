# Source meaning fidelity

Decision: preserve useful native interpretations in House source extraction and
check meaning metadata in addition to matching code strings.

Hypothesis: source-backed collection and amendment definitions, explicit number
roles, amendment degree labels and weekly-notice date roles improve extraction
without changing literal fields, strict parse/render behavior or source catalog
content. ORH receives the Rules-resolution definition only in its explicit
ORH-Rule construction; a bare local ORH token does not establish that meaning.

Compare the unchanged native outputs in drafts-final and the previous House
outputs in recurring-gaps-final against the updated extractor on all 333,368
retained basenames. Record labels, notes, candidates and context changes, not
just code equality. Verify every context/code pair resolves to a catalog entry.
Retain source hashes, full changed outputs and raw examples for each family.

Controls: committee-vote CRPT and outer HMTG notice prefixes must not acquire a
report or meeting classification; generic amendment wording must not establish
committee consideration. Unknown amendment numbers, local tokens and possible
version-shaped word endings must retain their uncertainty. Weekly dates that
violate the Monday convention must remain readable as source values.

Acceptance: unchanged strict results and literal field signatures, preserved
source definitions/examples, valid lookup references, explained meaning changes,
and focused positive/negative tests. New definition links describe filename
conventions, not verified document contents. Bound the full comparison to the
retained corpus and 30 minutes, without network access. This is reused
development evidence, not a held-out accuracy claim.

Follow-up discovered during controls: compound-local-file can split ORH into O
and the version RH. Review compound identifier/version boundaries separately;
record this gap even if it is outside the initial metadata-only change.

Revision after semantic-fidelity-first: all 333,368 strict results and raw field
signatures passed; inspect all meaning changes separately. Extend the existing
descriptive word-ending safeguard to compound local identifiers. Test uppercase
ORH and SERIES endings, explicit separated versions and actual mixed-case/number
boundaries. All 72 compound-local-file inputs were inspected directly; only two
end in letters before their versions, and both have already supported boundaries.
Also restore the specific meaning of internal format wording (xml is not the
actual extension). Preserve the first run and its audit before this change.

Correction after semantic-fidelity-final: the word-ending check reached every
local_identifier field, including seven explicitly structured subtitle letters.
The full comparison exposed all seven regressions. Restrict the added safeguard
to compound-local-file; preserve existing subtitle grammar. Add the seven actual
names as tests. Retain this rejected candidate and audit, then qualify the
corrected parser in semantic-fidelity-verified.
