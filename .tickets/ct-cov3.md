---
id: ct-cov3
status: open
deps: []
links: []
created: 2026-10-30T18:34:44Z
type: feature
priority: 2
assignee: mikewolfd
tags: [phase-2, retention, spicy-regs, release]
---
# Harden external release pin contract and stale-pin handling in archive_maintenance (ss-vhi2)

Per `docs/engine-first-architecture.md` §8.5 and §10.3.7 and `spicy-stack` ticket `ss-vhi2` item 4 (`L2-A3`), `spicy-regs` reads `congressional-tech`'s release files (`meetings`, `witnesses`, `recordings`, `urls`, `sources`, `list`, `detail`) pinned by `release_id` and publishes a pin list of the archive releases it consumes.

`packages/viewer_publication/src/viewer_publication/archive_maintenance.py` (`maintain_releases`, `prunable_release_ids`, `kept_input_records`) already accepts an `external_pins` parameter and has baseline tests in `packages/viewer_publication/tests/test_phase2_release_pruning.py`, but three production hardening gaps remain:
1. The wire format and object key / URL for `spicy-regs`'s archive release pin file are not yet wired into a reader helper in `archive_maintenance.py`.
2. If `external_pins` contains a stale `release_id` whose `releases/<id>/inputs/` prefix was already pruned before the pin was published (or never existed), `kept_input_records` raises `ValueError(f'Kept release has no input record: {release_id}')` and aborts maintenance.
3. In `archive_maintenance.py:177`, `store.write_spicy_generations(spicy_generations)` is only called when `execute and deleted`, so if a newly pinned release is added when no old release is deleted on that run, `pins/spicy-generations.json` is not updated.

## Design

Owners: `packages/viewer_publication/src/viewer_publication/archive_maintenance.py` and `packages/viewer_publication/tests/test_phase2_release_pruning.py`.

1. **Pin-file wire contract (`pins/archive-releases.json`, shared with `L2-A3`):**
   - Support reading `viewer-publications/pins/archive-releases.json` (or an explicit pin URL/path) with schema:
     ```json
     {
       "version": 1,
       "updated_at": "2026-10-30T18:00:00Z",
       "releases": ["<64-char lowercase hex release_id>"]
     }
     ```
   - Validate `version == 1` and 64-character hex `release_id` entries; if fetching/parsing the configured external pin source fails, fail closed (raise before deleting any release prefix).
2. **Tolerate stale external pins that are no longer present in `releases/`:**
   - In `maintain_releases`, `live` and `last_good` must still strictly exist and have `inputs/<input_digest>.json` records.
   - For `external_pins`, filter against the set of `existing_releases` present in the bucket (logging/returning `stale_external_pins` in the maintenance summary when an externally pinned release is not in `existing_releases`) so a lagging external pin never bricks `kept_input_records`.
3. **Unconditional `write_spicy_generations` when `execute=True`:**
   - In `archive_maintenance.py:177`, call `store.write_spicy_generations(spicy_generations)` whenever `execute=True` (not only when `deleted` is non-empty).

## Acceptance Criteria

- `read_archive_release_pins` parses and validates the v1 `pins/archive-releases.json` payload and fails closed on network/schema errors when an external pin source is configured.
- If `external_pins` names a `release_id` absent from `existing_releases`, `maintain_releases` records it in `stale_external_pins` without crashing `kept_input_records`, while still failing closed if `live` or `last_good` lacks an input record.
- `store.write_spicy_generations(spicy_generations)` is written whenever `execute=True`, even when `deleted == []`.
- Unit tests in `test_phase2_release_pruning.py` cover the v1 pin-file schema, stale external pins, and `execute=True` with zero deletions.

## Notes

**2026-10-30T19:28:54Z**

Also linked with ct-vnkf maintenance spec alignment: ensure archive_maintenance.py fetches spicy-regs' published archive release pin list (failing closed if unreachable), syncs viewer-publications/pins/spicy-generations.json across all kept releases, and binds raw_verification and lake_maintenance in model/jobs/maintenance.json.
