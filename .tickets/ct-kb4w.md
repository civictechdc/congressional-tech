---
id: ct-kb4w
status: open
deps: []
links: [ct-30fp, ct-94hw]
created: 2026-11-04T20:12:20Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-gi01
tags: [data-model, correctness, release-blocker]
---
# Witness keys break on every re-fetch: publish old-to-current key mappings before the next release

witness_key hashes [witness-occurrence-v2, occasion, source, record_sha_hex, source_locator, context_key]. Re-fetching a body with different bytes, or binding a context where there was none, gives every witness at that occasion a new key. Nightly run 8 (candidate ef4c1632 vs live e4538f00) re-keyed 35,889 Congress.gov witnesses at 8,285 meetings after 18,123 committee-meeting API URLs first fetched 2026-10-30 entered the lake; content equal apart from 79 names / 68 positions / 69 organizations. The Explorer /witness route looks up by key, so every saved or shared witness link at those meetings breaks. ct-30fp required 'unambiguous, ambiguous and unresolved old-key mappings without name-only merging'; that mapping never shipped. Evidence: .cache/archive-release/nightly/20261104T174328Z/candidate/witness-rekey.md (base and candidate releases saved alongside).

## Design

Keep witness-occurrence-v2 as defined (no one-time re-key of all 172,964). Publish a mapping from every witness key a prior record at the same occasion produced to its current key, derived inside the model from superseded appearance records still in the lake (no cross-release input). Match on occasion + source + source_locator plus agreeing non-name attributes; a name alone never maps. Ambiguous and unresolved old keys are stated as such, not guessed. The Explorer /witness route resolves through the mapping. Release schema, generated reference, fixtures and the release gate (rows re-keyed through a mapping count as explained) change together.

## Acceptance Criteria

1) The saved nightly-8 base/candidate pair: every removed congress_gov witness key with an unambiguous successor maps to it; the 10 mods rows and the remainder are classified. 2) Fixtures cover unambiguous, ambiguous (two candidates) and unresolved mappings, and a same-name-different-person case that must not map. 3) /witness/<old key> renders the current witness in apps/site contract checks. 4) Full model build peak memory within the documented limits; model invariant suites pass. 5) A rebuild of the nightly candidate leaves no unexplained witnesses groups at gate 1.

