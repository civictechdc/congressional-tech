---
id: ct-2c0w
status: closed
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


## Notes

**2026-11-01T21:08:34Z**

2026-11-01: built eb40c54 linux-amd64 from git archive with --release (rust 1.94.0, stripped): 195,663,208 bytes, SHA-256 c7b411adc3ef3d625e09b2c1d7be063a8398b7264eae43cd4a862854a743ee92. Under emulated linux/amd64: 54 tests passed, including native capture tests; serve flags and glibc 2.36 resolve. Not a live Ubuntu runner, and no corpus-scale check. Local files are in .cache/runtime-eb40c54. Pending: upload credential, pin digest, repository variable.

**2026-11-01T22:04:06Z**

Validate Congress MCP run 41354326013 passed. Validate Committee Explorer run 41354328062 passed runtime setup on all shards and 3 of 6 test shards. Its 3 test failures have causes other than a refused runtime; tracked in ct-31e2. Pin 3df9bdf6, variable set, rollback value in .cache/runtime-eb40c54/previous-DOCSPEC_RUNTIME_ARTIFACT.json. Corpus-scale behavior on Linux remains unmeasured.
