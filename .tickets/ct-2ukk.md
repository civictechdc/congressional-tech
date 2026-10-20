---
id: ct-2ukk
status: open
deps: [ct-dat9, ct-7e7q, ct-9vtu, ct-y32m]
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

**2026-10-20T07:37:41Z**

Current input bytes retained and verified for all4core tables. Complete721-part reading scan passed491,710rows, preserving prior failed/unclassified/size-limit outcomes. Core decoded scan remains running. Native adoption is blocked by oversized selected document rows; ct-rcs8 owns preservation-safe resolution. Native production selectors remain unchanged.

**2026-10-20T08:00:34Z**

Full current table scan complete:725Parquetfiles,8623851rows,1521719517storedbytes. All core identities/references and721reading-part validations pass. Exactly one43.8MB document requires ct-rcs8 lossless occurrence normalization. Native import/readback and production selection remain pending. Complete receipts:output/incremental-updates-20261019/adoption-survey/migration-scan-inventory.md and core-compatibility-scan.json. ct-upte repeated-membership read optimization is reviewed, measured and closed; remaining affected-leaf costs remain documented.

**2026-10-20T08:26:58Z**

Final normalized-format local measurement passed at 3a03125a for 4 and 40 unrelated records. Append catalog reads are 18 in both cases versus baseline 105; logical read bytes 79,279 / 609,583 versus 1,135,041 / 8,992,328. Typed parts add native submissions (12 to 16) and metadata bytes. All unrelated values, IDs and public records preserved. Initial setup still reads alias owners repeatedly (116 / 908 native reads); assess before production import. These are fixture counters, not cloud throughput. Receipts: end-to-end/typed-occurrences/measurement-summary.json and receipt.md.

**2026-10-20T08:33:51Z**

Initial qualification alias rereads resolved by closed ct-7e7q; full fixed-change measurements preserve data, IDs, mappings and existing assets. Documented operational order: adopt catalog, pin its returned selected_identity in raw receipt v2, adopt raw, qualify retained source contributions, then ordinary updates. Keep one native workspace owner and inactive legacy writers during cutover. Production import/readback remains pending.
