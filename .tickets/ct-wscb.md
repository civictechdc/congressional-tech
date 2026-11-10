---
id: ct-wscb
status: in_progress
deps: []
links: [ct-4qld, ct-xyo9]
created: 2026-11-10T07:05:20Z
type: bug
priority: 1
assignee: mikewolfd
tags: [gate, release, links]
---
# Release gate does not see a live lookup key or address that answers another file

The link rule (ct-4qld) judges link keys only. On the unpublished candidate a70ebc3d1466 the six fused House Financial Services PDFs (live rows 256823, 256827, 256829, 256831, 256836, 278162) each kept 2 lookup keys (urls.parquet) and 2 addresses (sources.parquet), 12 and 12, all answering hhrg-119-ba00-20260902-sd002.pdf on row 331783. The comparison's 'documents changed for a shared key' groups counted 3 lookup keys and 4 addresses, none of them these: that check maps live rows through document pairs, so a merge hides the change. Measured 2026-11-10 in .cache/archive-release/investigations/gate-rules-20261110/outside-tickets-lookup-and-address.md (13 and 13 by the saved-file test alone; the thirteenth of each is a correct split).

## Acceptance Criteria

Every lookup key and address that the live release and the candidate both publish reaches a candidate row serving the live row's saved body or one of the live document's own files; otherwise the gate refuses and names it. A test plants the fusion and the gate refuses it. On live 630164505301: candidate a70ebc3d1466 is refused and the named keys and addresses are the fused ones; published 619db5f9e08e passes. The counts are recorded here.


## Notes

**2026-11-10T07:12:44Z**

2026-11-10 branch claude/ct-gate-rules: the link rule has two more findings, lookup_changed and address_changed (release_comparison.changed_addresses). A lookup key hashes a URL and an address is a URL, so neither names a body and the release carries none beside them. The live row does: its saved body, and the bodies its own link keys name. Rule: for every lookup key and address that both releases publish, on a live row with a saved body whose document the candidate still holds (one of its link keys is still a candidate link), at least one candidate row it reaches must serve (saved, alternate or recovery) the live saved body or a body one of the live row's link keys names. Otherwise the publish is refused, each is named in the refusal and listed in the report with its live row and file and the candidate rows and files. No cause record overrides it. Not judged here, each already its own group: a key or address the candidate dropped (keys gone, URLs gone), and a document the candidate removed (removed rows and the ledger; its address may rightly show only a newer edition). Cost: hash anti-joins over urls (642,584 rows), sources (580,383) and the 394,230 served bodies; the whole comparison still takes about 3 s.

Counts (investigations/gate-rules-20261110/wscb-real-data.md), each equal to a plain-Python recount of every live row:
- live 630164505301 to unpublished a70ebc3d1466: refused. 12 lookup keys and 12 addresses named, 2 and 2 for each of the six fused rows (256823, 256827, 256829, 256831, 256836, 278162), all answering hhrg-119-ba00-20260902-sd002.pdf on row 331783, and nothing else. Of the other rows, 13 lookup-key rows and 13 address rows keep the live file as an alternate, and 1 of each reaches another of the live document's own files (a correct split; that one is why the saved-file test alone counted 13 and 13).
- live 630164505301 to published 619db5f9e08e: passes, 0 and 0. Lookup-key rows: 642,571 same saved file, 2 live file kept as alternate or recovery, 11 another of the live document's own files. Address rows: 580,377 and 6. These are the cause review's numbers (causes-2/capture-address).
- e145d24c389e to 630164505301 (two published releases, not consecutive): 0 and 0.
Planted on a copy of the published candidate: one lookup key and one address re-pointed at another row; each is named and nothing else is.

Cannot see: which of a wrongly joined live document's files an address named (the capture table knows, the release does not), so after a split an address sent to the wrong half passes; whether a recorded alternate or recovery is the same document (ct-u9y4). Open, as for ct-4qld: a refusal here has no hand path.

**2026-11-10T07:53:59Z**

2026-11-10: after the review of ct-4qld the rule fails closed. If urls or sources lacks the columns it reads, or detail has no saved_body, link_rule.unchecked says so and the gate refuses. Re-proved on the published candidate after that change: 0 lookup keys and 0 addresses named, the 11 lookup-key rows and 6 address rows of correct splits pass (review-4qld-real-data.md, wscb-real-data.md).
