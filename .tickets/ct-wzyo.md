---
id: ct-wzyo
status: open
deps: []
links: [ct-4acu]
created: 2026-11-11T00:44:06Z
type: bug
priority: 3
assignee: mikewolfd
tags: [model, ledger, selective]
---
# The selective job's own model build runs with no retired-link ledger (archive_selective.py:481)

Found 2026-11-10 by W3's review (docspec-feedback refactor, model-only build command). archive_selective.py:481, step 9 (_model), calls archive_model_job.execute(validate_model(value,base=run.work)) with no prior_links or base_retired, so build_release gets an empty retired-link ledger: retired_links comes out empty and every key the base had retired vanishes from that build. This is the hazard the 2026-11-10 14:39Z model-only build hit (release 597a6416a5c8: '452 keys vanished', ct-4acu), which release-next/bm_execute.py then fixed by hand and archive_model_job --ledger/--ledger-base now fixes for the model-only command. What it affects here: step 9 checks the six model suites, relationship_invariants among them, whose retired-key checks (missing_retired_successor) see no retired rows, and records release_id and rows in run.state (archive_selective.py:488) for a release that differs from the one publication would make. Publication itself is not affected: the candidate spec it writes goes through archive_publish_job, whose controller runs the model again with the ledger it derives from the live release (release_gate.fetch_base), as archive_selective.py:15 says. Latent today: model/jobs/backfill-selective.json is blocked (no real-data run approved, ct-9gmr C7).

## Acceptance Criteria

Step 9 passes the ledger the publisher would pass (archive_model_job.ledger_files over the base the run selects, the same release_gate calls fetch_base makes), or the run state says in so many words that its release id and suite results were made with an empty ledger and why. A test with a base that carries retired_links shows the step-9 build's retired_links rows equal the publisher's for the same inputs.


## Notes

**2026-11-11T14:33:14Z**

validated 2026-11-11, left open: not fixed. archive_selective.py:481 still calls execute_model(validate_model(value, base=run.work)) with no prior_links or base_retired. Latent while model/jobs/backfill-selective.json stays blocked.
