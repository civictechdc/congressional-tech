---
id: cef-adn6
status: closed
deps: []
links: []
created: 2026-10-27T12:00:28Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, C7]
---
# C7: bind the existing native client to SQL jobs

## Acceptance Criteria

SQL job calls reuse NativeDatasets binary verification and process invocation, require explicit limits and artifact pins, refuse remote lifecycle configuration, and preserve completed output identities on native failure. Project runner covers the injected executable adapter.


## Notes

**2026-10-27T12:07:27Z**

Reused NativeDatasets._call and verify_runtime for job dispatch. Explicit limits plus binary/source pins required before execution; remote lifecycle configuration refuses. DocSpecFailure retains stdout/completed outputs. Seven injected executable-adapter checks and all15docspec_client checks pass through production-offline (cx_c7_client_tests.log,cx_c7_client_suite.log).
