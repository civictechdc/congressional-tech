---
id: ct-mqf8
status: closed
deps: []
links: []
created: 2026-11-22T19:53:26Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-o7j0
tags: [docmeta, v7, schema]
---
# DocMeta V7.1: Codebook RFC, FRBR/ELI-DL decomposed specialist schemas & outward crosswalks

Define locked Pydantic v2 + YAML codebook_v7.0 replacing the 47-way flat schema: ~12-15 orthogonal genres, 3 separated attributes (status absorbing error_or_non_document; is_packet/contains_kinds[]; media_format prose|slides|web_page|table_or_form), 5 tight specialist schemas (Event Logistics, Testimony/Bios/Disclosures, Transcripts/Votes/Attendance, Correspondence/QFRs/Oversight, Legislation/Reports/Fiscal), FRBR Work/Expression/Manifestation + EU ELI-DL ForeseenActivity->Activity mapping, static outward crosswalk (docs.house.gov 18+4 codes, api.congress.gov/v3, LoC LCGFT URIs), MLCommons Croissant JSON-LD + W3C DCAT 3 release metadata spec, and explicit negative boundary examples. Plan: docs/plans/docmeta-v7-consulting-plan-20261122.md.

## Acceptance Criteria

1) Frozen Git-tracked codebook_v7.0 + Pydantic v2 schemas for Core Triage + 5 Specialist Extractors. 2) Negative boundary rules & explicit null/abstention conditions documented per field. 3) Static outward crosswalk covering docs.house.gov (18+4), Congress.gov v3, and LCGFT URIs verified by unit tests. 4) Croissant JSON-LD + DCAT 3 schema spec validated.


## Notes

**2026-11-22T21:51:40Z**

Completed V7.1 schema, codebook, crosswalks, and release metadata under packages/congress_docmeta/src/congress_docmeta/v7/ ({__init__,codebook,models,crosswalk,release_metadata}.py + codebook_v7_0.yaml + crosswalk_v7_0.yaml) and packages/congress_docmeta/tests/v7/test_v7_schemas_and_crosswalk.py. Verified: codebook_v7_0 (14 orthogonal genres partitioned 1:1 into 5 specialist families, 8 DocStatus, 4 MediaFormat, negative boundaries & abstention rules), Pydantic v2 FRBR Work/Expression/Manifestation + ELI-DL ForeseenActivity/RealizedActivity/SubmissionRecord + strict JSON schemas, outward crosswalks (docs.house.gov 18+4, Congress.gov v3, LoC LCGFT URIs), Croissant JSON-LD + W3C DCAT 3 manifest builder/validator, and OCR SpanRef fuzzy grounding. Verified under restored .venv Python 3.12.13 pytest.
