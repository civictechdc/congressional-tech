---
id: ct-pt42
status: closed
deps: []
links: [ct-r524]
created: 2026-11-18T22:05:15Z
type: task
priority: 3
assignee: mikewolfd
tags: [docmeta, model, fast-gemma4]
---
# fast-gemma4 ANE prefill ring leftovers: older batch-cache pad write, 13-doc cohorts, hardware tests on the new native call

Left over from the ring work merged into fast-gemma4 main as b725b87 (2ff2b9f pad fix, edd577a seven chunks). (a) _prefill_early14_group, the older batch-cache prefill, still writes pad positions into sliding-window ring layers the way _prefill_early14_slot_group did before 2ff2b9f. The sweep does not use it; find who does before fixing or deleting it. (b) Seven chunks need one ring slot per doc per chunk, so the 96-slot ring carries 13 docs per cohort instead of 16. out_ring_slots=128 would restore 16 at about 150 MB (estimate); nobody has measured whether 16-doc cohorts are faster. (c) tests/test_ane_hybrid_and_writer.py had its long-tail case raised from 820 to 2,100 suffix tokens for the new gemma4_px_run_chunk_into_ring call; see the linked ticket for the suite's state on main. Two ideas the owner did not take up on 2026-11-17, recorded so they are not lost: report measured ANE busy time in the eval summary; rebuild the Early14 bundle with a 2,944-token history input (would cover an estimated 99.0% of prefill tokens against 90.5% now). Side-session notes: ane-ring-accuracy-findings-20261117.md, ane-capabilities-research-20261117.md.

## Acceptance Criteria

1. _prefill_early14_group either routes its ring writes through _scatter_ring_chunk or is deleted with its callers named. 2. A back-to-back idle-machine timing of 96 against 128 ring slots decides the cohort size, recorded in the measurements note. 3. The hardware tests in tests/test_ane_hybrid_and_writer.py pass on fast-gemma4 main.


## Notes

**2026-11-22T18:40:56Z**

2026-11-22 ticket backlog audit: Deferring and closing — internal fast-gemma4 ANE housekeeping (_prefill_early14_group unused by sweep; cohort size unmeasured while Base M5 already runs ~1.8-2.3 docs/s); reopen only if a broken hardware test blocks CI/releases.
