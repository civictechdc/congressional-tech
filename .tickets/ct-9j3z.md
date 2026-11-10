---
id: ct-9j3z
status: open
deps: []
links: [ct-gc99, ct-ud0b]
created: 2026-11-10T07:18:55Z
type: task
priority: 1
assignee: mikewolfd
tags: [gate, release, url_state]
---
# Release gate cannot prove url_state bookkeeping from new receipts: it lacks the recheck band's meeting date and the page behind each queued link

Capture and the nightly now run unattended, and every capture night changes url_state. On 2026-11-10 (live 630164505301 to 619db5f9e08e) six value groups (attempts 4,729, last_attempt 4,729, last_status 4,526, last_outcome 4,549, last_good_at 4,218, next_attempt_at 4,739 rows) and two added-URL groups (910 attempted, 1,011 queued) each needed a hand cause, and ct-ud0b's automatic proof refuses a night that has any of them. Measured in .cache/archive-release/investigations/gate-rules-20261110/url-state-real-data.md (script scripts/gr_12_url_state.py there).

What a receipt new to the release implies, and what the gate can already see. The unattended path holds the lake captures table, the live release's receipt-key set and both url_state files. From those alone, with one line per receipt line and requested URL as url_state_lines folds them:
- attempts = live value + number of new lines: 4,729 of 4,729 changed rows.
- last_attempt = the newest new line when later than the live value, else unchanged: 4,729 of 4,729.
- last_status and last_outcome = that newest line's, else unchanged: 4,526 of 4,526 and 4,549 of 4,549.
- last_good_at = the later of the live value and the newest good new line: 4,218 of 4,218.
- added URL with attempts: attempts = its new lines and no line in a live receipt: 910 of 910.
- 4,415 of the 4,729 rows were queued in the live release (attempts 0) and got their first attempt.
The same fold reproduces attempts on every attempted URL of both releases (1,153,397 and 1,158,722, 0 differences), so the live receipt set and the fold are right.

What the gate cannot see, so nothing was implemented (a partial proof changes no night: the proof is all or nothing and these groups would remain):
1. next_attempt_at = last_attempt + the interval of the URL's recheck band. All 23 families in model/registries/recheck-intervals.json have the same three bands (7, 28, 365 days) chosen by age = attempt date minus a meeting date. That meeting date comes from the model step url_state_meeting_dates (source_addresses, source_annotation_addresses, document_members, component_meeting_links, meetings_resolved); none is a release table or a gate input. Without it the gate can tell only that the interval is one of the family's three values (true for all 4,729), not that it is the right one. 305 rows keep the live interval, which does not show the band was right to keep; 1 row with a new line moved band; 10 rows changed next_attempt_at with no new line at all (8 from 7 to 365 days, 1 from 7 to 28, 1 from 365 to 7), which by definition no receipt implies.
2. Queued links (attempts 0, 1,011 added): a queue row exists because some read page links the URL (resolved_link_targets joined to good page contexts) and scope admits it. None of the 1,011 has a capture line. The gate holds neither the readings nor the model's link tables, so it cannot name the page, let alone show the page came from a new receipt rather than from an old page read late or a scope change.

Ruled out as unsound: accepting any registry interval of the family (cannot see a wrong band); accepting the live row's interval (same); rebuilding the meeting date in the gate from sources, detail.meeting_keys and meetings (an approximation of a four-way union over model-internal tables, and a second copy of the rule).

## Acceptance Criteria

Decide and build one of: (a) the publisher passes the gate, as pinned files beside the candidate, the per-URL meeting date the schedule used (url_state_meeting_dates) and, per queued URL, the page body and address it was found on; or (b) url_state publishes the band (interval id or meeting date) so the release itself carries it. Then the automatic proof accepts a url_state row only when: attempts, last_attempt, last_status, last_outcome and last_good_at are exactly what the lines of receipts absent from the live set imply (rules above), each line confirmed in raw; next_attempt_at equals last_attempt plus the registry interval for the family and the supplied meeting date, and that meeting date is unchanged from the live build or the row stays non-automatic; nothing else on the row moved; an added queued URL is linked only from pages whose every capture line is in a new receipt. Still refused: an attempt count that falls, a last_good_at that is lost or moves without a stored line, any change with no new line (the 10 interval-only rows), a tie in time with the live value, capture_disposition, capture_reason and capture_decision_id changes, and a removed URL. Tests plant each of those. On the 2026-11-10 pair the counts above are reproduced by the gate's own code, and the decision whether ct-ud0b's rule that an attempted URL must have supplied a new document (349 of 910 do) is replaced by the bookkeeping rule is recorded.


## Notes

**2026-11-10T07:19:12Z**

2026-11-10: url_state is not the only thing that stops a capture night. By ct-ud0b's rule, additions on documents the live release already has also refuse the automatic proof, and last night had 201 such link keys, 1,038 addresses and 1,321 lookup-key rows (investigations/gate-rules-20261110/gc99-real-data.md), plus 2,953 sources rows whose link_text and listed_on were filled from newly read pages. Whether those can be traced to new receipts the same way is not measured here.
