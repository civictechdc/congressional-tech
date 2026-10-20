---
id: ct-2ukk
status: open
deps: [ct-dat9]
links: []
created: 2026-10-20T02:20:22Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-czsd
tags: [incremental, efficiency, debt]
---
# Qualify snapshot adoption and end-to-end incremental costs

Local caching or isolated speedups do not establish an incremental archive-to-browser path. Qualify the integrated result using the baseline and counters created before each lane's changes.

## Design

Adopt verified current raw/catalog snapshots through the chosen owner in resumable bounded batches; never refetch or reclassify them merely to change storage. Use the maintained publication lifecycle for eventual cutover, with one writer and retained rollback data. Do not create a second production selector.

## Acceptance Criteria

- Test no-change, append, correction/delete, state/evidence edit, group merge/split, mapping-only edit and explicit rule-upgrade sequences against a small independent semantic reference.
- Apply the same fixed change to fixtures with 1x and 10x unrelated records. Report records/bytes read, recomputed, validated, rewritten and uploaded, plus wall time and peak memory for the full path.
- Show untouched payload identities remain unchanged and no hidden global scan/rewrite remains. Report metadata and adoption costs separately; do not claim speedups from cache hits alone.
- Kill/resume adoption and processing; test fresh-host restore, competing selection and lost replies. Confirm browser behavior, review state, source fidelity and existing identities.
- If gains are absent, identify the measured bottleneck and reopen its owning ticket. No qualification claim from planned tests or local-only evidence; production qualification/cutover must be separately recorded.
- After qualified cutover, remove superseded internal update routes while preserving source files, receipts and the prior immutable generation. Optional exports/compaction cannot be required to make updates correct.
