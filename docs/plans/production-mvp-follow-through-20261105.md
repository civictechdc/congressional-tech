# MVP release follow-through

All three implementation waves and the requested independent acceptance reviews are complete. Final corrections are merged into local `main` through `db1a52b8`, and the combined native inputs are verified. The full build is waiting for resource admission: its measured allowance requires at least 21 GiB free before starting. The public archive remains `e145d24c`; publication, the main push and scheduler restoration are still held.

The coordinator owns the remaining actions below. Reports and reusable outputs live under `.cache/archive-release/implementation/production-mvp-20261105T190929Z/`, outside disposable worktrees.

## Completed and verified

| Work | Result and evidence |
| --- | --- |
| Independent first-wave acceptance | All five owners delegated fresh GPT-6.1 Sol/xhigh reviewers using greybeard, ETL workflow and both semi-formal review skills. Source repairs and focused checks are complete. Candidate and live checks remain separate. See `acceptance/SUMMARY.md`. |
| Independent Wave 3 acceptance | All five owners delegated fresh Sol/xhigh children that loaded all four skills and personally executed targeted checks. Two additional failure probes exposed cross-key retry reporting and diagnostic descendant cleanup defects. Their owners repaired both; the same independent children passed the original probes and focused controls. Reviewed fixes are merged at `736e6bf7` and `db1a52b8`. The 25-body reading proof remains valid. See the third wave's `acceptance-final/child-command-audit.json`. |
| Reviewed source | Site and MCP readers preserve usable records, source dates, descriptions, nomination precision, witness identity and recording ownership. Follow-up repairs cover PDF pages, search deadlines, capture outcomes, native origins, reading versions, cleanup and nightly recovery. Producing commits remain in ancestry. |
| Historical reading refusals | The maintained proof reproduced all 25 original decisions: nine memory limits and 16 output limits. Live exact-key qualification and planner settlement passed with no changed or missing outcome. One compatibility entry is merged at `2f4a267a`; original decisions and provenance remain selected. `ct-zpbl` is closed. See `docs/measurements/historical-reading-refusals-20261105.md`. |
| Four native imports | Imported 42,551 meeting rows, 129,448 appearance rows, 4,361 playlists and 6,235 committee parents into fresh tables. All four matched their staged inputs in both directions. Original appearance rows survive verbatim; authentic IMPORT records identify the new tables. The run took 84.7 seconds at 1.017 GiB peak RSS. |
| Raw admission and ordinary append | Created the 20 exact missing objects and verified the existing Rules objects. The completed append accounts for 24,341 receipt keys, including all 12 additions, 11 stored bodies, nine meeting rows, six appearance parents with eight entries, and three committee parents with 568 entries. The 12 captures retain nine successful and three failed HTTP outcomes. Six moved heads have actual DAILY producer records. The run took 921.1 seconds at 5.25 GiB peak RSS. See `combined-release-prep/receipt-append-run/verification.json`. |
| Bounded HTML producer | The existing producer now accepts a digest-pinned body scope and current native heads, uses maintained batches and records actual append ancestry. Eleven focused checks and independent review passed at `956f7858`, merged at `1319ee3f`. Checks cover conditional reads, interruption and resume, unchanged leaf rows and original refusals. A forced process stop still requires head/ledger reconciliation before retry. |
| HTML inputs and native bindings | All 48,798 HTML metadata rows completed. The final native table equals the six staged appends in both directions, with zero duplicate keys, pending pairs or new unreadable decisions. After a catalog timeout, recovery verified the actual head and reused the retained parsed batch without rereading it. All eight table heads and producer chains passed verification; the selected pointer and 36 provenance identities are unchanged. |
| Canonical jobs | Reviewed configuration is merged at `54e9ad70`. Daily and fallback jobs use the seven qualified writer targets and four authentic imported-table anchors. The model keeps eight verified selectors, including the unchanged video selection. Video refresh and whole-archive daily HTML derivation remain opt-in. All three plan checks passed before the final source rebind. |
| Cleanup | Completed author and acceptance worktrees have been archived and pruned through `scripts/dev.py prune-worktree`. Reports, native fixtures and exact archive refs remain. The integration checkout remains active; unrelated worktrees and local research are preserved. |

## Remaining release actions

