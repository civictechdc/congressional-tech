# DocMeta V7 Release Contract (`docmeta_v7` Seam)

**Status:** Locked architectural contract (Contract `7.3`, Owner Decisions A1/A2/A3/A4)  
**Scope:** Interface between `congress_docmeta.v7` (training corpus + future V7.3b 328K student inference), `viewer_publication` (DataFusion archive release model), `apps/explorer_mcp`, and `apps/site`.  
**Machine-enforced schema & validator:** [`packages/congress_docmeta/src/congress_docmeta/v7/release_contract.py`](../../packages/congress_docmeta/src/congress_docmeta/v7/release_contract.py)

---

## 1. Source Byte & Archive Join Identity

- **Authoritative internal join keys:** `(link_key, doc_key, saved_body)` against the archive DataFusion `details` relation (cf. [`model/sql/document-docmeta-v6-1.sql`](../../model/sql/document-docmeta-v6-1.sql)).
  - `link_key`: `FixedSizeBinary(8)` (8 raw bytes; hex helper column `link_key_hex` in training Parquets).
  - `doc_key`: `Utf8` logical document key matching `details.doc_key` (`document-identities.sql`).
  - `saved_body`: `FixedSizeBinary(32)` exact captured-byte SHA-256 digest (`body_sha256` hex in training Parquets; explicit `NULL` in V7.3 training artifacts if legacy V6.5 SSOT rows lacked retained byte digests — **never** fabricated from `doc_key` or `doc:<link_hex>`).
- **Published table caveat vs. internal `details`:** Public `detail.parquet` (`model/registries/release-schema.json`) exposes `link_key` and `saved_body` without `doc_key`, whereas internal `details` exposes all three (`list_row, doc_key, link_key, saved_body, package_id`). Legacy `sidecar_builder.py:427` wrote fabricated `doc:<link_hex>` keys that fail against real `details.doc_key`. V7 forbids `doc:` prefixes fail-closed inside `validate_release_sidecar_table` and `build_docmeta_v7_invariants_sql`.
- **Training corpus vs. release sidecar boundary:** `.cache/archive-release/docmeta-v7-corpus/sealed/docmeta_v7_3.parquet` is an **internal V7.3a training/benchmark corpus** (indexed by string `doc_key`, `link_key_hex`, `body_sha256`), whereas the future Gate-1 `docmeta_v7` release sidecar produced after V7.3b student sweep MUST conform strictly to `release_sidecar_arrow_schema()`.

---

## 2. Unified Filter Vocabulary (`v7_to_document_kind`)

- **No parallel dropdowns:** `apps/explorer_mcp` and `apps/site` filter documents via `list.parquet`'s `document_kind[]` column and `synonyms.document_kind[]` in [`model/registries/release-schema.json`](../../model/registries/release-schema.json) (`release.py:kind_words`).
- **Authoritative mapping:** `congress_docmeta.v7.crosswalk.map_genre_to_document_kind(primary_genre, subkind=...)` (defined in `v7/crosswalk_v7_0.yaml`) maps all 14 `PrimaryGenre` values deterministically onto canonical `house_naming` `document_kind` strings (plus `subkind_overrides` for committee/floor amendments, QFR responses, witness lists, member rosters, rules memos, and budget views & estimates).
- **Non-usable isolation:** Rows with `status != "usable"` MUST emit `primary_genre = None` and `archive_document_kind = None`, preventing error stubs, wrappers, or covers from polluting user genre filters.

---

## 3. Canonical Text-Window Producer Contract

- **V7.3a teacher window:** `DOCMETA_V7_TEXT_WINDOW_SPEC = "p12_clean_or_raw_head_9000"` (`9,000` chars), matching the V7.3a candidate pool window.
- **V7.3b student window & Two-Channel Context contract:** `DOCMETA_V7_STUDENT_TEXT_WINDOW_SPEC = "p12_clean_plus_p3_bidi_clean_9000"` (invisible Unicode bidi/format chars stripped, `p3_toc_or_gavel_slice` appended on `is_cover_roster_p12` / packet docs inside the 9,000-char cap), formatted via `release_contract.format_two_channel_input`:
  - **SFT offset parity on legacy V7.3a candidates:** V7.3b SFT training loaders consuming V7.3a candidates containing invisible format characters (67 legacy rows) MUST call `release_contract.reanchor_payload_for_clean_text(raw_text, core_payload, specialist_payload)` alongside `format_two_channel_input` so `SpanRef` `[start, end]` bounds match the stripped `<<<DOC_TEXT>>>` string byte-for-byte.
  - **Channel 1 (`<<<DOC_TEXT>>>` — sovereign for intrinsic genre & verbatim spans):** Bidi-cleaned bounded text window. Verbatim spans (`verbatim_title`, `title_span`, `date_spans`, `personas`, `issuer_org`) MUST ground solely inside `<<<DOC_TEXT>>>`.
  - **Channel 2 (`<<<DOCUMENT_CONTEXT>>>` — structural & provenance context only):** Allows ONLY `page_count`, `saved_bytes`, `congress_gov_doc_title` (`meetings.document_references.name`, present on 99.8% of Congress.gov Support Documents), and non-generic `source_link_text` (filtering `"please click here"`, `"download"`, `< 15`-char strings, or bare filenames). Raw filename slugs (`filename`, e.g., `-Wstate-`/`-TTF-`) and Congress.gov slot names (`congress_gov_role`) are **strictly forbidden** (`ValueError`).
  - **50% SFT Context Dropout (`STUDENT_CONTEXT_DROPOUT_RATE = 0.50`):** Randomly omit `<<<DOCUMENT_CONTEXT>>>` on half of SFT training steps so the local student performs strongly on the ~38% of archive docs lacking meeting links and preserves counterfactual slug-invariance.
