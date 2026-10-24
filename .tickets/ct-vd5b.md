---
id: ct-vd5b
status: closed
deps: []
links: [ct-esm4, ct-n3qy, ct-vxzu, ct-ma8a, ct-fqgf, ct-r46l]
created: 2026-10-19T17:00:40Z
type: task
priority: 2
assignee: mikewolfd
tags: [script-restructure]
---
# Split resident_tree and webharvest CDX imports

Architecture review of the top-level scripts/ restructure returned RECONSIDER. This ticket describes the reshape, not the blocked original plan. Implementation agent 338f11a1-e496-4c63-b886-17efe958ffec is applying the reshape now.

Move resident_tree to scripts/process_rss.py. publication_costs and benchmark_viewer_publication import it; measure_publication_control does not need a direct import. Move digest, key, load, parse_cdx, and save to scripts/webharvest_cdx.py and re-export them from webharvest_index_remaining.py so tests/test_webharvest_index_remaining.py still works. Do not replace resident_tree with .github/scripts/capture-memory-guard.py.

## Acceptance Criteria

- resident_tree lives in scripts/process_rss.py.
- publication_costs and benchmark_viewer_publication import resident_tree from scripts/process_rss.py.
- measure_publication_control does not import resident_tree directly.
- digest, key, load, parse_cdx, and save live in scripts/webharvest_cdx.py.
- webharvest_index_remaining.py re-exports digest, key, load, parse_cdx, and save.
- tests/test_webharvest_index_remaining.py still imports those names and passes.
- resident_tree is not replaced by .github/scripts/capture-memory-guard.py.


## Notes

**2026-10-19T18:10:39Z**

a56d222071d22f8c64a4f6d0c77962ea04bb16df Split shared RSS sampling and CDX parsing from their command modules.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch standalone).
- Grades: proposal 70 → 70, work 90 → 90.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
