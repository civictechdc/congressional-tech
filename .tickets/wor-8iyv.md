---
id: wor-8iyv
status: closed
deps: []
links: []
created: 2026-10-29T12:02:52Z
type: task
priority: 1
assignee: mikewolfd
---
# Compact retained body URLs before capture-source hash joins

The exact model6 capture_sources probe attributes the dominant charged build allocation to inline body-URL DISTINCT buffers. Materialize its unchanged single-column result through existing native portable conversion before the capture hash join. Three narrow joins remain in capture_sources; serializing all three is not required. Preserve source identities, normalized URL aliases, receipt provenance, all admission guards and every existing wide/byte-parity assertion. This minimum correction follows the revised lead decision at 20261029T121132Z, codex-coord/mailbox/engine/done/20261029T121132Z-lead-attribution-ack-pr147.md.

## Acceptance Criteria

Fixture-first native reference/body/ambiguity/no-match/filename-negative and wide regression preserve semantics. Native EXPLAIN shows a persisted source_url-only body lookup and no inline aggregate in the capture hash plan; controlled native allocation metrics prove its buffers compact before the hash build. The maintained lifetime graph releases the lookup after its actual last consumer. Focused official runner checks and one review pass. Lead alone launches modelv7 with the same exact pins/native34GiB64GiB/outer24GiB after approval and normal merge; full-corpus fit remains an acceptance gate.


## Notes

**2026-10-29T12:15:08Z**

Attribution completed on exact model6 pins: inline distinct body-URL build9.73B rounded charged bytes; URL-key268.9M, target163.6M. Probe389.8315s/12294449616B physical; attribution-only lower retained baseline. Pinned0cb materialization already runs portable_stream logical-value compaction. Fixture-first body-urls-red-v1 confirms missing retained-step/lifetime boundary and native inline194.8M build bytes for196608 generated512-byte URLs; expected compact build<128MiB. Outer21.124s/772541152B physical. No implementation, primary edit, new env or corpus retry before this fixture commit.

**2026-10-29T12:28:32Z**

ONE review FINAL APPROVE product87ab39adddafa43a46e3f36f12bb61fbffa8f9d8, no blocker/concern; certificate cx_body_urls_review/review.md SHA25654a09455175ec7c786c95ec076931acd90213a87392ecd68a807af71da3783ce. Final official6+63PASS, native194.8M->105.9M charged build gauge on fixed196608 keys, no inline aggregate and exact source_url-only persisted lookup. Native149-step last-reader graph and unchanged four leaves/combined0bef/filenamee8 pass. Clarified the stale serialization wording in place per revised lead20261029T121132Z: three narrow capture joins remain; materialize/compact only the measured dominant DISTINCT first. No product change after87ab39ad. Ticket stays open for lead modelv7 same-pin/same-limit corpus acceptance after normal merge; local measured fixture and review evidence do not claim full-corpus fit.

**2026-10-30T14:32:57Z**

Completed body URL compaction and recording intermediate relation retirement (16ce6cc0) in main.
