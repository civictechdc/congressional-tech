---
id: ct-xnn6
status: closed
deps: []
links: []
created: 2026-11-10T12:06:28Z
type: bug
priority: 1
assignee: mikewolfd
tags: [nightly, launchd, ops]
---
# Scheduled nightly fails at the end of the model and runs at half speed under launchd

The first two scheduled runs of 2026-11-10 after the launch agent was switched back on. (1) 11:12:52Z run failed at 11:59:16Z, step publish, exit 2, after the model had written its release files: 'Execution error: accepted_versions line 1: source open failed'. The input exists and is readable (nightly/candidate/archive-model/accepted_versions.jsonl.gz, 439 bytes). launchd starts an agent with 256 open files (launchctl limit maxfiles: soft 256); a shell here has 1,048,576, and every earlier completed build was shell-started. Probable cause, not proven: the engine exceeds 256 open files late in the job (scratch files for retained results, spill, 46 outputs, lake readers); the engine's message hides the errno. (2) The agent's ProcessType was Background, so the whole tree ran at priority 4 on the efficiency cores: daily about 19 min against 12, model 23 min against 11.4, 46 min in total against 25 from a shell. (3) A passing scheduled run left no step log. (4) The 10:30Z run refused at setup disk admission because uv.lock had moved and the budgets were not re-qualified (carried forward by hand).

## Acceptance Criteria

A run started by the launch agent completes the model and the publish step; its summary records the open-file limit it ran with; its wall time is close to a shell-started run; its folder holds steps.jsonl. The engine reports the OS error on a failed source open (engine follow-up, ct-n5ec's list).


## Notes

**2026-11-10T13:16:36Z**

2026-11-10 fixed on main af1da283. Scheduled run 20261110T121530.896579Z through the reinstalled launch agent: status ok, exit 0, open_files 65536 in summary.json, publisher release_unchanged; 26.7 min in all (46 at Background priority), publish step 1,579 s, peak 11.20 GiB RSS; steps.jsonl present in the run folder. Engine follow-up (OS error on a failed source open) is built on docspec-rs fix/nested-slice-bytes, tracked under ct-n5ec.
