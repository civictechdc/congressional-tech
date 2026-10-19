---
id: ct-57gf
status: in_progress
deps: []
links: []
created: 2026-10-19T15:46:23Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-snh8
tags: [package-cleanup, behavior-preservation]
---
# Make shared configuration imports side-effect free

congress_shared.globals configures root logging and mixes bundled resources with command output defaults. Move logging setup and output-path selection into explicit command setup while preserving existing default locations and flags.

## Acceptance Criteria

Imports do not change root logging or create/write files. CLI logging, arguments, path values, credentials and outputs remain compatible. Preserve bundled reference data. Check all affected command entrypoints with focused offline tests.


## Notes

**2026-10-19T15:46:23Z**

Implementation authorized in an isolated worktree. Preserve source data and production workflows. Ticket closes after focused checks and independent review; parent tracks merge completion.

**2026-10-19 implementation, pending independent review**

Separated bundled references (`resources`), existing writable defaults (`paths`), and explicit command setup (`cli`). `globals` retains its public constants and argument-helper aliases. All nine affected entrypoints explicitly select the previous INFO/stdout format, including the indirect `congress-committees` caller. Removed the ineffective second logging setup in `hearing-transcribe`. Library imports now leave root logging unchanged; output/cache paths retain their exact package-relative values. Credentials, source data, dependencies, workflow definitions, and command return behavior are unchanged.

Traced every Python import of `congress_shared.globals`, package console-script declarations, module wrappers, and workflow/replay references. No maintained Python caller still relies on the compatibility module. Existing command arguments still select their output locations; library function defaults remain available.

Validation: own worktree `uv sync --frozen`; 129 focused tests passed across shared import/setup, Congress CLI/boundaries/import fences, YouTube interpretation/fetch fidelity, committee metadata/details, and transcript regression tests. New checks audit imports for filesystem writes with both empty and configured root logging, exercise all nine entrypoints through help, check default/explicit argument types and output paths, preserve credentials and exact missing-key errors. `uv build --package congress-shared --wheel` passed; extracted wheel imported cleanly and both bundled resources matched source bytes. `git diff --check` passed.

Concrete improvement: importing collectors/readers no longer configures application logging; each responsibility has one maintained owner. Compatibility aliases reuse those definitions. No speed/resource claim or live-source qualification is made. Full pipeline replay and remote operations were outside this focused configuration change. Status stays `in_progress` until independent review and parent merge.
