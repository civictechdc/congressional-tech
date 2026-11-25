---
id: ct-f2ai
status: closed
deps: []
links: []
created: 2026-11-22T19:53:26Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-o7j0
tags: [docmeta, v7, prep, cleanup]
---
# DocMeta V7.3b prep: unify 9K text-window producer & clean V7 package deps

Greenfield retirement of dead V4-V6.5 heuristics and unshipped `docmeta_v6_1` is already complete (82 files deleted). Before launching the 328K+ archive sweep (`ct-hbj1`), unify the text-window producer and clean package dependencies so training (`ct-pqi5`) and serving (`ct-hbj1`) share identical inputs. Plan: docs/plans/docmeta-v7-consulting-plan-20261122.md; Release contract: docs/plans/docmeta-v7-release-contract.md.

## Acceptance Criteria

1) Align `BodyTextSSOT.iter_docmeta_windows` onto the single shared `p12_clean_plus_p3_bidi_clean_9000` producer (bidi-stripped, `p3` rescue budget, overlaying `.cache/archive-release/docmeta-v7-ocr-rescue/rescued_p15.parquet` over the 508 rescued `ct-o7ew` SHAs) with unit + parity tests. 2) Add any needed lightweight deterministic pre-extractors (WAF/error/wrapper/cover/citations) in plain tested Python/DataFusion SQL (no Hamilton overhead). 3) Declare `pydantic`, `pyyaml`, `duckdb`, and `numpy` in `packages/congress_docmeta/pyproject.toml` (removing unused legacy `usaddress`/`pycountry`/`msgspec*` pins if unreferenced elsewhere) and refresh `uv.lock` after verifying zero unintended byte-hashed parser drift.

## Notes

**2026-11-24T05:13:10Z**

Rewired dependency from `ct-so28` (V7.3a corpus) to `ct-pqi5` (V7.3b student training & 328K sweep) per Owner Decision A2; added shared 9,000-char window producer parity, `docmeta_v6_1` Gate-1 PR retirement, and `packages/congress_docmeta/pyproject.toml` + `uv lock` dependency declaration items from Astra/Fable architecture review.


**2026-11-24T18:01:03Z**

Greenfield cut complete (2026-11-24): deleted 82 tracked legacy files (~2.8+ MB across V4-V6.5 heuristics/normalizers/validators/docs/scripts + unshipped viewer_publication/docmeta_v6_1.py + model/sql/document-docmeta-v6-1.sql + docmeta-model lane). Verified 237/237 affected production-offline tests + doctor + inventory (624 files) pass cleanly. Remaining scope on ct-f2ai is purely: (1) unify the single 9K text-window producer (BodyTextSSOT + rescued_p15.parquet), (2) keep any needed deterministic pre-extractors in simple Python/DataFusion SQL (no Hamilton overhead), and (3) declare pydantic/pyyaml/duckdb/numpy in packages/congress_docmeta/pyproject.toml + uv lock.

**2026-11-24T20:44:34Z**

Completed & closed 2026-11-24: (1) Added canonical 9K window producer docmeta_v7_window in viewer_publication/body_text_slices.py and aligned BodyTextSSOT.iter_docmeta_windows (p12_clean_plus_p3_bidi_clean_9000, max_chars=9000, ocr_rescue_parquet overlay respecting held/refused policy); (2) Added lightweight pure-Python congress_docmeta.v7.preextract (non-usable stub detection, bill/PL/USC/CFR/EO/GPO/HHRG/congress/date hints, and build_v7_text_window parity while keeping congress_docmeta.v7 top-level exports scoped to V7.1 core); (3) Declared pydantic/pyyaml/duckdb/numpy/viewer-publication in packages/congress_docmeta/pyproject.toml, removed unused usaddress/pycountry/msgspec* pins, and ran uv lock --no-upgrade && uv sync --frozen cleanly with zero unintended version bumps; (4) Verified 690 passed in targeted production-offline run (14 of 601 lane files including V7 tests, SSOT/handoff tests, parser pin tests, archive model & definition-change checks), scripts/dev.py doctor, scripts/dev.py inventory (625 files), and tk dep cycle.
