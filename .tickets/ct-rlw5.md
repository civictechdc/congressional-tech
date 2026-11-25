---
id: ct-rlw5
status: open
deps: [ct-hbj1]
links: []
created: 2026-11-22T18:41:11Z
type: feature
priority: 2
assignee: mikewolfd
tags: [docmeta, release, mcp, site]
---
# Publish DocMeta structured metadata in the release, MCP and site

Wire the greenfield DocMeta V7 sweep sidecar (`ct-hbj1` under epic `ct-o7j0`: unified 9K windows + `ct-o7ew` OCR rescue + qualified `ct-pqi5` student) directly into `model/jobs/publish-model.json` / release document tables, Congress MCP (`apps/explorer_mcp`), and `apps/site` per `docs/plans/docmeta-v7-release-contract.md` and `congress_docmeta.v7.release_contract` (no legacy `docmeta_v6_1` cutover/fallback needed). Expose unified `document_kind` filtering (`v7_to_document_kind`), structured V7 `primary_genre`/`subkind`, separated `media_format`/`is_packet`, clean titles/gists/topics, personas, `members_present`/`staff_present`, Truth-in-Testimony disclosures, refs, outward crosswalks, and **dual provenance display** (intrinsic doc type vs. hearing attachment `meetings.document_references.role`/`name`), while keeping entity resolution in `viewer_publication.org_entities`. Plan: `docs/plans/docmeta-v7-consulting-plan-20261122.md`.

## Acceptance Criteria

1. Digest-pinned `docmeta_v7` sidecar passing `validate_release_sidecar_table` and joined via `(link_key, doc_key, saved_body)` (`build_docmeta_v7_release_join_sql` + `build_docmeta_v7_invariants_sql`, honoring `AGENTS.md` DataFusion rules) bound directly into `publish-model.json` with coverage, omission/refusal counts, and static outward crosswalks (`docs.house.gov` 18+4 codes, `api.congress.gov/v3`, and LoC `LCGFT` URIs); entity resolution stays in `viewer_publication.org_entities`. 2. Machine-verifiable **MLCommons Croissant JSON-LD** + **W3C DCAT 3** release catalog metadata manifest emitted with the release bundle. 3. `apps/explorer_mcp` exposes unified `document_kind` (`map_genre_to_document_kind` + `list.parquet` synonyms), structured DocMeta V7 fields, and dual provenance (intrinsic genre vs. hearing attachment slot/title). 4. `apps/site` renders DocMeta V7 metadata + dual provenance cleanly and passes `npm --prefix apps/site run contract:archive`.


## Notes

**2026-11-22T19:53:35Z**

2026-11-22 Rewired dependency from superseded ct-u3eh (V6.5) to ct-so28 (DocMeta V7.3) and added A3 deliverables: static outward doc_kind crosswalk (docs.house.gov 18+4, Congress.gov v3, LoC LCGFT URIs) + MLCommons Croissant JSON-LD & W3C DCAT 3 release catalog manifest.

**2026-11-24T05:13:10Z**

2026-11-24 Rewired dependency from ct-so28 (V7.3a corpus qualification) to ct-pqi5 (V7.3b local student training & 328K sweep) per Owner Decision A2. Locked `docmeta_v7` release seam in `docs/plans/docmeta-v7-release-contract.md` and `packages/congress_docmeta/src/congress_docmeta/v7/release_contract.py` (`(link_key, doc_key, saved_body)` join, `v7_to_document_kind` unified filter mapping, and `viewer_publication.org_entities` entity-resolution ownership).
