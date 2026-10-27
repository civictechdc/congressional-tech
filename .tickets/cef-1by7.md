---
id: cef-1by7
status: closed
deps: []
links: []
created: 2026-10-27T19:51:03Z
type: task
priority: 1
assignee: mikewolfd
---
# Stage body readings through native work lists and appends

D2 local producer slice: native deduplicated body/parser/version worklist and active unreadable anti-join, ranged sniff adapter, bounded page reads and supervised parsers, raw unreadable staging, native typed output and C7 append. Live backfill stays owner gated; local duplicate/noop/version/error/size/nested link fixtures pass before review closure.


## Notes

**2026-10-27T21:41:21Z**

Local producer contract is complete: 74 focused producer/worker/page/sniff tests pass after the three CODE and ARCH concerns were fixed. Shared sniff identity now includes producer/supervisor/resources; page versions include XML helper. Atomic presence marker is inspected after stop/reap; uncertain reads remain pending. Post-decode guard uses error/decoded_size_limit. Content-hashed unreadable batch keys avoid same-run collisions. Native append/noop and local-only CLI pass. Reviews cx_d2_producer_{review,arch_review}/review.md; real full backfill/link measurements and live jobs remain plan-level work, not claimed by this local ticket.