| Action | Completion check |
| --- | --- |
| Bind the final candidate | Rebind the prepared candidate to the final merged source and verify its transitive file hashes. The native selectors, terminal IMPORT anchors, DAILY head records, receipt set and provenance have already passed exact checks. Reuse them while those identities remain unchanged. |
| Build one combined archive | Freeze the final source, inputs, parser versions, runtime and provenance. Recheck whole-operation disk and memory against measured use. Run the maintained checkpoint publisher and all six invariant suites once. Compare with `e145d24c` and review actual changes. The full model has not started. |
| Account for every saved HTML key | Compare the final model's saved HTML population with completed or partial metadata and active unreadable decisions. An `unread` row is not accepted merely because the general invariant suites pass. |
| Verify the exact candidate | Site and installed MCP must agree on witnesses, dates, bill identity, descriptions, nomination activities, recording scope, captions, Rules records, publisher declarations, selected-text digests and physical PDF pages. Run the strengthened date check without its fixture mode, the existing aggregate check and the source comparisons below. |
| Publish the same release everywhere | Publish and verify the accepted archive. Build MCP 0.6.2 through its existing tag workflow, including distribution, client launch and Linux amd64 PDF checks. Publish matching MCP assets before the main push advertises them. Bind the hosted image and site to the accepted archive, then verify the immutable release ID in each reader. |
| Close tickets and finish cleanup | Close delivered acceptance criteria, preserve broader unfinished work and source gaps, and prune the integration checkout only after its outputs and checks are durable. Write release notes from accepted changes and actual gains. |
| Restore the schedule | Reconcile canonical jobs and remote main, restore the retained `ai.spicygov.archive-nightly` launch-agent configuration, and verify a genuine bounded unattended run through all five publication gates and pointer readback. |

The shared `FULL-BUILD-HOLD.json` records current write admission and schedule restoration commands. The scheduler remains disabled. Pushing `main` deploys Pages, so that push waits for release readiness.

## Candidate checks and open boundaries

- Historical witness links: check Farmer/Reese hearing keys, the July print link, Scott's real key versus the discarded fragment, Allen's two roles and three saved documents versus four raw links, and Stephen T. Ayers at event `100346`. Use `witness-identity/verify-selected-witnesses.py` with the final data directory, release ID and `--verify-allen`.
- Dates and Rules: run the identity-aware and aggregate date checks from `acceptance/dates-captions-recovery/RESULTS.json`, then `dates-captions-recovery/rules-118300/check.py` on the same candidate. The three exact-body date repairs do not establish a general rule for ambiguous print dates (`ct-cxc5`).
- Source comparison: run the full `ss-ikn9` meeting/chamber/document comparison. Its upstream comparator at `519ffb30` remains in the separate SpicyRegs checkout for explicit handoff (`ct-r4rd`, `ct-8cno`). No accepted historical roster generation exists; the current roster covers the 119th Congress.
- HTML (`ct-082q`): verify partial/unreadable pages, witness isolation, multiple captures, detail size and transfer behavior. The Indian Affairs page's native event association remains unproved.
- Witness coverage (`ct-kthe`, `ct-x78c`): Intelligence returned 403 and the exact Environment detail remains unavailable. These are source gaps. Complete legacy occurrence accounting and selected-release checks; local role preservation alone does not close them.
- Recovery (`ct-umtm`): two qualified mirror PDFs still lack complete capture evidence and final identity admission. Their older HTML records have no accepted successor. Account separately for twelve historical Wayback pairs and edition differences.
- PDFs (`ct-680z`): dependency and physical-page fixes are merged. Broader shipped-dependency triage, hard interruption of stalled decoding and final Linux amd64 acceptance remain open.
- Committee records (`ct-k2ij`): the imported 49-parent legacy addition contains 557 entries, including 362 amendments and 195 votes. Its missing HTTP status, completion and URL facts remain unknown. The final comparison determines publication gain.
- Writer retirement (`ct-5kto`): retain the small historical event map used by bookmark translation until its replacement is accepted.
- Capture reporting (`ct-4jms`): the repaired retained-state case is independently checked. A discovery-only spelling with no original retained row and the startup-summary boundary remain outside that correction; keep them explicit in scheduled acceptance.
- Nightly operation (`ct-ud0b`): focused recovery and mixed-addition tests passed. They do not establish unattended production acceptance. A kill before the producer record is written still requires reconciliation.
- Operations (`ct-4jms`, `ct-1l1h`, `ct-9lxf`): scheduled capture/storage-policy readback, header-pattern disposition, complete-operation disk admission and spill retirement remain scoped follow-ups.
- Saved HLS manifests are downloads. Archived playback remains unavailable in the site and MCP.

## Evidence map

- `acceptance/`: five owner reviews, findings, fixes and cleanup.
- `combined-release-prep/`: frozen inputs, native imports, historical-refusal qualification, ordinary append, scoped HTML production and final input bindings.
- `reader-metadata/` and `witness-identity/`: exact staged-source comparisons and independent preservation checks.
- `site-cutover/publication-prep/`: maintained checkpoint/resume preparation and candidate checks.
- `mcp-release/HANDOFF.md`: package assets, hosted deployment and live verification; apply the later acceptance corrections.
- `main-merge/`: reviewed merge records and the release-note draft.

Round-two evidence is retained in `production-mvp-round2-20261105T200638Z/`; round-three evidence is in `production-mvp-round3-20261105T205727Z/`. Both waves are complete and their owned worktrees are pruned.
