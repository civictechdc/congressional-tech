---
id: cefr-tovv
status: closed
deps: []
links: []
created: 2026-10-28T07:30:46Z
type: chore
priority: 2
assignee: raw
---
# Make ZIP byte fixtures deterministic

Pin the two ZIP fixture writers to a fixed timestamp while preserving requested member compression, so repeated fixture generation keeps the same bytes.

## Acceptance Criteria

The archive member and engine-first sniff focused runner checks pass without production or assertion changes.


## Notes

**2026-10-28T07:33:26Z**

Closed local fixture-only scope: focused project runner production-offline with engine71 narrow runtime exited0, 55 tests passed (double quiet output). Both ZIP helpers use fixed2000-01-01 timestamps; archive keeps requested compress_type. Production code and assertions unchanged.
