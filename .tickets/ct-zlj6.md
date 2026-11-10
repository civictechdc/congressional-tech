---
id: ct-zlj6
status: in_progress
deps: []
links: []
created: 2026-11-10T15:46:19Z
type: task
priority: 1
assignee: mikewolfd
tags: [engine, client, observability]
---
# Client keeps the engine's log for every job and puts the error first

From the docspec-rs feedback root-cause analysis (cause E; .cache/archive-release/investigations/docspec-feedback-20261110/root-cause/ROOT-CAUSE.md). docspec_client captures the engine's stderr and drops it on success, so a passing job leaves no step numbers; on failure the whole stream is the exception text with the real error last. Change (additive): run_job(spec, log=...) writes the engine's stderr to a file as it is produced; provenance.run_job passes <job dir>/engine.log; DocSpecFailure's message leads with the engine's own code and message; one reader for metric lines. Branch claude/dx-client-evidence.

## Acceptance Criteria

A failing job's message starts with the engine's error, not a metric line; a passing job leaves its step events on disk; .stderr is unchanged; no existing caller has to change; measured on the failed nightly 20261110T111252 text before and after; six shards or a full lane pass; independent review done.

