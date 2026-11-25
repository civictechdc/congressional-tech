---
id: ct-bwyj
status: closed
deps: []
links: [ct-2cig, ct-69ly]
created: 2026-11-18T22:04:57Z
type: bug
priority: 3
assignee: mikewolfd
tags: [docmeta, work-addr]
---
# DocMeta R8 keeps a wrong model-written work address (a letter recipient given the sender's)

Rule R8 (attach_work_addresses_v6 in packages/congress_docmeta/src/congress_docmeta/relational_rules_v6.py) never replaces a work_addr the model wrote. Seen 2026-11-17 on HHRG-116-IF17-20200128-SD031.pdf: the model gave the letter's recipients the sender's address, and R8 left it. How often this happens is not measured; one document was read. R8 itself was read against the text on every address it added (16 of 16 right on val48 and valid_sweep).

## Design

Measure first, with no model: on the saved predictions in fast-gemma4 artifacts/eval/v64_ep1_r8_after.json, count people whose model-written work_addr differs from the address R8 would attach from the block under their own name (read_work_addresses in congress_docmeta/address_reader/congressional.py gives the offsets). Read a sample against the text before changing the rule. If the count is real, let R8 replace a model address only when the text prints a different address directly under that person's name and the model's address is printed under someone else's. Scratch scripts for this kind of count: fast-gemma4 artifacts/work-addr-20261117/ (rule_vs_gold.py, show_blocks.py).

## Acceptance Criteria

The count and the sample reading are recorded here. If the rule changes: work_addr agreement stays 100 percent on val48 and valid_sweep, no other field moves, and the SD031 letter's recipients no longer carry the sender's address.


## Notes

**2026-11-22T18:40:56Z**

2026-11-22 ticket backlog audit: Deferring and closing — observed on 1 document (HHRG-116-IF17-20200128-SD031.pdf) with unmeasured prevalence on a secondary field not surfaced to users; reopen if work_addr becomes a published user-facing field.
