---
id: ct-hbj1
status: open
deps: [ct-pqi5, ct-f2ai]
links: [ct-o7ew, ct-knzb]
created: 2026-11-24T18:21:46Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-o7j0
tags: [docmeta, v7, sweep]
---
# DocMeta V7.3b-2: Run 328K+ archive sweep & emit validated docmeta_v7 sidecar

Stream all 328K+ archive documents through the unified p12_clean_plus_p3_bidi_clean_9000 window producer (ct-f2ai, with .cache/archive-release/docmeta-v7-ocr-rescue/rescued_p15.parquet overlaid over the 508 rescued SHAs) and run resumable local Apple Silicon inference under archive_watchdog.py using the qualified ct-pqi5 student with SHA-256 deduplication (effective_body_sha) and explicit docmeta_source.

## Acceptance Criteria

1) 100% of 328K+ archive documents swept locally with SHA-256 deduplication and Two-Channel Context formatting. 2) Emitted docmeta_v7 release sidecar passes release_contract.validate_release_sidecar_table(table) == [] with zero doc: fabricated keys or zeroed digests, accompanied by MLCommons Croissant JSON-LD and W3C DCAT-3 manifests.


## Notes

**2026-11-25T12:01:56Z**

2026-11-25: Upstream prerequisites ct-f2ai (9K window + OCR overlay) and ct-ogcq (8,510 WARC/ARC envelope cleanup) are merged on main (PR #240, 6374ea1f). Blocked solely on ct-pqi5.
