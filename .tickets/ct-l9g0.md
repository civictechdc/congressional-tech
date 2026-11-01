---
id: ct-l9g0
status: closed
deps: []
links: [cef-9e9w, ct-oxg6]
created: 2026-10-30T14:32:31Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [phase2, ci, runtime, bindings, track3]
---
# T3.3: Consolidate the engine runtime pin file across setup and check scripts

Per docs/plans/bindings-20261025.md §3.1: replace environment-variable digest lookups in .github/scripts/setup-native-runtime.py, .github/scripts/setup-local-job-runtime.py, and .github/scripts/check-native-runtime.py with one committed pin file holding the engine revision and per-OS SHA-256.

## Acceptance Criteria

One committed runtime pin file holds the engine revision and per-OS SHA-256 digests, and setup-native-runtime.py, setup-local-job-runtime.py, and check-native-runtime.py read from it.


## Notes

**2026-10-30T19:28:54Z**

Reopened per Greybeard parity audit: (1) .github/scripts/setup-native-runtime.py:71-77 computes should_enforce = Path(pin_file).resolve() != Path(RUNTIME_PIN_FILE).resolve(), which evaluates to False on the default RUNTIME_PIN_FILE and skips checking value['sha256'] != pinned_digest; (2) .github/scripts/check-native-runtime.py:55 sets pin_file = None if binary_sha256 is not None else pin_file, bypassing pin-file verification when --binary-sha256 is passed.

**2026-11-01T03:09:00Z**

Enforced committed runtime pin platform digest by default in .github/scripts/setup-native-runtime.py:artifact_descriptor and install(), and ensured .github/scripts/check-native-runtime.py verifies explicit binary_sha256 overrides against the committed runtime pin file when a platform is present. Verified across .github/tests/test_native_runtime_setup.py, test_native_runtime_preflight.py, and test_local_job_runtime.py.

**2026-11-01T10:38:19Z**

Independent Validation Audit (2026-11-01, validator 2366732b):
- Verdict: PASS-WITH-CAVEATS (1/1 AC met; 57/57 tests pass across test_native_runtime_setup.py, test_native_runtime_preflight.py, and test_local_job_runtime.py).
- Remaining work before closure:
  1. [Priority 2] In `.github/scripts/check-native-runtime.py:50-67` (`verify_runtime`), require a resolved platform pin entry whenever `pin_file` is active (including when `--binary-sha256` is passed without `--platform`), or resolve the platform from the runtime / require `--platform` so explicit `--binary-sha256` cannot bypass `pin['platforms']` verification.
  2. Commit working-tree changes.

**2026-11-01T12:05:49Z**

Evolutionary Refactoring & Recursive Review Swarm Audit (2026-11-01):
- Refactored by Cluster 5 Engineer (4c90d67e, 99% confidence):
  1. Updated `.github/scripts/check-native-runtime.py:50-82` so passing `--binary-sha256` without `--platform` or `runtime.json["platform"]` still resolves and enforces the platform entry in `model/docspec-runtime-pin.json` (`test_native_runtime_preflight.py:72-104`).
- Recursive Review Swarm Verdicts (Round 2): Red Team PASS (99%), Green Team PASS (100%), Greybeard PASS (99%), Evolutionary Refactoring PASS (99%).
