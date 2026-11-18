---
id: ct-31qi
status: in_progress
deps: []
links: []
created: 2026-11-17T18:18:49Z
type: task
priority: 1
assignee: mikewolfd
tags: [hosted, publish, ci]
---
# Keep the built candidate between hosted runs and resume at the gates

Root cause 2 of .cache/archive-release/investigations/etl-rca-20261117/RCA.md. Hosted runners keep nothing, so a gate stop answered by a cause record repeats a 22-minute, 10 GiB model build of an identical candidate. On 2026-11-17 ten builds produced five distinct candidates. The controller already has a resume path (completed-model checkpoint); nothing carries the candidate between runs.

## Acceptance Criteria

A hosted publish that stops after its build, re-run with the same inputs, reaches the gates without rebuilding the model, and a run whose inputs changed rebuilds. Proven by tests and by one real stopped-then-resumed run.

## Notes

**2026-11-17**

Merged as pull request 192 (ad2e2efe): the publish job restores the newest kept candidate from the Actions cache (about 178 MiB), resumes it when its files are intact and its inputs and selected release are this run's, and otherwise deletes it and builds fresh. Tests cover resume, changed inputs, changed definitions, damaged files and a candidate that is already live.

Kept open for the second half of the acceptance: one real stopped-then-resumed run. On the next night the gates stop, after the cause record is merged and main has validated it, the re-run's log should say "Resuming the kept candidate" and its publisher step should take minutes, not about 25. If it says "Building fresh; kept candidate discarded: ...", the reason names what differed; record it here.

Every normal night now passes through this code too (yesterday's candidate is restored, found to be another night's, deleted, and a fresh build runs), so the first scheduled night after the merge is its first production check.

**2026-11-18T19:13:34Z**

2026-11-18: first real stop-then-re-run, and it did NOT resume. Run 44356863837 (commit b15dca5b) built candidate ca6e7adbfacf and stopped at the checks; the cause record merged as 48c49900; run 44373468129 restored the cache (key archive-publish-candidate-5cd22df7…), printed 'Resuming the kept candidate if its inputs are this run's' and then 'Building fresh; kept candidate discarded: Publication continuation inputs differ from the completed model', rebuilt (about 13 minutes), produced the same candidate id and published. No capture ran in between. So the saving this ticket exists for did not happen in its main use. Root-cause analysis by Codex is running (.cache/archive-release/investigations/kept-candidate-not-resumed-20261118/).

**2026-11-18T19:27:21Z**

2026-11-18 root cause and fix. Codex (gpt-6.2-astra, xhigh; greybeard + etl-workflow; report .cache/archive-release/investigations/kept-candidate-not-resumed-20261118/codex-rca.md), checked here against the code: run_publish's continuation identity hashed the whole model spec; each provenance row in it carries the local path its record was downloaded to; a hosted run is not in 'resume' mode, so it runs produce_daily_inputs afresh and provenance_inventory._download names each file <sha of key>-<fresh uuid>.jsonl. The identity therefore differs on every hosted re-run, and the kept candidate could never be resumed. The existing tests use empty provenance lists. The cause-record commit and the ticket-only commits do not enter the comparison. Not established: that the path was the only differing input (the old checkpoint stores one digest, not its parts).
Fix: pull request 207. The identity leaves out a provenance row's path (key, sha256 and size stay; every other path still counts), is built from one digest per input, and those digests are saved with the candidate so a refused resume names what differed. Tests cover both directions, and the path test fails without the fix.
Held on purpose: archive_controller.py is in the model definition hash, so merging it stops the next publish for a cause record. Merge after the scheduled night of 2026-11-19, then run a publish by hand: that stop, its record and the re-run are the first real test of the resume. Keep this ticket open until a hosted re-run reaches the checks without rebuilding.

**2026-11-18T20:15:22Z**

2026-11-18 20:15 UTC: pull request 207 merged (df37d3b2) on the owner's decision 'Merge now'. Plan the same evening: once main validates it, a capture and publish by hand; that publish stops at gate 1 for the definition change (archive_controller.py), the cause record is merged, and the re-run is the first real test of the resume. Expected re-run log line: 'Resuming the kept candidate if its inputs are this run's' with no 'Building fresh'. If it still rebuilds, the refusal now names the differing inputs.
