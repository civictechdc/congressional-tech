---
id: ct-ma8a
status: closed
deps: []
links: [ct-esm4, ct-n3qy, ct-vxzu, ct-fqgf, ct-vd5b, ct-r46l, ct-70kc]
created: 2026-10-19T17:00:40Z
type: task
priority: 2
assignee: mikewolfd
tags: [script-restructure]
---
# Package viewer publication after setup only

Architecture review of the top-level scripts/ restructure returned RECONSIDER. This ticket describes the reshape, not the blocked original plan. Implementation agent 338f11a1-e496-4c63-b886-17efe958ffec is applying the reshape now.

Keep scripts/viewer_release_identity.py as a real stdlib module in scripts/ because publication_preflight.py runs before uv sync. Do not replace it with a shim that imports an installed package. This package does not depend on moving viewer_release_identity.

Package only guarded_recovery_publication_client, recovery_publication_continuation, viewer_publication_attempt, and publication_verification. If publication_verification moves, live_observation takes an explicit repository root. publication_cli git rev-parse stays on the checkout root. If a workspace member is added, update uv.lock, test-suites.toml [environment.imports], .github/actions/setup-python-project description, and docs/development.md in the same change. Pin source_files and RecoveryGuard at the files that execute. Shims are temporary debt.

## Acceptance Criteria

- scripts/viewer_release_identity.py remains a real stdlib module in scripts/ and is not a shim that imports an installed package.
- The package contains only guarded_recovery_publication_client, recovery_publication_continuation, viewer_publication_attempt, and publication_verification.
- publication_preflight.py still runs before uv sync without importing the new package.
- If publication_verification moves, live_observation takes an explicit repository root.
- publication_cli git rev-parse stays on the checkout root.
- If a workspace member is added, the same change updates uv.lock, test-suites.toml [environment.imports], .github/actions/setup-python-project description, and docs/development.md.
- source_files and RecoveryGuard are pinned at the files that execute, not only at shims.
- Any shim left behind is recorded as temporary debt.


## Notes

**2026-10-19T18:10:39Z**

1b86cd6e75f9a9c54808e6dcdf859ffd17838ccb Package viewer publication code that runs after workspace setup.

## Audit 2026-10-24

- Verdict: LANDED-CONCERNS (batch standalone).
- Grades: proposal 83 → 74, work 76 → 76.
- Problem: Partly reversed by ac7e09a9 (ct-unv0): `scripts/viewer_release_identity.py:8-12` is now a sys.path shim onto `viewer_publication.release_identity`.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/standalone/standalone-verdicts.md:21
- Covered by: WS6 (ct-qqk2), which deletes `scripts/viewer_release_identity.py`.
- See docs/reviews/2026-10-24-ticket-audit/README.md
