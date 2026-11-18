---
id: ct-1lpr
status: open
deps: []
links: []
created: 2026-11-17T20:17:27Z
type: bug
priority: 3
assignee: mikewolfd
parent: ct-ihe7
tags: [docmeta]
---
# DocMeta V4 system prompt lists statuses in a different order every process

prompt_v4.py builds STATUS_CSV with '|'.join(STATUS_SET), a Python set, so SYS_DOCMETA_V4 changes with the hash seed. Measured 2026-11-17: three runs of the same code gave three orders; old (fast-gemma4 11dcf14) and moved code agree under a fixed PYTHONHASHSEED. The V4 training prompts (train_v4_all360.jsonl) froze one order: error_or_block|index_or_listing|govinfo_wrapper|ocr_unreadable|usable|cover_or_toc|stub_or_blank|catalog_xml. Affects the V4 wire only (FUSED_V4 and the Pass-2 user prompt); the compact wire the current model uses is fixed text. Found while moving DocMeta (ct-ihe7); not fixed there because it changes what a V4-wire model is fed.

## Acceptance Criteria

SYS_DOCMETA_V4 is the same string in every process and equals the order the V4 model was trained on; a test runs two hash seeds.

