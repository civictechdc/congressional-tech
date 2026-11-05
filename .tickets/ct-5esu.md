---
id: ct-5esu
status: open
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

Owner: published lookup inputs/aliases and the reader consuming them. Add narrow supported aliases or a fallback relation while retaining existing fixed keys and exact-match behavior. Start with percent-triplet case and literal-space serialization; do not apply the complete WHATWG serializer, decode reserved separators, or replace public keys with capture normalization.

Qualify host-specific download repairs, query stripping, whitespace changes and archive expansion separately. An observed repair rule is not by itself proof of a same-document association. Use admitted good-fetch/recovery relationships when needed. Reuse retained metadata; body acquisition is not required for serialization aliases.

## Acceptance Criteria

- The 21 retained literal-space-to-%20 cases and all 1,005 failing percent-triplet-case cases find their expected document through the implemented public lookup path. Preserve all pre-existing exact lookup keys and their expected document/edition membership; identify any intentionally added result separately from exact matches.
- Keep escaped reserved characters, path case, dot segments and meaningful query values distinct with positive and negative controls. Producer and actual reader use the same alias semantics. No document/body/link identity changes or row merges arise solely from lookup aliases.
- Give every retained repaired-download, stripped-query, trailing-space and Wayback variant case a supported disposition: admitted alias with evidence, separate edition, or unsupported/no association with reason. Implement documented rules for the admitted subset; do not report all generated probes as broken URLs or missing documents. Preserve original spelling and supporting association evidence.
- For the three retained Wayback pairs, exact timestamped lookup still selects its intended archived representation; any broader fallback preserves every supported edition and its source/time distinction. No bare address silently replaces or merges the historical body.
- Extend the maintained exact-source lookup/release checks with these alias and negative controls. Verify candidate bytes with the actual reader function, then representative deployed site journeys and MCP access to the same selected lookup index. Record counts as source-occurrence/variant cases, not document gains, and measure index size and lookup cost before/after.
