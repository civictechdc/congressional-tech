---
id: ct-bult
status: in_progress
deps: []
links: []
created: 2026-11-18T19:49:45Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-ihe7
tags: [docmeta]
---
# DocMeta: raise the people (personas) limit from 10 to 26

Owner decision 2026-11-18: raise DocMetaV4Causal's personas maxItems from 10 to 26. Hearing transcripts print a witness list; labels must capture what the text states. 30 of 324 labeled transcripts list 11 to 26 witnesses, so the cap of 10 forced 166 stated witnesses out of the labels. Options shown: keep 10 with witnesses first; raise to 16; raise to 26. Owner chose 26.

Scope: one named constant for the limit across the JSON schema, SCHEMA_OBJ, the compact wire format, the decoding grammar, validators, post-pass rules, prompts and tests; keep schema name, field order and keys. Roster spam stays guarded (the cap of 10 was also its backstop). Output-token default sized for a 26-person answer. Report training-length consequence (fast-gemma4 train_lora --max-seq-len 3584) without running a trainer. Move any sealed identity or version the change genuinely moves, with the reason in the commit.

## Acceptance Criteria

A 26-person label validates and round-trips through the compact format; 27 is rejected by schema, validator and (if testable without a model) the grammar; a 10-person label validates unchanged. Package offline tests pass through scripts/dev.py. Engine tests (docmeta-model lane) listed for a GPU run, not run here.

