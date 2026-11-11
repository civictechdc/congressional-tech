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


## Notes

**2026-11-10T17:00:46Z**

2026-11-10: built (four commits on claude/dx-client-evidence, last e1a9b490) and independently reviewed: no must-fix; ship from the greybeard, etl-workflow and evolutionary-refactoring views. Review fixes decided by the manager, to be applied test first: (1) a failed job whose log file is gone must still raise the engine failure with its report, not FileNotFoundError (client.py:346); (2) the signature check in provenance.run_job that passes log only to engines that accept it is a test accommodation in production code and fails silently: pass log always, let the 27 test doubles in 19 files accept it, add one test through PublicationRuntime; (3) .code taken from the stdout report has no production reader and overlaps PRE_ADMISSION_ERROR_CODES: remove; (4) metric_events skips a last line that has no newline: fix; (5) correction of a claim: 'no step events kept before' holds only without DOCSPEC_STEP_LOG, which the nightly already sets (5,106 events in the 12:15Z run's steps.jsonl), so engine.log adds per-job attribution and the non-metric text. Open asks with the coordinator: the nightly driver deletes engine.log with a retired candidate (scripts/nightly_publish.py:219-233); the model build calls the engine directly (archive_format.py:357) and gets no log, which belongs with the model-only build command and the runtime-evidence change. Measured on the failed nightly's own text: 808 metric lines and 202,201 characters before the error, now 0 lines and 50 characters; whole message 202,583 to 508.

**2026-11-11T00:18:36Z**

Reading evidence: W1 moved workspace_sha256 for sniff, readings, pdf_text, html_text, xml_text and warc. Recorded as equivalence in f6615f13 (claude/dx-reading-evidence), with every declared version kept and the six values re-stamped. Not a reader: daily.py:1363's activation byte limit now counts engine.log.

**2026-11-11T00:22:00Z**

2026-11-11 from the reading-evidence review: since W1, engine.log files (231 to 10,850 bytes in fixtures) land in job work folders, so byte limits that sum a work folder now count them: lake/daily.py:1363 (record activation, max_output_bytes from the activation job) and archive_house_xml_dispositions.py:126. Not a reader effect. Check the configured limits against a worst-case engine.log before the next hand-run activation, or exclude engine.log from those sums.
