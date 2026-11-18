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


## Notes

**2026-11-18T20:15:35Z**

Branch docmeta-people-limit-26 (local, not pushed). Limit is now schema_v4.MAX_PERSONAS (schema personas maxItems 26); roster guard is role-based (anomaly_router_v6.roster_shaped_members_v6 > 10, shared with eval_blind roster_spam_docs); MAX_OUTPUT_TOKENS 768 -> 1536; WIRE_CONFIG records max_personas. Offline package tests pass (40 passed, 2 skipped). Measured 2026-11-18 (tokenizer only): no training pair moves over 3,584 (28 of 3,449 over at full text before and after, all fit after windowing); largest 26-person transcript pair 3,456; R5 now adds 64 cosponsors past 10 on 5 training bills. Open: run docmeta-model lane (new grammar test) and the blind eval with v6_4 on this branch before any sweep (v6_4 was trained on 10 and now reads the 26 prompt and grammar); update ANNOTATION_RUBRIC.md personas <=10 line in docmeta-v65-raretypes-20261118; fast-gemma4 train_lora.py adapter_meta version label v6_4_c2_c4_bf16 is hard-coded.
