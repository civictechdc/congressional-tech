---
id: ct-n3qy
status: closed
deps: []
links: [ct-esm4, ct-vxzu, ct-ma8a, ct-fqgf, ct-vd5b, ct-r46l]
created: 2026-10-19T17:00:41Z
type: task
priority: 2
assignee: mikewolfd
tags: [script-restructure]
---
# Require measurement git revisions only on parents

Architecture review of the top-level scripts/ restructure returned RECONSIDER. This ticket describes the reshape, not the blocked original plan. Implementation agent 338f11a1-e496-4c63-b886-17efe958ffec is applying the reshape now.

Require the git revision only on the parent entry of measure_preparation_resources.py, measure_alias_preparation.py, and probe_corpus_recovery_memory.py. Worker and child respawns keep working. Docstrings point at preparation-readers.md and evidence/preparation-memory.json, preparation-aliases.md and evidence/preparation-aliases.json, and for the probe state that no saved receipt exists so the parent argument is the baseline.

## Acceptance Criteria

- measure_preparation_resources.py, measure_alias_preparation.py, and probe_corpus_recovery_memory.py require the git revision only on the parent entry.
- Worker and child respawns of those three scripts still run.
- The measure_preparation_resources.py docstring points at preparation-readers.md and evidence/preparation-memory.json.
- The measure_alias_preparation.py docstring points at preparation-aliases.md and evidence/preparation-aliases.json.
- The probe_corpus_recovery_memory.py docstring states that no saved receipt exists and that the parent argument is the baseline.


## Notes

**2026-10-19T18:10:39Z**

3fbeb43f7d658a395bf9172a416bb5df59f944b7 Require an explicit baseline revision for the measurement runners.

## Audit 2026-10-24

- Verdict: LANDED-SOUND (batch standalone).
- Grades: proposal 72 → 72, work 84 → 84.
- Problem: No material finding.
- See docs/reviews/2026-10-24-ticket-audit/README.md
