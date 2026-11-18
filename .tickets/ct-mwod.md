---
id: ct-mwod
status: closed
deps: []
links: []
created: 2026-11-18T14:19:09Z
type: bug
priority: 1
assignee: mikewolfd
tags: [model, recordings, nightly]
---
# A page saved under a host alias drops its correct video-to-meeting match

Root cause of the removed recording match that stopped the capture night of 2026-11-17 (95f4e73e859d into 2ec7ae83a852), and probably the one of 2026-11-18.

Removed: match ed3de8ff15b0, event 117471 (House Science markup of H.R. 8958, 2024-07-10) to youtube:SBp0UXikw8w, basis committee_page, source committee_page:cc092361b53d. The link is correct: the committee's own markup page embeds that video. My cause record for that night said the match was 'replaced'; it was not, it was dropped. The record stays as signed; this ticket is the correction.

Why: the meeting's title is the generic 'Markup', so model/sql/house-page-meeting-links.sql matches it only by its third rule, which needs single_url_on_date: one page address for that committee on that date. The page was held as https://republicans-science.house.gov/markups?ID=F6543C82-... (saved 2026-10-31, body cc092361). On 2026-11-17 the fetch queue stored the same page from https://science.house.gov/markups?ID=F6543C82-... (body 212ccf9b, 108 bytes smaller). Two addresses on one date, so the rule saw two pages and matched neither. Every alias the queue fetches for such a page drops one more correct match and stops that night for a cause record.

Fix: count pages, not addresses. page_key is the address without scheme, www, edit- and the party or archive prefix; the same path and query on those hosts is one page.

Evidence: public releases 95f4e73e859d and 2ec7ae83a852 (recording_matches, recordings, sources, url_state, detail), copies under .cache/archive-release/nightly-evidence/.

## Acceptance Criteria

The alias pair matches its meeting in test_explorer_native_tables; two different pages on one date still match nothing; after the fix publishes, event 117471 has its recording again.


## Notes

**2026-11-18T14:26:19Z**

2026-11-18 independent review (Opus, greybeard + etl-workflow + evolutionary-refactoring): merge after named changes; applied. page_key is now built from host_stem, so the host prefixes have one owner; the unused source_url column is gone; the flag is single_page_on_date; the test asserts one match row cited to the lower body. Checked and not accepted: 'a moved source_ref still stops a night'. A changed value on a matched key is in the data-only rule's explainable set (run 44303486024 carried 28 changed source_ref and stopped only for the removed key). Left in place, named by the review: aliases whose path or query differs; an edit-<committee> host with no party prefix; education and edworkforce as separate keys; the restored match cites the lower of the two bodies, so its source_ref moves from cc092361 to 212ccf9b.

**2026-11-18T14:39:04Z**

2026-11-18 independent root-cause analysis by Codex (gpt-6.2-astra, xhigh; greybeard + etl-workflow; briefed with the symptom only, in a clean checkout of main). Report: .cache/archive-release/investigations/removed-recording-match-20261118/codex-rca.md. It reached the same row, the same input change and the same rule on its own, and judged the removal wrong with high confidence. Added on its advice and the Opus review's: the two party sites are different publishers, so a date holding both a democrats- and a republicans- page is never one page (party_site), with a test that fails without the guard. Its claim that nine queued Science addresses with stored Republican-host twins all returned 200 on 2026-11-17 while one match disappeared is its own measurement, not re-derived here. Senate exposure split out as ct-k7j4. Its verdicts: the gate made the right call; fix the matcher's definition of a competing page; keep both saved copies.

**2026-11-18T19:13:34Z**

2026-11-18 published and read back. Release ca6e7adbfacf (live 19:10 UTC, run 44373468129) carries match ed3de8ff15b0 again: event 117471 to youtube:SBp0UXikw8w, basis committee_page, now cited to the lower of the two saved bodies (212ccf9b4a94); the recording's event_ids are [117471] again. Read from the public files, whose hashes match the published manifest. Exactly one match id left the release, the false one tracked on ct-414r. The Senate rules' same exposure is ct-k7j4.
