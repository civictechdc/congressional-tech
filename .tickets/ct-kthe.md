---
id: ct-kthe
status: open
deps: [ct-h1nd]
links: [ct-j2yo, ct-x78c, ct-5w9u, ct-dx22, ct-egg6]
created: 2026-10-30T18:34:44Z
type: feature
priority: 2
assignee: mikewolfd
tags: [phase-2, senate, parsers, witnesses, etl-workflow]
---

# Find witnesses and their testimony from three Senate committee sites

Readers should be able to open the testimony a committee page assigns to a witness. The earlier Phase 2 D4 check associated 25 of 49 Intelligence testimony documents, 3 of 20 Environment documents, and none of one across 56 candidate Joint Economic Committee (JEC) pages. These counts describe that sample. The audit traced the JEC failure to the source parser and meeting match.

## Root cause (2026-11-05)

The retained June 12, 2024 JEC page “Made in America: The Boom in U.S. Manufacturing Investment” shows two separate failures.

- In `e145d24c389e`, the plain witness parser treated adjacent parts of Scott Lincicome’s title as separate people. Both anchors refer to file `D2F941B3-FF5F-4503-B354-5C8BE5D7AF3B`. The release publishes “Stiefel Trade Policy Center” as another witness with the same testimony.
- The retained page supplies the same title and date as event `335901`. The previous model mapped the JEC host to `jsec00`, while the event has `jjec00`. A separate filter excluded the event because its chamber is null. Both rules ran before the title and date checks could link the page.

The Senate reader calls `source_details_tree` directly. At the time of the audit, its appearance version omitted `witness_names.witness`, a dependency of the plain witness parser.

## Implementation and remaining checks

The first-wave merge `18049548` includes the JEC parser and meeting matcher fixes, Senate version tracking for the shared witness helper, and Intelligence open-hearing discovery. The bounded native check attached four JEC witnesses to event `335901`, including one Scott Lincicome row with the title “Vice President of General Economics and Stiefel Trade Policy Center,” Cato Institute and the exact testimony URL. The 168 focused witness and JEC checks passed, including shared-file and ambiguous meeting controls.

The independent replay check preserved all 84,610 prior appearance rows and added 44,838 completed records with exact source and digest parity. It added 35,020 MODS rows under `1775aa40` and 9,818 Senate rows under `a8b682c5`. Only the named JEC witness list changed among the Senate rows, from five entries to four. House XML and Congress.gov appearance rows matched in both directions. [Independent replay and release handoff](../docs/plans/production-mvp-follow-through-20261105.md)

Intelligence discovery found 19 eligible links in the retained listing. The exact hearing detail request returned HTTP 403. No matching `environment.senate.gov` detail body was found in the inspected retained exports. Two Environment and Public Works controls confirm that a source-assigned PDF follows its witness and that an ungrouped All Testimony PDF stays unassigned. Keep both source-detail gaps open.

After the build hold clears, the release coordinator will confirm the native import, verify the JEC hearing and exact testimony in the selected site and MCP, and check that Scott’s former key `e00bd733c3873560` follows the genuine witness while the false fragment key `c52036f0f172e6c1` has no unsupported successor.

## Acceptance Criteria

- The JEC fixture publishes one Scott Lincicome occurrence with the complete title and the source-bound testimony, and links it to `335901`. Keep genuinely distinct witnesses that share a file, and preserve ambiguity when page evidence does not resolve a meeting.
- The retained Intelligence, Environment and JEC fixtures recover witness appearances and source-bound `document_urls`. Flat or ungrouped links stay unassigned to individuals.
- Keep the extractor independent of `retention/document_links.py` internals. Account for the shared witness helper in the Senate version before carrying readings across a helper change. A Senate-only extractor edit advances its source version while the MODS, Congress.gov and House XML versions stay stable.
- Record the exact replay scope, version and resulting lake output. Keep the three-host counts tied to their measured sample.

## Coordination and evidence

The retained JEC HTML SHA-256 is `b4c3127548dbf19424641b714dfc301050797c164a8ce20e3e11d087ecc8cc0f`. [Root-cause analysis](../docs/plans/production-mvp-root-causes-20261105.md) · [Phase 2 annex, §4.2.1](../docs/plans/phase-2-annex-20261028.md)

Use the existing Senate version work and coordinate any shared helper edit with the MODS owner. The local JEC match can ship independently of explaining chamber gaps across the release. [ct-h1nd](ct-h1nd.md) · [ct-lx67](ct-lx67.md) · [ct-opy0](ct-opy0.md)

## Notes

**2026-11-05T20:18:06Z**

Integrated the JEC continuation repair, source-specific committee matching and shared-helper version tracking. All 9,818 Senate records replayed successfully; independent comparison found exactly the named JEC list changing from five rows to four, with Scott Lincicome's role and testimony URL preserved. Intelligence discovery is fixed, but its exact detail request returned 403; the exact Environment source fixture remains unavailable. These gaps and final selected-release acceptance keep the ticket open.
