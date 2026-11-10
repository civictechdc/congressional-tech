---
id: ct-uywf
status: open
deps: []
links: []
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

