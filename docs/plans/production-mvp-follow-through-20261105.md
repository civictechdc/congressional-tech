# MVP merge and release follow-through

The release coordinator owns the actions below. Sessions hand back reviewed commits, focused results and remaining work; their follow-ups stay here until delivered or assigned to an existing ticket.

Completed first-wave source is merged into local `main` at `18049548`. This includes the site cutover, MCP 0.6.2 preparation, source-preserving date and witness repairs, document descriptions, nomination activities, recording associations, caption handling and bounded recovery fixes. The merge preserves the existing ticket and plan edits. Its source files match the verified integration tree.

The three first-wave sessions updated their 16 tickets with the merged changes, verification evidence and remaining release actions. All remain open. Their original acceptance criteria, notes and ticket metadata are preserved.

The reviewed House XML acquisition slice `81053718` is merged at `34406841`. It accepts a bounded list of exact event URLs, checks the returned XML event, and keeps failed or wrong-event attempts as failures. Both retained publisher captures passed independent identity checks. It changes no parser or schema, so the completed first-wave stages remain reusable.

The reviewed unattended-addition checks through `5d7301f9` are merged at `b28fdd7e`. Every added document and URL attempt must trace to a successful fresh raw capture. Mixed dated and undated baseline receipts remain supported, while removals and failed same-digest requests still require review. The focused run passed 108 tests. Scheduled retry and full unattended release acceptance remain unfinished.

The optional video refresh `373ebb96` is merged at `085bb61c`. It registers the existing video producer in the daily path. Two focused native controls verify that default jobs skip video, an opted-in job writes the expected record, and an unchanged rerun retains its pin with no video work. No parser, schema or job selection changed.

The retained committee staging slice `4a6b63a5` is merged at `c23891e7`. It selects 49 already-held House XML bodies with 557 amendment and vote entries while preserving their original unknown fetch facts. Independent review checked every source row and rejected corrupt or mismatched inputs. The resulting delta still needs a complete-table backfill origin before import.

**Hold:** merge completed work as it becomes ready. Wait for every implementation wave to finish before the full archive build, shared catalog changes and publication. The scheduled publisher remains disabled. Pushing `main` would deploy Pages, so the push also waits for release readiness.

## Coordinator actions