- **Unified sweep window producer (`ct-f2ai`, `body_text_ssot.py`):** `BodyTextSSOT.iter_docmeta_windows` (`packages/viewer_publication/src/viewer_publication/body_text_ssot.py`) is pinned directly to `DOCMETA_V7_STUDENT_TEXT_WINDOW_SPEC` (`p12_clean_plus_p3_bidi_clean_9000`, `max_chars=9000`) via `viewer_publication.body_text_slices.docmeta_v7_window`, supporting `.cache/archive-release/docmeta-v7-ocr-rescue/rescued_p15.parquet` overlay (`ocr_rescue_parquet`) so V7.3b training and 328K+ serving match 1:1.

### Dual Provenance Display in Congress Explorer (`ct-rlw5` & `ct-f2ai`)

- Downstream search and hearing UI/MCP tools MUST distinguish cleanly between **what the file intrinsically IS** (`docmeta_v7.primary_genre`, `archive_document_kind`, `subkind`, e.g. `Executive Order` or `Congressional Record` excerpt) and **why it is attached to a hearing** (`meetings.document_references.role` and `name`, e.g. `"Support Document"` / `"FTR - E.O. 14112 - Rep. Leger Fernandez"`). Never overwrite an artifact's intrinsic type with its submission slot name.

---

## 4. Entity-Resolution Ownership Boundary

- **DocMeta V7 responsibility:** Extract **verbatim, span-grounded evidence strings and character offsets** (`PersonaEntry`, `committees`, `subcommittees`, `bill_refs`, `grants_or_contracts`, etc.) strictly from the bounded document text window — zero ungrounded inference or canonical database synthesis.
- **`viewer_publication` / Org Entities responsibility:** Own canonical identifier resolution from DocMeta strings + archive context (`viewer_publication` SQL/Python, `appearance_records_resolved`, `committee_records`, `bills`, Org Entities). DocMeta V7 does not fabricate `witness_key`, `org_id`, `bioguide_id`, `committee_key`, or `measure_key`.

---

## 5. FRBR / ELI-DL & Student Architecture Deferral

- **FRBR / ELI-DL conceptual classes (Owner Decision A1):** `WorkRecord`, `ExpressionRecord`, `ManifestationRecord`, `ForeseenActivity`, `RealizedActivity`, and `SubmissionRecord` remain in `v7/models.py` as forward-looking conceptual scaffolding and are **explicitly unpopulated in V7.3** per-document outputs. Existing archive SQL (`document-versions.sql` and `meeting-records-resolved.sql`) remains authoritative for document editions and committee sittings.
- **Local Apple Silicon student architecture (Owner Decision A4):** Deferred until after V7.3a polished corpus qualification and this contract are locked; recorded on the split V7.3b child ticket under `ct-o7j0`.

---

## 6. Gate-1 PR Checklist (`ct-rlw5` & `ct-f2ai`, Future Phase)

When integrating the qualified V7.3b student sweep into the archive release:
1. Validate every generated sidecar partition with `validate_release_sidecar_table(table) == []`.
2. Add `viewer_publication.docmeta_v7` + `model/sql/document-docmeta-v7.sql` using `build_docmeta_v7_release_join_sql()` and `build_docmeta_v7_invariants_sql()` (honoring `AGENTS.md` DataFusion rules: small sidecar on left of hash join, zero unpushed `GROUP BY` over `captures`).
3. Populate `document_kind` + `synonyms` cleanly from `map_genre_to_document_kind` so `explorer_mcp` and `site` expose V7 facets without taxonomy drift.
4. Wire `docmeta_v7` into `model/jobs/publish-model.json`, update `model_spec` `sha256` and `size` in `model/jobs/publish.json`, retire `docmeta_v6_1` and the legacy V4–V6.5 heuristic stack in that clean cutover PR, and explicitly declare `pydantic`, `pyyaml`, `duckdb`, and `numpy` in `packages/congress_docmeta/pyproject.toml` + `uv lock` after impact review.
