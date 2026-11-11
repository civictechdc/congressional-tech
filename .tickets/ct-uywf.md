---
id: ct-uywf
status: open
deps: []
links: [ct-rhqw]
created: 2026-11-10T19:31:06Z
type: bug
priority: 1
assignee: mikewolfd
tags: [model, witnesses, gate, nightly]
---
# A Congress.gov meeting re-fetch re-keys every witness on the record, so witness_key_map changes on any night meetings are re-fetched

Seen in two releases with no parser change behind it. Release 619db5f9e08e (2026-11-10): witness_key_map 'changed basis' on 99 matched keys, because receipt run 20261108T190655Z-99156488897a re-fetched 17 Congress.gov meeting records; every witness on a re-fetched record was re-keyed (basis occurrence to content, same successor), 77 of the 99 on records whose witnesses were otherwise identical, and 5 records listed the same people in a new order (22 display_order changes). Evidence: .cache/archive-release/release-20261110/causes-2/witness/11-witness-key-map-basis.json and 06-congress-gov-reread.json; independent review in causes/review-C/. The next candidate (77673bfb8fcf, same day) shows the same group again, 37 keys and 4 added witnesses, after the 14:02Z meetings relist wrote 38 meeting receipts; that attribution is being confirmed for its cause record. Cost: the key map grows with history, and the release gate sees a difference group on every night meetings are re-fetched, which an unattended nightly cannot pass without a hand-written cause.

## Acceptance Criteria

Either a witness's key and basis are stable across a re-fetch that does not change that witness (keyed on content from the first read), with a test on a re-fetched record whose witnesses are unchanged; or the gate gives this group an automatic cause that it proves row by row (same successor, record re-fetched in receipts newer than the live release). A release comparison after a meetings re-fetch with no witness change shows no unexplained witness_key_map group.


## Notes

**2026-11-10T19:32:03Z**

2026-11-10 (session congress-1): the attribution for candidate 77673bfb8fcf is confirmed in both directions by the release's record drafter (.cache/archive-release/release-20261110b/causes/evidence/77673bfb8fcf/witness_reread.json, script rc2_witness_reread.py beside it). Today's meetings relist stored 24 Congress.gov details (35 requested). Every live Congress.gov witness on a re-fetched meeting is re-keyed and its old key is in the group (37 of 37); every key in the group sits on a re-fetched meeting (37 of 37, none elsewhere); each live successor maps by content to the new key (37 of 37); each re-keyed row is equal on all 16 content columns and differs only in record_sha and the other columns the key hashes. Eight meetings: 118340 (4), 118922 (8), 119128 (3), 119309 (5), 119520 (4), 119543 (4), 119558 (4), 119592 (5). The 4 added witnesses are all on meeting 119590, re-fetched the same day. No other witness key leaves. So the description's 'being confirmed' is now fact, and the fix has a precise target: the key hashes record_sha, which changes on every re-fetch of an unchanged record.

**2026-11-10T20:38:46Z**

2026-11-10 seen again in release 77673bfb8fcf after the 11-10 meetings relist (38 receipts). Checked on published release 77673bfb8fcf (2026-11-10T20:27:52Z) against 619db5f9e08e with DuckDB on the published tables. witness_key_map: 37 matched old keys changed basis, all 37 now map to a different witness_key; 78 new rows. The cause record explains it by hand under ct-uywf. Every relist night will need the same until this lands.