| Action | Current state and completion check |
| --- | --- |
| Merge each reviewed slice | First wave, bounded House acquisition, unattended-addition checks, optional video refresh and retained committee staging are merged. HTML review fixes, committee table composition and nightly retry remain unfinished. Merge completed slices without waiting for unrelated unfinished work. Preserve producing commits in ancestry. |
| Reconcile final source and data dependencies | At the joint freeze, compare final parser versions, schemas, source inputs and reference generation with the retained stages. Use pinned Poppler 26.06.0; the host's 26.10 binary produces a different sniff fingerprint and does not justify a replay. HTML work changes the readings bundle; reconcile missing parser pairs and unreadable decisions. Add new coverage receipts and record keys explicitly. Reuse unchanged stages. |
| Prepare missing HTML metadata once | The retained e145 detail has 48,798 distinct saved HTML bodies and no selected HTML metadata pin. Start with the held digest inventory, reconcile the final saved-body set and any compatible existing readings, and stage only missing body/parser pairs. Reconcile the 25 active reading decisions at e145's selected old bundle before changing that bundle. Preserve accepted leaf readings and qualify custody before reading the body population. |
| Load the verified meeting, witness and caption results | Prepared native import plan covers 42,551 meeting rows, 129,448 versioned appearance rows and 4,361 playlists. All 84,610 prior appearance rows survive verbatim; 44,838 new rows are complete. Check each import against its actual staged source in both directions and select its acknowledged native table. No import has run. |
| Add the Rules records without losing existing data | The prepared daily append retains the existing 6,186 committee parents and adds one parent with 31 children. It keeps both the successful meeting request and failed witness request. It needs one new body and raises the receipt set from 24,329 to 24,331 before other waves add inputs. Refresh starting heads and provenance under the writer lock. No append has run. |
| Admit reviewed coverage additions | The coverage handoff stages eight meeting records, six appearance records containing eight appearances, and two House committee records containing 537 entries. It retains two failed detail requests separately. The 49 held House XML bodies have a separate 557-entry committee stage. After final review, reconcile each key against the selected inputs and verify the event-specific attachments. No shared catalog admission has run. |
| Import a complete committee base | The 49-parent stage is append-only. Compose its verified rows with the exact 6,186-parent e145 export in the maintained backfill path, preserving the base verbatim and producing a genuine origin for the 6,235-parent result. Import that complete table before the ordinary fresh House and Rules appends. This avoids reparsing old XML and keeps the subsequent daily production chain valid. The coverage author owns this source follow-up. |
| Admit the new raw inputs once | The 49-parent retained cohort's receipt is already selected. Promote only the ten new source receipts and their exact referenced bytes into shared raw storage, creating absent objects and verifying existing ones. The two Rules receipts are already held there. Process the twelve new receipt keys together where compatible, keeping separate source comparisons. The frozen committee inputs forecast 6,238 parents and 21,110 nested records; verify final native heads before treating those counts as the selected result. |
| Activate optional daily producers | At the final freeze, configure the video, committee and playlist table targets only after qualifying their current heads and producer ancestry. Generate and import qualified recording decisions through the existing provenance path. The merged registry wiring does not activate these tables in the scheduled job. |
| Build and validate one combined archive | Recheck current disk and memory, then use the maintained publisher and its genuine checkpoint/resume path. Run all six model invariant suites, compare with the selected archive, and explain actual changes. The full build has not started. |
| Check user journeys against that exact candidate | Site and installed MCP must agree on the repaired witnesses and roles, dates, bill identity, document descriptions, nomination activities, recording scope, captions and Rules documents. Check the old Farmer/Reese hearing keys and the July print link, Scott's real historical key versus the discarded fragment, Allen's two roles and available documents, and the Stephen T. Ayers receipt-path case at event `100346`. Run the full `ss-ikn9` comparison for meeting chamber and document fields. Preserve useful pages when optional data fails. Reuse unchanged focused checks; record candidate and live results separately. |
| Publish the archive, MCP and site in order | Publish and verify the accepted archive. Use the existing tag workflow to build MCP 0.6.2 from the final source and run the distribution and client-launch checks; the earlier wheel and source archive cover only first-wave code. Bind the final hosted image and site to the accepted archive and verify the Linux amd64 saved-PDF path. Publish the matching MCP assets before pushing the site links that advertise them. Check page metadata and selected-text digests through the installed MCP, hosted service and browser on the same archive. |
| Finish tickets and cleanup | Close only delivered acceptance criteria. Keep source gaps and broader unfinished work open. Prune owned merged worktrees through `scripts/dev.py prune-worktree` after durable evidence and process checks. Preserve the historical event-ID map until its replacement is accepted. |
| Restore the schedule | After the combined source/input review and release acceptance, restore `ai.spicygov.archive-nightly` using the retained launch-agent configuration. Verify a bounded unattended run. Do not re-enable it during the all-wave hold. |

## Follow-ups that remain open

- `ct-082q`: the HTML slice remains unmerged while its author fixes the selected-pin lifecycle, partial-reading acceptance, unreadable-versus-unread state and final metadata size after capture expansion. The Indian Affairs page's native event association is also unproved; correct separation of page and event dates in both readers does not establish that link. Final checks include partial/unreadable pages, witness isolation, multiple captures, detail size and transfer behavior.
- `ct-kthe`: the Intelligence detail request returned 403, and the exact Environment source detail remains unavailable. Neither result establishes a testimony link.
- `ct-umtm`: two mirror PDFs passed document qualification but still lack complete capture evidence and final identity admission. The old HTML records retain no successor. Account separately for the twelve historical Wayback pairs, edition differences and other unresolved notices.
- `ct-cxc5`: the three exact-body date repairs do not establish a general rule for every ambiguous print date.
- `ct-680z`: the MCP PDF dependency fix is prepared; broader shipped-dependency triage and hard interruption of stalled decoding remain unfinished.
- `ct-x78c`: the two source-listed W. Ron Allen roles are preserved locally. The full legacy occurrence accounting and selected-release reader checks remain due.
- `ct-5kto`: writer retirement remains separate. Legacy bookmark translation still uses the small event map produced by historical staging; preserve it before removing that staging.
- `ct-k2ij`: the verified 49-parent stage contains 557 entries (362 amendments and 195 votes) from a legacy receipt without HTTP status, completion or URLs. The full-table composition must preserve the 6,186 existing parents and establish the import's genuine production origin. Do not attach the delta-only proof to a complete table. The final selected-input comparison determines the actual publication gain.
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
