---
id: ct-pqi5
status: open
deps: [ct-so28]
links: [ct-o7ew]
created: 2026-11-24T05:13:08Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-o7j0
tags: [docmeta, v7, training]
---
# DocMeta V7.3b-1: Select, train & qualify local Apple Silicon student on V7.3a.1

Select the local Apple Silicon student architecture (Owner Decision A4: e.g. 2-tier encoder + ~4B MLX vs single Gemma-4/Qwen3.5 MLX), train SFT/DPO on the sealed DocMeta V7.3a.1 corpus (`docmeta_v7_3.parquet`, 10,487 gold rows), and qualify programmatically on `sealed_temporal_2026` before running the 328K+ archive sweep (`ct-hbj1`).

## Design

Contract: docs/plans/docmeta-v7-release-contract.md; Schema validator: packages/congress_docmeta/src/congress_docmeta/v7/release_contract.py. Format training inputs via `format_two_channel_input` (`STUDENT_CONTEXT_DROPOUT_RATE = 0.50`, forbidding `filename`/`congress_gov_role`) and re-anchor legacy V7.3a bidi spans with `reanchor_payload_for_clean_text(..., normalize_ws=True)`.

## Acceptance Criteria

1) Owner Decision A4 architecture documented and implemented for Apple Silicon local training/inference. 2) Local student achieves >= 0.90 Macro-F1 and Gwet AC1 with 0 ungrounded span errors on `sealed_temporal_2026` via purely programmatic scoring, and passes counterfactual slug-invariance checks (`ct-hbj1` unblocked).


## Notes

**2026-11-24T15:39:01Z**

Consume sealed V7.3a.1 parquet (.cache/archive-release/docmeta-v7-corpus/sealed/docmeta_v7_3.parquet, sha256=b7b14a1dcb489df915363f3714d57cca40c40630671af329b12999665c84c481, gold_count=10487, quarantined=60). SFT loader MUST format inputs with release_contract.format_two_channel_input (STUDENT_CONTEXT_DROPOUT_RATE=0.50; forbidden: filename, congress_gov_role) AND re-anchor legacy V7.3a bidi spans via release_contract.reanchor_payload_for_clean_text(raw_text, core_payload, specialist_payload).

**2026-11-24T16:09:54Z**

ct-o7ew fast-ocr rescue completed: overlay .cache/archive-release/docmeta-v7-ocr-rescue/rescued_p15.parquet (559 SHAs, sha256=ea2179a0f47cac4ba7dd000944fc0131f1cab5ca90f022d53fecffa39543f688; 508 ok, median 2671 chars) ready to merge before 328K student sweep.

**2026-11-24T18:01:03Z**

Legacy V4-V6.5 and docmeta_v6_1 retired up front (greenfield simplification). Next step: align the single 9K text-window producer (p12_clean_plus_p3_bidi_clean_9000 + ct-o7ew rescued_p15.parquet overlay) BEFORE the 328K student sweep, select Apple Silicon student architecture (Owner A4), train & qualify (>=0.90 Macro-F1 / AC1, 0 ungrounded spans on sealed_temporal_2026), and emit docmeta_v7 sidecar.
