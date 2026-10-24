---
id: ct-2ut4
status: closed
deps: [ct-2d3k, ct-v6ao]
links: [ct-d3un, ct-qqk2]
created: 2026-10-19T16:40:42Z
type: task
priority: 2
assignee: mikewolfd
tags: [overlap-followup]
---
# Give local recovery one event owner and derived progress

Local dispatcher journal 78-82 mutates continuation state and appends/fsyncs separate events.jsonl. Its receipts intentionally remain local, but overlapping representations still obscure which record owns uncertain-write/phase progress. Cloud remote-journal restoration does not reduce this local path automatically.

## Acceptance Criteria

- Choose an explicit local event authority with derived bounded progress/checkpoint state.
- Retain exact local uncertain-write facts, phase acceptance, failed-attempt evidence and required fsync boundaries.
- Do not require cloud artifact custody or remote durability for a deliberately local route.
- Measure local serialization/fsync work and test resume after every accepted phase and uncertain write.


## Notes

**2026-10-19T16:40:42Z**

Review evidence: scripts/dispatch_corpus_recovery_publication.py:113:run.journal. See docs/package-overlap-rescore-20261019.md for the full grade map.

**2026-10-19T16:56:07Z**

Prioritized for efficiency and architectural debt per user direction. Require measured work/resource changes and simpler ownership; preserve behavior and data. Grok/Cursor is concurrently refactoring /scripts; use this ticket as its acceptance checklist and avoid duplicate implementation. Keep open until reviewed evidence passes.

**2026-10-19T19:51:06Z**

Implemented LocalContinuation: synced events.jsonl owns local write and accepted-phase state; continuation.json is derived at explicit phase/control boundaries. Shared read-only parser supplies status, including intent newer than checkpoint and missing checkpoint. Old checkpoint-only observations explicitly stale/unknown. Bounded 128-write/four-phase comparison gives exact final states/event facts/body hashes; final pinned measurement and independent review pending. No remote custody or full catalog execution.

**2026-10-19T19:52:47Z**

Frozen implementation0c2b782; exact-source matched run-final shows 783→276 fsync, 5,493,025→511,187 serialized JSON chars, exact state/257 event facts/128 body hashes and PUT+GET counts in 3pairs. Retained scratch grows117,247→245,262B for authoritative phase snapshots; explicit256MiB history ceiling. Full affected package/dispatcher/status focused suite165 passed+7subtests33.20s. Tracked local-events report/receipt; independent review pending.

**2026-10-19T19:54:08Z**

Independent review follow-up: replace versions.clear/update with protected-key assignment only, and writes.clear/update with admitted-key delta. Regression forbids clearing/repopulating shared versions across informational/immutable/protected events and checks unrelated write identity.79passed+5subtests0.98s. Serialization/fsync/request boundaries unchanged; prior timing remains attributed to0c2b782, no rerun.

**2026-10-19T19:58:38Z**

Independent review approved 1e572d0. Integrated with selected runtime ownership at fd8eb4d; 92 local integration tests and 5 subtests passed. Same-fixture 128-write journal experiment preserves state/body hashes while fsync calls fall 783 to 276; scratch grows 117247 to 245262 bytes. Evidence: docs/experiments/efficiency-debt/local-events.md.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch standalone).
- Grades: proposal 85 → 76, work 85 → 85.
- Problem: `transition()` (`local.py:28`) copies the whole writes and versions maps on every event and every replayed event, which is O(events × writes).
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/standalone/standalone-verdicts.md:32
- Covered by: WS6 (ct-qqk2), which deletes `local.py`.
- See docs/reviews/2026-10-24-ticket-audit/README.md
