---
id: ct-o7j0
status: open
deps: []
links: [ct-flq8, ct-u3eh]
created: 2026-11-22T19:53:14Z
type: epic
priority: 1
assignee: mikewolfd
tags: [docmeta, v7, architecture]
---
# DocMeta V7 Core Reset: FRBR/ELI-DL decomposed schema & 3-family SOTA dataset factory

Reset DocMeta on clean FRBR/ELI-DL foundations and an anti-chaos 3-family SOTA factory (Gemini + Claude CLI + Codex CLI), superseding V6.5 training (ct-flq8, ct-u3eh). Plan: docs/plans/docmeta-v7-consulting-plan-20261122.md.

## Acceptance Criteria

Required greenfield phases closed (`ct-mqf8`, `ct-02x5`, `ct-so28`, `ct-o7ew` closed; `ct-f2ai` 9K window & dep cleanup, `ct-pqi5` student train/qualify, `ct-hbj1` 328K+ sweep, `ct-rlw5` release/MCP/site, and `ct-bngs` git checkpoints complete; optional P3 `ct-knzb` dispositioned); 0 event-grouped or temporal leakage; 0 ungrounded student targets; legacy V4-V6.5 & `docmeta_v6_1` retired; `ct-rlw5` shipped with `docmeta_v7` + external crosswalks + Croissant/DCAT-3 manifest.

## Notes

**2026-11-24T05:13:10Z**

Architectural decisions locked (2026-11-24):
- **Owner A1 (FRBR/ELI-DL scope):** Keep the 6 FRBR/ELI-DL classes (`WorkRecord`, `ExpressionRecord`, `ManifestationRecord`, `ForeseenActivity`, `RealizedActivity`, `SubmissionRecord`) in `v7/models.py` as future conceptual scaffolding, explicitly documented as unpopulated in V7.3 per-document outputs while archive SQL (`document-versions.sql`, `meeting-records-resolved.sql`) remains authoritative for editions and sittings.
- **Owner A2 (Rollout & Release Seam):** Locked `docmeta_v7` release seam in `docs/plans/docmeta-v7-release-contract.md` and `v7/release_contract.py`; split V7.3 into corpus qualification (`ct-so28` V7.3a) and student training/sweep (`ct-pqi5` V7.3b).
- **Owner A3 (Git Provenance):** Keep files uncommitted until ready and stamp transparent `git_provenance` (`git_dirty`, `codebook_tracked`) in `MANIFEST.json`.
- **Owner A4 (Local Student Architecture):** Deferred until kickoff of `ct-pqi5` after V7.3a seal and release contract completion.


**2026-11-24T15:39:01Z**

V7.3a.1 sealed strictly (9/9 gates passing, MANIFEST.json 2026-11-24T15:38:38Z): total_processed=10549, gold_count=10487, quarantined_count=60 (55 RC-1 multi-page cover truncations + 5 RC-2 blank/stub-head tail fragments incl. 455febeab7a7), deadlock_count=2; min_genre=162 (>=150); cleanlab.checked=true (oof_acc=0.9403, flagged=48); minilm_checked=true; grounding=0 errors; body_sha_contradiction_count=0; blank_head_tail_only_count=0; parquet_sha256=b7b14a1dcb489df915363f3714d57cca40c40630671af329b12999665c84c481; overrides=polish/overrides_v7_3_1.jsonl (2847). Two-Channel Context contract + reanchor_payload_for_clean_text locked in release_contract.py & docs/plans/docmeta-v7-release-contract.md. Bounded ~554-PDF fast-ocr rescue tracked in ct-o7ew.

**2026-11-24T18:01:03Z**

Greenfield fat-cut done (2026-11-24): removed 82 legacy V4-V6.5 / docmeta_v6_1 files cleanly (~10 MB -> 2.6 MB active V7 source+tests); 237/237 affected tests + doctor + inventory pass.
