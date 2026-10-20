# Keep independent raw-leaf builds

The bounded local experiment does not justify replacing `RawStorage._candidate`
with native `Update`. Keep the existing build path. Update was slower for every
changed case and retained more new files/bytes. It also advances the leaf's native
latest version before the application conditionally selects its coherent raw
snapshot. An unselected native candidate can therefore block another update from
the application's still-selected pin.

This is the measured no-change outcome allowed by `ct-eipa`. The only production
change explains the reason beside `_candidate`; one regression preserves it. No
runtime configuration, credentials, provider, production data, selector or mapping
was read or changed.

## Comparison

Run from `codex/docspec-keyed-updates`, based on `3c0816c2`, using the real local
DocSpec CLI from source revision `91eb44f520221ec91897403e930d23f491b5ffd0`.
The binary SHA-256 checked after execution was
`817831a55c4273d79b8a9653a0a0248caa3648242b7f5cbb6200164c62864dbb`.

The script uses the actual raw native state schema, the maintained unsigned/binary
storage mapping, and the existing `_candidate` build method. The experimental
update adapter lives only in the measurement script and submits changed complete
rows/deletion keys to the existing native `Update` wrapper. Each changed operation
reads the same old pin first, then writes either the complete 16-row bounded leaf
or its changed rows. An append produces 17 rows; deletion produces 15.

Three repetitions cover each arm, case and unrelated population: 48 cases. Native
CLI processes are fresh for each command. Each scale/arm has a separate local
workspace, with one or ten unrelated 16-row datasets. Those unrelated datasets
are outside the changed leaf, matching the application's existing partition
isolation. Command and native processing scan counts remain the same with more
unrelated data; complete native physical reads are not instrumented. This does
not measure a tenfold larger changed leaf. Cases reverse order on alternating repetitions; Build and Update
arms run in groups. Cache state and other machine activity are uncontrolled, so
the timing difference between the two population sizes is not a scaling claim.

Median complete leaf-operation wall time in seconds includes the common exact
source read, preparation, hashing, native admission/processing/validation and
release. Independent result/old-pin verification and inspect calls happen after
the timed interval for both arms.

| Case | Build, 1x | Update, 1x | Build, 10x | Update, 10x |
| --- | ---: | ---: | ---: | ---: |
| Append | 0.3954 | 0.6473 | 0.3692 | 0.7842 |
| Correction | 0.4013 | 0.7182 | 0.3838 | 0.7841 |
| Delete | 0.4052 | 0.7555 | 0.3753 | 0.7414 |
| Guarded no-op | 0.0230 | 0.0273 | 0.0232 | 0.0248 |

Native processing counters for the 1x fixture follow. The exact per-run counters,
including the small correction/delete byte variation at 10x, are in the receipt.
These are native counters, not estimates from producer Parquet sizes.

| Case/arm | Files scanned | Files reused | Data files written | Bytes written | Bytes reused |
| --- | ---: | ---: | ---: | ---: | ---: |
| Append Build | 0 | 0 | 1 | 24,560 | 0 |
| Append Update | 1 | 1 | 2 | 7,439 | 22,211 |
| Correction Build | 0 | 0 | 1 | 22,226 | 0 |
| Correction Update | 2 | 0 | 4 | 41,998 | 0 |
| Delete Build | 0 | 0 | 1 | 22,167 | 0 |
| Delete Update | 2 | 0 | 3 | 35,473 | 0 |

Build's zero native processing file scans do not mean zero reads: both arms issue
one exact source read returning 33,352 Arrow IPC bytes. Build issues `read`,
`hash`, `run`; Update issues `read`, `hash`, `update`, plus a second `hash` for
deletion keys. Producer hash bytes are separately recorded. Source schema
restoration and ordering happen before comparison. Guarded no-op issues only
`read`, and exact workspace inventories prove zero persistent writes in both arms.

