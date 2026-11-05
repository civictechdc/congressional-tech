# MVP merge and release follow-through

The release coordinator owns the actions below. Sessions hand back reviewed commits, focused results and remaining work; their follow-ups stay here until delivered or assigned to an existing ticket.

Completed first-wave source is merged into local `main` at `18049548`. This includes the site cutover, MCP 0.6.2 preparation, source-preserving date and witness repairs, document descriptions, nomination activities, recording associations, caption handling and bounded recovery fixes. The merge preserves the existing ticket and plan edits. Its source files match the verified integration tree.

The three first-wave sessions updated their 16 tickets with the merged changes, verification evidence and remaining release actions. All remain open. Their original acceptance criteria, notes and ticket metadata are preserved.

The reviewed House XML acquisition slice `81053718` is merged at `34406841`. It accepts a bounded list of exact event URLs, checks the returned XML event, and keeps failed or wrong-event attempts as failures. Both retained publisher captures passed independent identity checks. It changes no parser or schema, so the completed first-wave stages remain reusable.

The reviewed unattended-addition checks through `5d7301f9` are merged at `b28fdd7e`. Every added document and URL attempt must trace to a successful fresh raw capture. Mixed dated and undated baseline receipts remain supported, while removals and failed same-digest requests still require review. The focused run passed 108 tests. Scheduled retry and full unattended release acceptance remain unfinished.

**Hold:** merge completed work as it becomes ready. Wait for every implementation wave to finish before the full archive build, shared catalog changes and publication. The scheduled publisher remains disabled. Pushing `main` would deploy Pages, so the push also waits for release readiness.

## Coordinator actions

| Action | Current state and completion check |
| --- | --- |
| Merge each reviewed slice | First wave, bounded House acquisition and unattended-addition checks are merged. Remaining HTML, coverage and nightly retry work stays with its sessions until reviewed. Merge completed slices without waiting for unrelated unfinished work. Preserve producing commits in ancestry. |
| Reconcile final source and data dependencies | At the joint freeze, compare final parser versions, schemas, source inputs and reference generation with the retained stages. HTML work may change readings and bundle versions; reconcile missing parser pairs and unreadable decisions. Add any new coverage receipts or record keys explicitly. Reuse unchanged stages. |
| Load the verified meeting, witness and caption results | Prepared native import plan covers 42,551 meeting rows, 129,448 versioned appearance rows and 4,361 playlists. All 84,610 prior appearance rows survive verbatim; 44,838 new rows are complete. Check each import against its actual staged source in both directions and select its acknowledged native table. No import has run. |
| Add the Rules records without losing existing data | The prepared daily append retains the existing 6,186 committee parents and adds one parent with 31 children. It keeps both the successful meeting request and failed witness request. It needs one new body and raises the receipt set from 24,329 to 24,331 before other waves add inputs. Refresh starting heads and provenance under the writer lock. No append has run. |
| Admit reviewed coverage additions | House events 117955 and 118261 have verified local captures. The coverage session is qualifying six Congress.gov detail successes and retaining two 404 results separately. It is also preparing an explicit retained-file stage for 49 existing House XML bodies. After review, reconcile each new key against the final selected input, preserve existing rows, and check each event's nested attachments in the candidate. Reuse held bytes. No shared catalog admission has run. |
| Build and validate one combined archive | Recheck current disk and memory, then use the maintained publisher and its genuine checkpoint/resume path. Run all six model invariant suites, compare with the selected archive, and explain actual changes. The full build has not started. |
| Check user journeys against that exact candidate | Site and installed MCP must agree on the repaired witnesses and roles, dates, bill identity, document descriptions, nomination activities, recording scope, captions and Rules documents. Check the old Farmer/Reese hearing keys and the July print link, Scott's real historical key versus the discarded fragment, Allen's two roles and available documents, and the Stephen T. Ayers receipt-path case at event `100346`. Run the full `ss-ikn9` comparison for meeting chamber and document fields. Preserve useful pages when optional data fails. Reuse unchanged focused checks; record candidate and live results separately. |
| Publish the archive, MCP and site in order | Publish and verify the accepted archive. Bind the hosted service to it, regenerate configuration and check the final Linux amd64 image and saved-PDF path. Publish MCP 0.6.2 assets before pushing the site links that advertise them. Deploy and verify the live site and MCP against the same archive. |
| Finish tickets and cleanup | Close only delivered acceptance criteria. Keep source gaps and broader unfinished work open. Prune owned merged worktrees through `scripts/dev.py prune-worktree` after durable evidence and process checks. Preserve the historical event-ID map until its replacement is accepted. |
| Restore the schedule | After the combined source/input review and release acceptance, restore `ai.spicygov.archive-nightly` using the retained launch-agent configuration. Verify a bounded unattended run. Do not re-enable it during the all-wave hold. |

