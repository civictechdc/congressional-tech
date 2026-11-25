# congress-docmeta (DocMeta V7)

FRBR / ELI-DL-grounded document metadata extraction, 3-family SOTA corpus construction, and the `docmeta_v7` release seam for U.S. Congressional committee documents.

## Layout

- `congress_docmeta.v7.models` — Pydantic v2 core envelope + 5 specialist family schemas, exact character-offset `SpanRef` verification (`verify_grounded_extraction`), and non-populated FRBR/ELI-DL conceptual scaffolding.
- `congress_docmeta.v7.codebook` & `codebook_v7_0.yaml` — Versioned annotation codebook (v7.0) with strict intrinsic-vs-submission, cover/TOC boundary, and GPO `[ERRATA]` rules.
- `congress_docmeta.v7.crosswalk` & `crosswalk_v7_0.yaml` — Deterministic mappings from `PrimaryGenre` + `subkind` to canonical `house_naming` `document_kind`, Congress.gov v3, `docs.house.gov`, and LoC LCGFT terms.
- `congress_docmeta.v7.release_contract` — Locked `docmeta_v7` Arrow sidecar schema, fail-closed validator, DataFusion join/invariant SQL, `format_two_channel_input` (`<<<DOCUMENT_CONTEXT>>>` + `<<<DOC_TEXT>>>` with 50% SFT dropout), and `reanchor_payload_for_clean_text`.
- `congress_docmeta.v7.release_metadata` — MLCommons Croissant JSON-LD and W3C DCAT-3 catalog generators & validators.
- `congress_docmeta.v7.factory` — 3-family SOTA consensus factory (Gemini, Claude CLI, Codex CLI), CheckEval arbitration, counterfactual sensitivity harness, MiniLM/TF-IDF decontamination, Cleanlab OOF audit, and `--strict` atomic corpus sealer.

## Sealed Corpus & OCR Overlay Artifacts

- **Sealed V7.3a.1 corpus:** `.cache/archive-release/docmeta-v7-corpus/sealed/docmeta_v7_3.parquet` (`10,487` gold rows, `9/9` strict gates passing, `60` bad-window exclusions quarantined).
- **`fast-ocr` archive rescue overlay (`ct-o7ew`):** `.cache/archive-release/docmeta-v7-ocr-rescue/rescued_p15.parquet` (`559` targeted PDFs, `508` cleanly recovered across pages 1–5 at \$0 API cost).
- **Release contract doc:** [`docs/plans/docmeta-v7-release-contract.md`](../../docs/plans/docmeta-v7-release-contract.md).
