---
id: ct-5esu
status: in_progress
deps: []
links: [ct-v51p, ct-aapl, ct-tk10]
created: 2026-11-05T20:08:13Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-gi01
tags: [site, publication, url-lookup, url-audit]
---
# Find documents through supported alternate URL spellings without merging editions

A copied URL can miss an already-published document when its spelling differs from the recorded source. On e145, all 580,383 exact source occurrences resolve, but 21 browser-space cases and 1,005 of 1,006 lowercase-percent-escape cases miss. Repaired-download variants miss in 4,790 of 4,804 cases, which does not prove all repairs identify the same document.

## Root cause

`archive_format.py:_lookup_steps` and the reader's `archive.ts:lookupUrl` deliberately implement the fixed lookup spelling in data-model section 8.2. They preserve query bytes and percent-escape spelling, unlike capture `url_key`. The lookup index admits observed source/recovery/good-fetch addresses rather than generating every acquisition-equivalent address. This is additional lookup capability, not a regression in the exact-source key algorithm.

Three Wayback-unwrapping cases resolve a different saved body in the same version group. Addresses without timestamps do not identify one historical edition. ct-v51p explicitly left public lookup unchanged; its capture normalization work remains closed.

[November 5 root-cause analysis](../docs/experiments/url-normalization-revalidation-20261105/root-causes.md). The actual-reader baseline and variant cases are `.cache/archive-release/investigations/url-revalidation-20261105/{release-check.json,lookup-cases.parquet}`. Detailed controls: `.cache/archive-release/investigations/url-root-cause-20261105/etl-identity-lookup/probe-results.json`.

## Design

Owner: published lookup inputs/aliases and the reader consuming them. Add narrow supported aliases or a fallback relation while retaining existing fixed keys and exact-match behavior. Start with percent-triplet case and literal-space serialization. Keep the exact-key result set authoritative and consult aliases only after an exact miss. Use a separate fallback relation or namespace so alias collisions do not weaken the existing exact-key checks. Do not apply the complete WHATWG serializer, decode reserved separators, or replace public keys with capture normalization.

Qualify host-specific download repairs, query stripping, whitespace changes and archive expansion separately. An observed repair rule is not by itself proof of a same-document association. Use admitted good-fetch/recovery relationships when needed. Reuse retained metadata; body acquisition is not required for serialization aliases.

## Acceptance Criteria

- The 21 retained literal-space-to-%20 cases and all 1,005 failing percent-triplet-case cases find their expected document through the implemented public lookup path. Preserve all pre-existing exact lookup keys and their expected document/edition membership; identify any intentionally added result separately from exact matches.
- Include a two-edition control where supported alias spellings converge but the exact URLs identify different saved rows. Exact lookup must preserve its original result set, and fallback must retain every admitted edition rather than choose or merge one.
- Keep escaped reserved characters, path case, dot segments and meaningful query values distinct with positive and negative controls. Producer and actual reader use the same alias semantics. No document/body/link identity changes or row merges arise solely from lookup aliases.
- Give every retained repaired-download, stripped-query, trailing-space and Wayback variant case a supported disposition: admitted alias with evidence, separate edition, or unsupported/no association with reason. Implement documented rules for the admitted subset; do not report all generated probes as broken URLs or missing documents. Preserve original spelling and supporting association evidence.
- For the three retained Wayback pairs, exact timestamped lookup still selects its intended archived representation; any broader fallback preserves every supported edition and its source/time distinction. No bare address silently replaces or merges the historical body.
- Extend the maintained exact-source lookup/release checks with these alias and negative controls. Verify candidate bytes with the actual reader function, then representative deployed site journeys and MCP access to the same selected lookup index. Record counts as source-occurrence/variant cases, not document gains, and measure index size and lookup cost before/after.

[Final root-cause review](../docs/plans/production-mvp-root-causes-round4-20261105.md).

## Notes

**2026-11-05T20:56:46Z**

Final root-cause review: preserve the exact-key result set, use aliases only after an exact miss, and add a two-edition collision control. No document identity merges.

**2026-11-06T18:43:10Z**

Local implementation is complete in 8f8ea78602fff18c0bc73c5c7a3165a640b163c3: exact lookup results remain authoritative, and serialization fallback preserves every admitted edition. The retained candidate resolves all 1,005 percent-case and 21 literal-space misses while preserving 611,729 exact index pairs; index size increases 3.03%. Validation passed 32 focused Python tests, 32 Node tests and 16 additional representative SQL checks bound to stable document links/body hashes. The latter are local SQL checks, not live MCP acceptance. Evidence and release-owner inputs are under .cache/archive-release/implementation/reviewed-non-news-20261106/ct-5esu/. The earlier 17-versus-23 reader-fixture issue now has a qualified ct-m104 repair (fixture-reader-02: four reader tests passed), so it is no longer an unresolved independent task.

Remaining: original root 01a1aa05-d4d2-7ca0-b541-a8a52e6c794f owns the consolidated source/main rollup; ct-m104 (01a1b1b0-7f7b-7b50-8b00-6f5a05eed772) owns the final selected index, including recovery/good-fetch aliases, and deployed site/MCP acceptance against that same index. Keep in_progress until those release criteria pass; local completion is not live delivery. The reviewed source commit is unchanged.

Independent review is in progress. No final review approval or completed release acceptance is claimed.
