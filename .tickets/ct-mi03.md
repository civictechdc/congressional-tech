---
id: ct-mi03
status: open
deps: []
links: [ct-2ukk, ct-czsd, ct-tuez, ct-ur2y, ct-r60e, ct-gfv8, ct-13g5, ct-ur7v, ct-nmjc, ct-a3le, ct-8ax6, ct-xu1o, ct-oc2g, ct-dzyf, ct-aia9, ct-sb0s, ct-te1p, ct-13cn, ct-n6lj, ct-dmca, ct-8kl2, ct-gziq, ct-gi01, ct-2yl5, ct-bwac, ct-uov2]
created: 2026-10-20T18:24:28Z
type: epic
priority: 1
assignee: mikewolfd
tags: [docspec, efficiency, debt]
---
# Reuse DocSpec execution and recovery instead of duplicating it

Reduce import staging, process and read-copy overhead while preserving source values, document identities, mappings, reviews and coherent application selection. Keep primary UI edits isolated. Local qualification and production adoption remain separate.

## Design & Ownership Contract

- **Native authority (`docspec-rs`)**: Owns admission, typed dataset versions, completion receipts, concurrency, and recovery. All five native worktrees are unified on `docspec-rs` `main` (`298053b`) and pushed to `Formspec-Labs/docspec-rs`.
- **Application authority (`congressional-tech`)**: Owns candidate identity, bounded typed preparation (`ct-adu0`), combined filesystem capacity preflight (`ct-n7la`), persistent loopback HTTP custody (`ct-q968`, `ct-copj`, `ct-bt1q`, `ct-3faj`), and coherent multi-table snapshot selection.
- **Transport authority (`docspec-client`)**: Neutral workspace package owning process custody, readiness, deadlines, streaming and producer-input retention. Both `congress_api` and `news_lake` depend on it; neither domain package imports the other.
- **Evolutionary-refactoring guardrails**:
  1. Do not freeze or adopt a new `docspec-rs` binary (`ct-oxg6`) until the two P1 regressions introduced on `docspec-rs` `main` (`715a8c2`) are repaired: recursive nested export schema sanitization + primitive-leaf footer admission (`ct-3li2`) and restoring caller-bounded row-group sizing in `src/engine/write.rs` (`ct-cpio`).
  2. Retain unknown-outcome producer inputs whenever native worker state is indeterminate, including HTTP 422 `"worker"` / quarantine failures (`ct-3faj`).
  3. Commit and integrate the DuckDB external-sort (`ordered.parquet`) sequential-reader fix for `ct-adu0` from `docspec-typed-preparation` into `docspec-reuse-integration`.
  4. Consolidate remote R2 field-group capability checks (`ct-3180`, `ct-13cn`, `ct-dmca`, `ct-sb0s`, `ct-gziq`) behind one `Engine` boundary rather than scattering `group != "source"` checks across CLI, HTTP, export, and change-stream entry points.

## Acceptance Criteria

Measured before/after evidence, failure-path tests and independent review for each implemented child. Merge reviewed work and retain evidence before cleanup. Features without R2 support remain explicit dependent work; no unsupported operation is silently enabled.

## Notes

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit validated the epic architecture (grade B+ conditional) and unified `docspec-rs` onto `main` (`298053b`). Updated all child tickets to track: (1) P1 fixes required in `docspec-rs` before `ct-oxg6` binary freeze (`ct-3li2` at `src/engine/export.rs:639-641,864-930`; `ct-cpio` at `src/engine/write.rs:429-456` and `src/engine/export.rs:588-605`), (2) P2 producer-input retention on HTTP 422 `"worker"` errors (`ct-3faj` at `docspec.py:233-238` and `src/engine/http.rs:442-454`), (3) committing and integrating the uncommitted `ordered.parquet` sequential-reader fix in `docspec-typed-preparation` (`ct-adu0`), and (4) tracking `ct-wjce` in the central ticket set.

**2026-10-20T22:19:32Z**

Current application plan: docs/plans/docspec-application-adoption-20261020.md. Eight new congressional-tech adoption tickets cover the shared client, cumulative news append, bounded upsert, coherent news releases, typed/incremental news views, policy-safe exports, runtime distribution and preparation spill qualification. Existing feature tickets now own application integration only. Engine upgrades are an upstream planning assumption, not observed deployment; actual9661026 local/R2 gaps are recorded. Different operations per consumer are appropriate; transport/custody/schema conversion have one owner. No implementation or production changes in this planning pass.

**2026-10-20T23:32:30Z**

