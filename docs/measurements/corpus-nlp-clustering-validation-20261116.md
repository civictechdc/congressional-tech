# Corpus Quality, NLP Contradiction & Tail Clustering Validation (`2026-11-16`)

Live validation of the `viewer_publication.corpus_quality` suite and `scripts/measure/corpus_quality_audit.py` against the full `323,564`-row `55c14dcda87a` published tables (`candidate-df55-final/public-readback/published`) paired with `docmeta_v6_1` (`parquets_v6_1`), using fresh audit seed `20261117`.

- **Release Gate Status**: **PASS** (`error_count = 0`, `max_errors = 0`, `warning_count = 3,722`, `info_count = 233`)
- **Provenance & Conservation Gate**: **PASS** (`passed_gate = true`)
- **Total Rows Audited**: `323,564` (`p12_text` hydrated on `277,100` rows / `85.64%`)
- **Total Wall-Clock Runtime**: `382.30s` (`load=8.00s`, `provenance=3.67s`, `tfidf_drift=220.07s`, `tail_clusters=144.97s`, `stratified_sampler=5.48s`)

---

## 1. Provenance, Conservation & Boundary Validation (`docmeta_v6_1`)

| Metric | Observed Value |
| --- | ---: |
| `detail.parquet` rows | `323,564` |
| `completed_no_llm_v6_1` rows | `64,582` |
| `llm_queue_v6_1` rows | `258,794` |
| `sha_dup_alias_v6_1` rows | `188` |
| Partition sum (`completed + queue + aliases`) | `323,564` (`exact = True`) |
| Duplicate `link_key` / `doc_key` | `0` / `0` |
| Orphan rows / `saved_body` mismatches | `0` / `0` |
| Broken `sha_dup_alias` targets | `0` |
| Invalid `strict_v4_valid` / malformed JSON | `0` / `0` |
| Usable rows missing `primary_kind` | `0` |
| `hsru00` floor-author leaks in `docmeta_v6_1` | `0` |

### Cross-Table Provenance & Trap Checks
- **Unattributed Committees (`committee_keys = []`)**: `72,760 / 323,564` (`22.49%`; `60,375` on resolvable committee hosts such as `veterans.house.gov`, `naturalresources.house.gov`, `waysandmeans.house.gov`).
- **`hsru00` Floor Attribution**: `5,749` published `hsru00`-only rows, `3,056` floor-repo URLs, `0` `docmeta` floor-author leaks.
- **URL Date Traps**: `10,493` CMS `/uploads/` URLs (`0` leaks), `101` Wayback/WebHarvest URLs (`0` leaks), `2,563` Senate download URLs, `5,215` `published_time` rows.
- **Congress Boundaries (`house_naming`)**: `24,985` `BILLS-` slugs checked (`1` mismatch), `0` out-of-range Congresses, `181` Noon-Jan-3 odd-year off-by-one rows.

---

## 2. TF-IDF / Log-Odds Label-Contradiction & Boilerplate Drift

Comparing raw published `55c14dcda87a` labels against `docmeta_v6_1` across all `323,564` rows:

| Label Source | Total Contradictions | `kind_body` | `committee_body` | `congress_body` | `-Bio-` Slot | `-Wstate-` Slot | `-SD` Slot |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Raw Published (`55c14dcda87a`) | `6,474` | `5,033` | `1,215` | `226` | `1,655` | `956` | `226` |
| `docmeta_v6_1` | `3,150` | `1,702` | `1,222` | `226` | `202` | `641` | `260` |
| **Delta (`docmeta_v6_1 - raw`)** | **`-3,324`** | **`-3,331`** | `+7` | `0` | **`-1,453`** | **`-315`** | `+34` |

- **`-Bio-` Upload-Slot Contradictions**: `docmeta_v6_1` resolved **`1,453` of `1,655` (`87.8%`)** raw `-Bio-` slot contradictions, leaving `202` residual contradictions flagged for downstream review.
- **Host Boilerplate & Soft-Refusal Drift Alerts**: `12` host-level alerts surfaced.

---

## 3. Unmapped-Tail & Emergent-Template Clustering (`llm_queue_v6_1`)

- **Target Tail Population**: `159,218 / 323,564` rows (`50,034` grouped into `4,353` deterministic structural + URL-template clusters; `0` emergent spike alerts in single-snapshot mode).
- **Notable Actionable Clusters**:
  - `tail-001-veterans-house-gz-narrative` (`5,791` rows) and `tail-002-veterans-house-gz-narrative` (`2,613` rows): `veterans.house.gov` `.html.gz` narrative committee pages.
  - `tail-003-judiciary-house-pdf-caps` (`1,638` rows) and `tail-006-financialservices-ho-pdf-caps` (`456` rows): committee-hosted GPO printed hearings matching `existing_page_signal_matches: gpo_printed_hearing_cover`.
  - `tail-011-docs-house-gov-pdf-narrative` (`374` rows): `existing_cover_rule_matches: document_cover:legislative-text`.
  - `tail-012-congress-gov-pdf-empty` (`336` rows): `new_error_or_wrapper_signal_candidate: page-signals:empty_or_scan_only_container`.
  - `tail-014-docs-house-gov-pdf-caps` (`329` rows): `new_cover_rule_candidate: cover:emergent-nays` (roll-call vote / nay tally sheets).

---

## 4. Seeded Multi-Stratum Acceptance Packet (`seed = 20261117`)

Sampled `140` items (`per_stratum = 10`) across `14` strata (`7` core strata + `4` dynamic `anomaly:*` strata + `3` top `tail_cluster:*` strata), keyed canonically on `(link_key_hex, saved_body_hex)`:
- Core strata sampled: `upstream_spicydocs_bills_hearings` (`48,741`), `zero_llm_synthesized_docmeta` (`19,312`), `unwrapped_warc_arc` (`8,354`), `gpo_transcript` (`4,612`), `clerk_bio_slot_override` (`21,293`), `clerk_statement` (`89,688`), `open_extraction_tail` (`131,564`).
- Dynamic anomaly & tail strata sampled: `anomaly:boilerplate_drift` (`12`), `anomaly:congress_boundary` (`51`), `anomaly:label_contradiction` (`3,144`), `anomaly:tail_cluster` (`717`), and top 3 tail clusters (`5,791`, `2,613`, `1,638`).

---

## 5. Verification Gate Summary

- `corpus_quality` + `measure` + `docmeta_v6_1` + `producer_identities` pytest suite: `100%` pass.
- `scripts/dev.py inventory`: `0` unenrolled test files.
- `congress_api.lake.reading_version_diagnostics`: `0` drift.
- Scratch/artifact path leaks: `0` matches.
