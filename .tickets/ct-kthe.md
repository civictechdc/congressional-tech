---
id: ct-kthe
status: open
deps: [ct-h1nd]
links: []
created: 2026-10-30T18:34:44Z
type: feature
priority: 2
assignee: mikewolfd
tags: [phase-2, senate, parsers, witnesses, etl-workflow]
---
# Add second-layout Senate hearing page parsers for intelligence, environment, and jec

Per the D4 measurement in `docs/plans/phase-2-annex-20261028.md` §4.2.1, after ColdFusion `[?&]download=1` normalization, three Senate committee sites still have low witness-card coverage because they use alternative HTML page layouts: `intelligence.senate.gov` (51.0%, 25/49 testimony docs), `environment.senate.gov` (15.0%, 3/20), and `jec.senate.gov` (0.0%, 0/1 across 56 candidate pages).

## Design

Owners: `packages/congress_api/src/congress_api/parsers/senate_page.py` and `packages/congress_api/src/congress_api/lake/appearance_records.py`.

1. **Decouple Phase 2 Senate witness/card extraction from unversioned Phase 1 `document_links` side effects (`etl-workflow` §4):**
   - `parsers/senate_page.py:source_details()` currently calls `retention/document_links.py:link_records()`, which is a Phase 1 crawler module not tracked in `appearance_records.current_version("senate_page")`.
   - Extract or self-contain the witness-card link binding helper in `parsers/senate_page.py` so `appearance_records` depends only on versioned Phase 2 parser files, and builds on `ct-h1nd`'s source-scoped `current_version("senate_page")` so updating `senate_page.py` never invalidates `mods` (34,559 rows), `congress_gov` (18,140 rows), or `house_xml` (3,398 rows).
2. **Inspect bounded samples of retained HTML captures:**
   - Visually inspect bounded samples of retained original HTML captures for `intelligence.senate.gov`, `environment.senate.gov`, and `jec.senate.gov` in the raw corpus.
3. **Add layout extraction rules:**
   - Add extraction rules for witness names, titles/organizations, panels, and testimony `document_urls` where the HTML structure binds each link to its witness.
   - Preserve the invariant (`DATA-MODEL` §7.2) that `witness_keys` come only from source-stated witness links (never guessed across flat ungrouped page links).
4. **Selectively replay `senate_page` in `appearance_records`:**
   - Run selective lake replay for `senate_page` (or the three target Senate hosts) without re-parsing `mods`, `congress_gov`, or `house_xml`.

## Acceptance Criteria

- `parsers/senate_page.py` witness and card-link extraction no longer depends on unversioned Phase 1 `retention/document_links.py` internals.
- Retained HTML fixtures from `intelligence.senate.gov`, `environment.senate.gov`, and `jec.senate.gov` extract witness appearances and witness-bound `document_urls`.
- Pages that list documents flat without per-witness grouping do not fabricate witness-document ownership.
- Updating `parsers/senate_page.py` advances only `appearance_records.current_version("senate_page")`, leaving `mods`, `congress_gov`, and `house_xml` parser versions untouched.
