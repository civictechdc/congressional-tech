---
id: ct-2c0w
status: open
deps: []
links: []
created: 2026-11-01T20:08:14Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [runtime, ci, cutover]
---
# Correct the linux-amd64 pin and DOCSPEC_RUNTIME_ARTIFACT for engine eb40c54

Commit 052b6111 moved the pin to eb40c54 but updated only the darwin digest. The linux digest and repository variable still describe the 0cbad87 build, so setup-native-runtime.py:68 refuses it; every offline shard of validate run 41149337076 failed this way.

## Design

Cross-build eb40c54 from git archive with the retained Dockerfile.cross recipe, using --release to match the darwin build. The earlier recipe used a debug profile. Qualify with engine-linux-qualify.sh, upload create-only through publish_docspec_runtime to congressional-tech-runtime with readback, update the pin digest and the repository variable, and keep the prior variable for rollback.

## Acceptance Criteria

- setup-native-runtime.py accepts the descriptor.
- Validate Congress MCP and Validate Committee Explorer get past runtime setup.
- No disabled workflow is enabled by this ticket.

