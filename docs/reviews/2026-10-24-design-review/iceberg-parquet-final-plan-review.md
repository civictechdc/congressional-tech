# Final plan review

Reviewed: plan revision 5, design revision 8 and data model revision 6 (main at `f559442c`).

## Verdict

**Ready to start, with one gap to close.** The plan implements all 37 owner decisions. Each is
traced to a step, and every earlier review finding is in place:
- week one measures with a throwaway harness;
- the bucket lock gates the big raw write;
- parity reports by cause;
- the data model's 18 invariants are the test suite.

The 11–20 week estimate is honest for one engineer given the accepted scope (decision 37).

## Findings

### 1. Hearings have no title: meeting records live outside the raw log (major)

Decision 33 groups documents by meeting ID (A9: "list every document for a hearing"). Neither
the design nor the data model gives a meeting a title, date, type or committee.
- Today those come only from `congress_meetings.jsonl.gz` and the House/Senate meeting
  inventories. `acquisition/meetings.py` writes them directly; they never pass through the raw
  writer.
- This is the same gap the parent session fixed for committees with `committee_records`.
- Without the fix, hearing pages can only show an event ID. The meeting data also isn't
  rebuildable from raw.

**Fix:**
- `acquisition/meetings.py` fetches through the raw writer (Congress.gov meeting JSON and the
  XML fallback).
- A small `meeting_records` lake table: `chamber`, `event_id long`, `congress int`, `title`,
  `meeting_date date`, `meeting_type`, `committee_keys list<string>` and `body_sha`, one row
  per meeting per API body, the latest per `(chamber, event_id)` by `(retrieved_at desc,
  body_sha)`.
- The model joins `meeting_ref` to it.

This is tens of thousands of rows. It also gives the parked committee explorer (ct-gi01) a raw
source when it's re-scoped.

### 2. F0 can't exercise every reader feature (medium)

F0 is converted from the pinned Oct 19 catalog, which has no format groups (renditions are
split), no committee names (no committee records), no meeting titles (finding 1), and old
recovery categories at best. Track A's "done when the site loads F0" would silently skip A5's
alternates, A9's hearings and committee names, and parts of A7.

**Fix:** F0 fills what the old data supports:
- meeting IDs from URLs;
- document dates from the old metadata;
- link labels from the old occurrences;
- committee names from today's `congress_committees.jsonl.gz`.

The plan should list what F0 can't show, and add a small hand-built fixture release that
covers those features (one document with PDF and XML alternates, one hearing with a title, one
of each recovery kind). The contract test runs both.

### 3. Week one is overloaded for one engineer (medium)

Week one holds P4, M1 (including 400 appends under Basin maintenance), M2 (a standalone
DataFusion harness, whose first build alone takes time), F0, C0, B14, and the start of A and
B. The two measurements gate track C's size, so they should not compete with the rest.

**Fix:**
- Week one: P4 (owner), B14 (small), then M1 and M2 only.
- F0, C0 and the start of A and B move to week two.

The total doesn't change; only the order does, and the gate stays first.

### 4. M1's fallback has no cost (low)

If M1 shows manifests growing without bound under Basin, the logs move to dated Parquet with an
`If-Match` manifest (design §13). That changes C1, C2 and D, but the plan doesn't say by how
much. Add an estimate, for example "adds 1–2 weeks to C and D", so the week-one decision has
its price attached.

### 5. Still with the owner

- **P4, the bucket lock:** the most protective step in the plan, and it gates B13.
- **Open question 1, the custom-domain path allowlist:** `r2.dev` already serves every key,
  so the WAF allowlist protects nothing. Deleting it and its tooling (`r2_edge_rules.py`,
  `apply_r2_edge_rules.py`) removes code. CORS, the immutable cache headers, CSP and the
  `?filename=` disposition rule stay.
- **Open question 2** applies only if parity finds facts held only in derived tables.

## What's right

- Raw first: the lock, the refusal matrix before the biggest write, and an R-check on every raw
  merge.
- Measure before building: M1 and M2 gate the engine work; determinism is an acceptance test.
- Build beside, switch, delete, with measured line counts, so no half-migrated state lingers.
- Every decision is traced, nothing silently dropped, and considered-not-chosen items are
  recorded so they aren't re-litigated.
- Parity by cause keeps E from becoming open-ended.

## Owner decisions (2026-10-24)

- **Finding 1:** yes. `acquisition/meetings.py` fetches through the raw writer, adding a
  `meeting_records` lake table that the model joins to `meeting_ref`. Hearing pages show the
  title, date, type and committee.
- **Open question 1:** delete the custom-domain WAF path allowlist and its tooling. Keep CORS,
  cache headers, CSP and the `?filename=` disposition rule.
