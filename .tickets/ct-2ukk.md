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

## Notes

**2026-10-20T03:15:53Z**

Basin target is the existing congressional-tech-raw bucket. Native qualification reached lifecycle table creation but failed with catalog-side storage authentication 424/401. The isolated test prefix has zero objects; existing archive data is unchanged. A token granting Basin and storage access is required; current OAuth and existing account token do not qualify. Retained evidence: output/incremental-updates-20261019/catalog-setup/SETUP.md. Local implementation continues; no production adoption claimed.

**2026-10-20T03:24:07Z**

Credential blocker resolved. Actual raw-provider-2 source-only remote qualification passed on congressional-tech-raw: Build, correction/deletion, exact old/new nested reads, completed fresh-host retry without original inputs, and stale/conflicting request refusals. All selected S3 references are inside the isolated prefix; 110 objects / 487,980 bytes retained. Receipt: output/incremental-updates-20261019/catalog-setup/raw-provider-2/verification-receipt.json. Build 65.03 s, Update 100.72 s, completed retry 6.18 s are tiny provider timings, not throughput gains. Application adoption, race and end-to-end cost qualification remain open.
