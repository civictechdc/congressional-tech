---
id: cef-cpgw
status: closed
deps: []
links: []
created: 2026-10-28T06:08:17Z
type: task
priority: 1
assignee: mikewolfd
---
# Verify raw-only document rebuilds across a registry change

Recreate D1, D2 and D3 from the same retained local receipt/body inputs without old derived inputs. Require identical native release bytes before and after a real capture-scope policy change; record full-corpus and schema-generation acceptance separately.


## Notes

**2026-10-28T07:14:21Z**

Local fixture acceptance passed at 6318ac85: production-offline test_phase1_raw_rebuild.py, 1 passed in 14.74s with qualified 71cc6eb. Independently regenerated captures/readings/filename_readings from retained raw and qualification only; exact public bytes match before and after a real capture-scope registry change. Full-corpus, native-generation and broader E2 acceptance remain separately open in cef-uvom/cef-h2rv.
