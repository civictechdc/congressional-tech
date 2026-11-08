---
id: ct-kthe
status: closed
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

- On the live release, source-assigned testimony follows its witness and flat or ungrouped links stay unassigned, shown by JEC event 335901 and the EPW Svinicki / All Testimony cases.
- The Intelligence detail page (HTTP 403) and the missing Environment page are recorded as source gaps.

## Coordination and evidence

The retained JEC HTML SHA-256 is `b4c3127548dbf19424641b714dfc301050797c164a8ce20e3e11d087ecc8cc0f`. [Root-cause analysis](../docs/plans/production-mvp-root-causes-20261105.md) · [Phase 2 annex, §4.2.1](../docs/plans/phase-2-annex-20261028.md)

Use the existing Senate version work and coordinate any shared helper edit with the MODS owner. The local JEC match can ship independently of explaining chamber gaps across the release. [ct-h1nd](ct-h1nd.md) · [ct-lx67](ct-lx67.md) · [ct-opy0](ct-opy0.md)

## Notes

**2026-11-05T20:18:06Z**

Integrated the JEC continuation repair, source-specific committee matching and shared-helper version tracking. All 9,818 Senate records replayed successfully; independent comparison found exactly the named JEC list changing from five rows to four, with Scott Lincicome's role and testimony URL preserved. Intelligence discovery is fixed, but its exact detail request returned 403; the exact Environment source fixture remains unavailable. These gaps and final selected-release acceptance keep the ticket open.

**2026-11-06T17:03:02Z**

Qualified the retained EPW positive and ungrouped controls independently from their raw hearing cards through the current lake/source adapter and actual local MCP Reader on private candidate 720c495b66d1691ee270dadb45c752f1c47d997c9fbe561dbbd039be15786b2f. Svinicki alone opens her exact source-listed PDF; all four ungrouped All Testimony witnesses remain unassigned. The same candidate keeps four JEC witnesses on 335901, Scott's complete role/PDF and genuine-key resolution, with no unsupported Stiefel successor. Three planted wrong reader results were rejected. Added two small retained hearing article excerpts and four maintained regression checks; the 50 focused checks passed (partial production-offline selection, not a full lane).

All four appearance parser versions still match the completed replay; credit the existing 9,818 Senate records and native import rather than repeating them. Rehashed the exact Intelligence 403 receipt/body; no new request or alternate route was attempted. The original environment.senate.gov positive detail remains unidentified in the inspected source inventory, so EPW controls do not close that original source gap. Ticket stays open for those two positive source fixtures and final same-release site/installed-MCP acceptance. ct-x78c retains the separate legacy occurrence audit; this patch changes no shared producer/model/reader files. See docs/measurements/senate-testimony-qualification-20261106.md and durable implementation/reviewed-non-news-20261106/ct-kthe/HANDOFF.md.

**2026-11-06T18:43:09Z**

Local EPW qualification is complete at commit 3253bab83ef5f98d5190714e7cedb135e5c41e28: Svinicki’s source-listed PDF follows her alone, and ungrouped All Testimony stays unassigned. Four new regression cases and 50 focused checks passed (partial lane). The local MCP reader passed on private candidate 720c495b for EPW and JEC, including Scott’s complete role/PDF and genuine historical key; three wrong-result plants were rejected. Independent GPT-6.1 Sol/xhigh review loaded all four requested skills and APPROVED this exact commit, confirming the existing JEC repairs address the parsing/matching causes. Evidence is in reviewed-non-news-20261106/ct-kthe/HANDOFF.md and merge-prune-20261106T180951Z/reviews/ct-kthe/REVIEW.md. These results establish local/private-candidate behavior, not live delivery.

Keep open: ct-kthe needs accessible Intelligence detail and the original Environment-host positive fixture; the exact 403 remains preserved. The four-parser equality report applies to 3253bab8, not the newer House-changing rollup; the reviewed Senate code remains unchanged, supporting reuse of its 9,818-record replay. The original root included 3253bab8 through rollup merge 09296f06 and owns the remaining main merge. ct-m104 owns final build/deployment and same-release site/installed-MCP acceptance. No further source change was required by review.

Independent review: APPROVE for the scoped work; remaining ticket acceptance is unchanged. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-kthe/REVIEW.md).

**2026-11-06T19:20:02Z**

Post-review update, November 6, 2026: independent GPT-6.1 Sol/xhigh review loaded all four requested skills and APPROVED the scoped source/evidence at 3253bab8. The EPW source-listed PDF follows Svinicki alone, while ungrouped All Testimony stays unassigned. Four new regression cases and 50 focused checks passed. A private-candidate MCP reader passed EPW/JEC cases and rejected three wrong-result plants. Review confirmed the existing parsing/matching repairs within that source scope.

The reviewed source reference is included in local main 1a5ae01c. Remaining: Accessible Intelligence detail, the original Environment-host positive fixture and final same-release site/installed-MCP acceptance. Preserve the exact 403 evidence and the revision limits on prior replay. Keep the ticket open for those acceptance criteria. This review does not establish a deployed release. [Review](../.cache/archive-release/implementation/merge-prune-20261106T180951Z/reviews/ct-kthe/REVIEW.md).

**2026-11-08T17:20:20Z**

2026-11-08 (sweep-b): A/C 1 now verified live on 630164505301: event 335901 has one active Scott Lincicome (senate_page 8a2d5ac9, full title, Cato Institute, testimony scott-jec-testimony-6.10.24-final-.pdf); the MODS row is superseded by it; old key e00bd733 maps unambiguously to 8a2d5ac9; false fragment c52036f0 has no successor and no witness row. Only A/C 2's two positive source fixtures remain (Intelligence detail 403; no environment.senate.gov positive body). Proposed for owner: accept the JEC and EPW controls as the behaviour proof and record those two as source gaps, then close.

**2026-11-08T17:33:44Z**

2026-11-08 closed on the owner-adopted acceptance criteria above (sweep B verified on live 630164505301: one active Scott Lincicome at 335901 with title and testimony PDF; old key e00bd733 maps forward; fragment c52036f0 has no successor).