Update append reduces its native data bytes, but the median new retained file
bytes rise from 193,635 to 373,540 in the 1x fixture. Correction rises from 191,303
to 423,551; deletion rises from 191,229 to 400,102. These totals count new files
after request scratch cleanup; they exclude changes to existing catalog files and
are not physical disk-write totals. Native exposes `files_scanned` and write-byte
counters, but no complete physical disk/network read-byte counter through this CLI.
The receipt therefore reports observed returned IPC bytes and native counters
separately. It makes no claim about total native physical I/O or R2 throughput.

## Preservation and selection

Every case checks exact expected values and original schema types after reading
the new pin, and exact old values after reading the original pin. The fixture
includes null URL, nested duplicate values, nested nulls, empty binary values and
maximum `uint64`. Old source-object hashes and every unrelated source-object hash
remain unchanged. Completed Update retries work with the original replacement
and deletion producers removed and leave the complete workspace inventory exact.
An operation using a different identity against that old base refuses
`stale_base`.

The added real-native regression reproduces the ownership mismatch through an
actual `RawStorage` snapshot: publish states, update its native leaf without
publishing the application selector, confirm the selector/old values remain
unchanged, then attempt another native update from that selected pin. Native
refuses the old base. The existing independent candidate Build still prepares and
publishes a correction from the same application-selected base, preserving the
other URL and old snapshot. Thus sharing native latest would change the existing
preparation/concurrency behavior, even if a larger append fixture later improved
its timing. Adding locks, branch-copy builds or selection repair to compensate
would increase work and policy for this already-bounded leaf path.

Raw capture history remains append-only, including duplicate captures in source
order. Raw state input remains keyed upsert, with duplicate URL keys refused and
stable state ordinals. The public raw API has no state/capture deletion operation;
the delete comparison tests complete native leaf replacement only. This experiment
does not invent application deletion semantics or remove selected observations.

## Verification and retained evidence

Baseline: 14 tests passed in 14.33 seconds. Final: 15 passed in 16.41 seconds:

```sh
DOCSPEC_BINARY=/Users/mikewolfd/Work/spicy-stack/docspec-rs/target/debug/docspec \
PYTHONPATH=packages/congress_api/src:tests \
/Users/mikewolfd/Work/congressional-tech/.venv/bin/python -m pytest \
  tests/test_raw_storage.py tests/test_docspec_boundary.py -q
```

The existing checks cover coherent capture/state selection, conflicting writers,
lost selection replies, completed delivery replay, deterministic operation
conflicts, capture duplicates/order, rich schema/null URL preservation, bounded
reads and no-op writes. The added regression covers the actual application/native
selection mismatch. The comparison's 48 cases all passed their independent
literal row/schema/hash/replay assertions.

```sh
PYTHONPATH=packages/congress_api/src \
/Users/mikewolfd/Work/congressional-tech/.venv/bin/python \
  scripts/measure/compare_raw_keyed_updates.py \
  --binary /Users/mikewolfd/Work/spicy-stack/docspec-rs/target/debug/docspec \
  --output output/docspec-reuse-20261020/updates/run-1 --rounds 3
```

The output directory must be absent on a repeat run. Full local workspaces and
the raw `results.json` receipt are retained under that output path and copied to
the primary checkout. A tracked copy of the receipt is
`docs/experiments/docspec-reuse/keyed-updates-results.json`.

## Upstream remote work remains separate

The checked native source explicitly permits remote initial independent Build and
source-only Update (`src/engine.rs:364`); it refuses other operation requests via
`require_local`. Native value/occurrence version comparison calls `require_local`
in `src/engine/comparison.rs:97` and `:191`. Therefore R2 version comparison/change
diagnostics (`ct-13cn`), occurrence evidence updates (`ct-sb0s`), and incremental
join/summary refresh (`ct-gziq`) need upstream engine remote support plus provider
preservation/recovery qualification. They cannot be enabled by a Python transport
wrapper or by this local Update measurement. None is implemented or qualified in
this lane.
