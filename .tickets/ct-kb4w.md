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


## Notes

**2026-11-05T00:53:22Z**

Branch witness-key-map (worktree .claude/worktrees/witness-key-map), head ce732727, not merged. Design: witness-occurrence-v2 unchanged; new release file witness_key_map.parquet (old_key, witness_key, status unambiguous|ambiguous|unresolved, basis occurrence|content|locator, candidate_keys) built in-model from superseded appearance records (steps witness_key_priors, witness_key_current, witness_key_map). Tiers: occurrence (record_sha+locator), content (occasion+source+package+signature+repeat rank), locator (agreeing non-name attributes, compatible person); name alone never maps. Saved pair e4538f00 -> rebuild (witness keys identical to ef4c1632): all 35,899 removed keys map unambiguously to a published successor (congress_gov 35,889; mods 10 via occurrence, package:CHRG-119hhrg61764/63968/64154 occasions now bound to meetings 118019/119026/119142); 0 ambiguous, 0 unresolved. The ticket's 79 name/68 position/69 org diffs were locator pairing: Congress.gov reordered lists at 13 meetings (78 rows, matched by content); one real edit (Mr.->Ms. Jennifer Manner). Whole map: 154,089 rows; unambiguous 153,659, ambiguous 424 (mods prints bound to 2+ meetings), unresolved 6 (house_xml). Gate 1 witness residue after the map: witnesses added 16 (Congress.gov lists more witnesses at meetings 117761/117973/119049), display_order 78, name 1, occasion/event_id/superseded_by 10 (mods), list/detail witness_keys 47 (documents of those meetings gain one), witness_key_map file added; each has an entry in .cache/archive-release/investigations/witness-key-map-20261104/runs/build-1/gate1-witness-causes.json with pinned evidence -> 0 witness reasons left. Full build peak 9.68 GiB RSS (watchdog), invariant suites passed. Lanes: production-offline (full lane): exit 0 at ce732727; native-loopback (full lane): exit 0 at 064865ca.

**2026-11-05T01:37:47Z**

Parent review follow-up (witness-key-map head 012251d5). The ArchiveExplorer failure in review came from the harness: without routeArchiveOrigin the built site reads the public origin, so the page showed live e4538f00 (355,608 documents / 172,948 witnesses), where 58f40c03ddf48488 is still a live witness and 0239f68c4b6da262 is unknown. Routed to build-1 (34e4dbd9...), the redirect note and URL replacement, ambiguous candidate links and the unresolved notice all work; no UI change. Added apps/site/scripts/archive-witness-browser.mjs (npm test:archive-witness-browser): current, redirected, ambiguous and unresolved keys in the built site, and it refuses a page that read any other release. verify-archive-contract.py runs it on a copy of the committed contract release extended by archive_fixture.add_witness_key_map (shared with test_archive_reader). Planted the reported behaviour (Workspace drops redirected_from/retired): the check fails waiting for the redirect note. Unrouted run fails the release assertion (actual e4538f00). contract:archive-ci passes (contract, saved, heap, witness). production-offline (full lane): exit 0 at 012251d5. Evidence and screenshots: .cache/archive-release/investigations/witness-key-map-20261104/browser/.
