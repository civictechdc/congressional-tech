---
id: ct-eipa
status: closed
deps: [ct-xl0y]
links: []
created: 2026-10-20T18:24:28Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-mi03
tags: [docspec, efficiency, debt]
---
# Use native keyed updates where they reduce partition work

Measure existing immutable partition `Build`s against DocSpec `Update` for a supported raw-state/capture consumer. Preserve complete replacement/deletion semantics, old pins, source order and application selector. Adopt only where measured work is reduced.

## Acceptance Criteria

- Before/after identical append/correction/delete/no-op measurements including native reads/writes and actual elapsed time (`docs/experiments/docspec-reuse/keyed-updates.md` and `docs/experiments/docspec-reuse/native-update-scale.md` in `codex/docspec-keyed-updates`).
- Prove old pins and unrelated data remain unchanged, replay is safe, and `stale_base` is refused (`tests/test_raw_storage.py`, `tests/test_keyed_update_scale_experiment.py`).
- Because the application's current 8,192-row / 16 MiB partition leaves are below the observed 10,000–100,000 row `Update` crossover (`Build` 0.538s vs candidate `Update` 0.834s at 8,192 rows) and an unselected native `Update` advances native `latest` (`74cff4c9`), retain the simpler immutable partition `Build` path for 8,192-row leaves rather than forcing an unbeneficial runtime switch.
- Merge the `codex/docspec-keyed-updates` measurement receipts, scripts, and regression tests (`71128ece`) into `codex/docspec-reuse-integration` to close this ticket with its measured engineering decision.

## Notes

**2026-10-20T18:35:20Z**

User requested investigating fixes in DocSpec-rs before deciding on Build versus Update. Existing48-case receipt and ownership regression are baseline evidence. Decision remains open pending native optimization and remeasurement; no runtime path switched.

**2026-10-20T20:18:00Z**

CS 300 / evolutionary-refactoring audit reviewed `codex/docspec-keyed-updates` (`71128ece`). Grade: A−. The scale study establishes that `Update` wins at 100,000 rows (0.783s–1.027s vs `Build` 2.095s–2.309s, saving ~90% of written bytes via shared unchanged files), whereas at the application's 8,192-row partition leaf size `Build` remains faster (0.538s vs 0.834s) and avoids advancing native `latest` ahead of the application selector. Per `evolutionary-refactoring` ("Leaving sound code alone is a successful outcome"), integrate `71128ece` into `docspec-reuse-integration` and close `ct-eipa` with this documented decision.