Evolutionary-refactoring / Iceberg / Parquet / query-plan audit of `docs/plans/docspec-application-adoption-20261020.md` after `main` merge (`8221566d`, commits `6cd80b0e`, `936ff845`, `33ce7877`):
1. Created `ct-5fkx` (P1 bug) to resolve the multi-poll `UpdateSpec` / `GenerationSeal` contract mismatch (`docspec_backend.py:924-925` passes `spec['relationship']`, which `docspec-rs` `UpdateSpec` at `src/model.rs:875-883` and `src/engine/inputs.rs:48-74,515-528` ignores, breaking `seal_generation` on Poll 2).
2. Reopened prematurely closed `ct-egpe`, `ct-qkvr`, `ct-nloa`, `ct-csyg`, `ct-jo8n`, `ct-gf8i`, `ct-4nyy`, and `ct-nc7l` with exact `path:line` evidence for remaining gaps: duplicate client in `docspec_backend.py:394-936`, missing `update_table` / `deletions.parquet` custody in `docspec.py:398-420`, full-table `read_arrow` materialization in `_existing_by_ids` (`docspec_backend.py:980-997`), $O(\text{files})$ unpruned key-probe scans in `docspec-rs/src/engine/write.rs:606-659`, and zero non-test callers in `packages/news_lake`.
3. Confirmed `ct-oxg6`, `ct-ugqq`, `ct-ccy4`, `ct-qdkd`, `ct-a70m`, `ct-3li2`, `ct-cpio` implementations on `main` (`6cd80b0e` / `docspec-rs` `22a804e1`).

**2026-10-20T23:53:21Z**

CS 300 Grade at 8221566d — Spec: A- | Impl: B (In Progress). Added 6 focused remediation tickets (ct-xq1y, ct-m9td, ct-gfv8, ct-q05l, ct-f11a, ct-n6lj) alongside ct-5fkx and reopened premature news/pruning closures so every CS 300 deduction has an explicit owner.

**2026-10-21T00:31:41Z**

Architecture correction (2026-10-21): the shared DocSpec transport now lives in the neutral workspace package packages/docspec_client (docspec-client). news-lake depends on docspec-client, not congress-api; congress_api.retention.docspec and .docspec_host are compatibility shims. This preserves domain separation while giving transport, readiness, deadlines, streaming and producer custody one owner. Implemented and locally verified: ct-xq1y, ct-m9td, ct-gfv8, ct-q05l, ct-5fkx, ct-f11a. Still open: ct-egpe measurement/re-qualification, ct-csyg pruning, ct-nloa/ct-qkvr full-history reads, ct-n6lj incremental bridges, ct-jo8n production caller wiring, ct-gf8i/ct-4nyy caller qualification, ct-nc7l runtime gate.

**2026-10-21T07:28:00Z**

Reconciled on `main` (`55ba3479`) after `ab68f546` and `e9431d68`: 42 of 43 child tickets are now closed and verified across local Python and Node suites (`ct-egpe`, `ct-csyg`, `ct-nloa`, `ct-qkvr`, `ct-n6lj`, `ct-jo8n`, `ct-gf8i`, `ct-4nyy`, `ct-13cn`, `ct-dmca`, `ct-gziq`, `ct-sb0s`, `ct-nc7l`). Repaired the `8221566d` merge regression, added `docspec_client` to `SelectedRuntime.PACKAGES` (`dispatch_corpus_recovery_publication.py`), and retired legacy full-table Parquet writers (`ct-dat9`). Only `ct-3180`'s isolated R2 remote comparison receipt remains `in_progress`.

**2026-10-21T11:48:00Z**

All 43 of 43 child tickets of `ct-mi03` are now closed and verified following the isolated R2 provider qualification receipt for `ct-3180` (`output/docspec-reuse-20261020/ct-3180-r2-qualification/verification-receipt.json`) and extraction of `viewer_publication.filename_viewer` into `packages/viewer_publication/src/viewer_publication/filename_viewer.py` (eliminating production `importlib` coupling to `docs/youtube-coverage/research/scripts/view_document_filenames.py`).

**2026-10-21T15:21:41Z**

Independent CS300 professor audit (fresh-context subagent, 2026-10-21) graded the 42 closed children: Spec A overall, Impl A- overall. All previously flagged P1/P2 defects verified fixed. Four re-validated findings ticketed: ct-9few (ChangeDescriptor field-name mismatch), ct-dzyf (abandon_cycle DocSpecLake compatibility), ct-x0nk (transport hygiene), and reopened ct-n6lj/ct-13cn/ct-gziq/ct-dmca/ct-sb0s for remaining production-consumer/delta-derivation scope.

## Audit 2026-10-24

- Verdict: PARTIAL (batch mi03b).
- Grades: proposal 80 → 72, work 73 → 73.
- Problem: The epic's acceptance criterion asks for "measured before/after evidence ... for each implemented child", but lcbc, wmtx, wjce, nc7l, nloa/qkvr (1/8/32 polls) and vt7i have no recorded measurements.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/mi03b/mi03b-verdicts.md:15
- Status: Reopened, because this audit reopened its children ct-jo8n and ct-oxg6, and ct-a70m, ct-csyg, ct-4nyy and ct-dzyf under the engine-first rule; it closes when they do (WS12 rule 1). Its own unmet criterion, measured before/after evidence for every child, is replaced by WS12 (ct-uov2).
- See docs/reviews/2026-10-24-ticket-audit/README.md