## Follow-ups that remain open

- `ct-kthe`: the Intelligence detail request returned 403, and the exact Environment source detail remains unavailable. Neither result establishes a testimony link.
- `ct-umtm`: two mirror PDFs passed document qualification but still lack complete capture evidence and final identity admission. The old HTML records retain no successor. Account separately for the twelve historical Wayback pairs, edition differences and other unresolved notices.
- `ct-cxc5`: the three exact-body date repairs do not establish a general rule for every ambiguous print date.
- `ct-680z`: the MCP PDF dependency fix is prepared; broader shipped-dependency triage and hard interruption of stalled decoding remain unfinished.
- `ct-x78c`: the two source-listed W. Ron Allen roles are preserved locally. The full legacy occurrence accounting and selected-release reader checks remain due.
- `ct-5kto`: writer retirement remains separate. Legacy bookmark translation still uses the small event map produced by historical staging; preserve it before removing that staging.
- `ct-k2ij`: 49 held House XML bodies contain 557 active source links (362 amendments and 195 votes) but come from a legacy receipt without HTTP status, completion or URLs. The coverage session owns a separate reviewed retained-file stage using the existing parser and preserving those unknown fetch facts. Do not refetch the bodies or invent successful fetch metadata. The final selected-input comparison determines the actual publication gain; the source count alone does not.
- `ct-r4rd` and `ct-8cno`: the upstream meeting comparator and historical roster availability remain with the coverage session until handoff. No accepted historical roster generation has been established.
- `ct-ud0b`: complete the separate scheduled retry work, interruption/resume checks, and a genuine additions-only scheduled run through all five publication gates and pointer readback after the hold. Passing the focused comparison tests is not that production acceptance.

## Retained work

Local evidence lives under `.cache/archive-release/implementation/production-mvp-20261105T190929Z/`; it is deliberately outside disposable worktrees and Git. `INTEGRATION.md` and `coordination.json` record the first-wave state. Key handoffs are:

- `reader-metadata/integration-meeting-appearance.verification.json` and `integration-playlist.verification.json`: exact staged rows and producing commits.
- `witness-identity/appearance-replay-independent.json` and `ct-x78c-root-review.json`: independent source and preservation checks.
- `witness-identity/verify-selected-witnesses.py`: run against the final installed MCP with exact `--data-dir`, `--release-id` and `--verify-allen`. Its e145 baseline is `selected-witnesses-baseline-allen.json`; the raw fixture has four Allen links, while that archive carries three documents.
- `dates-captions-recovery/rules-118300/daily-review/REVIEW.md`: bounded Rules append and exact inputs.
- `site-cutover/publication-prep/README.md`: prepare one combined candidate and resume the maintained publisher.
- `mcp-release/HANDOFF.md`: package publication, hosted deployment and live checks.
- `main-merge/after.json`: first-wave merge and preservation of pre-existing local edits.

The shared `.cache/archive-release/implementation/FULL-BUILD-HOLD.json` records the active hold and schedule restoration commands. Second-wave readiness is owned by its coordinator under `production-mvp-round2-20261105T200638Z/` until each slice is handed back here.

The second wave's `reviewed-slices.json` records accepted source slices. `source-coverage/STATUS.md`, `house-probes/result.json` and `meeting-probes/raw/` retain the House capture checks and remaining coverage boundaries.
