# DocSpec integration: CS 300 & evolutionary-refactoring review

These grades cover inspected paths across `docspec-rs` (`main` at `22a804e`) and
the `congressional-tech` integration branch (`codex/docspec-reuse-integration`), not the entire repository. A good grade
requires correct results, clear ownership, bounded resources, recovery after
interruption, and costs that fit the actual workload. Small fixtures establish
correctness and fixed overhead; scale experiments establish growth and any
performance crossover.

| Path | Current assessment | Evidence and next action |
| --- | --- | --- |
| Dependency preparation (`ct-adu0`, `ct-wjce`, `ct-ccy4`) | A− (`ct-adu0`, `ct-ccy4` qualified) | Preliminary `75091e05` read input-ordered Parquet parts repeatedly for hash-ordered leaves ($60.7\times$ read amplification: 995,200 decoded rows at 16,384 rows / 64-row leaves). The `ordered.parquet` DuckDB external sort + sequential window reader fixes this while isolating `giant=1` rows and enforcing combined `parts + index + ordered.tmp + spill` budgets. Qualified at unchanged `SORT_MEMORY_BYTES = 128 MiB` (`134,217,728` B) on 46,080 rows (2,057-byte `evidence.bytes`): `sort_spill_peak_bytes = 35,520,512` B, `sort_buffer_peak_bytes = 243,351,552` B, `retained_bytes = 10,663,443` B, `index_bytes = 46,845,952` B, `ordered.parquet = 6,430,725` B, peak combined staging + spill `93,029,907` B (`<= 160 MiB` budget; deterministic `OSError` refusal at `80 MiB`), process `ru_maxrss = 614,039,552` B (`ct-ccy4`). |
| Native `replace_keys` (`ct-xl0y`, `ct-eipa`) | A− (`ct-xl0y` closed) | Unused key-table registration removed (`a0df449`). Across 129 scale cases (`82b32df` / `71128ece`), `Update` beats `Build` at 100,000 rows (`0.783s–1.027s` vs `2.095s–2.309s`, reusing unchanged files), while 8,192-row application leaves still favor `Build` (`0.538s` vs `0.834s`) and avoid advancing native `latest`. |
| Python/native transport & runtime qualification (`ct-copj`, `ct-bt1q`, `ct-3faj`, `ct-q968`, `ct-oxg6`, `ct-ugqq`) | A (`ct-3faj`, `ct-oxg6`, `ct-ugqq` closed) | `docspec-rs` `22a804e` (darwin-arm64 SHA-256 `bd17918e9512e87d923e39ce7512c59550d420946fdc33fb5046b0d3bbc4ce3c`) and `docspec.py` / `docspec_host.py` enforce loopback protocol 1 (`request-deadline`, `owned-stdin-eof`), retain `source.parquet` on `"worker"` / `"custody_quarantined"` failures, and bind `source_revision`, `platform`, `build_features` (`["remote"]`), `binary_sha256`, and `required_capabilities` in runtime descriptors and preflight checks (`setup-native-runtime.py`, `check-native-runtime.py`). |
| Import disk admission, operator status & protected retention (`ct-n7la`, `ct-qdkd`, `ct-a70m`) | A (`ct-n7la`, `ct-qdkd`, `ct-a70m` closed) | `native_capacity.py` checks preparation budget + native scratch + 8 GiB headroom across same/separate filesystems, exposes `inspect_operator_status` (combining `inspect`, `retained_producer_inputs`, stage receipts, and measured/estimated/unavailable resource counters with `DOCSPEC_*` secret redaction), and provides read-only `plan_protected_retention` protecting application release pins, export pins, active readers, incomplete operations, and unresolved producer inputs. |
| Nested `List`/`Struct` export (`ct-3li2`) | A (`ct-3li2` closed in `a9bca74`) | `src/engine/export.rs:636-640,878-940` recursively validates descendant `List`/`Struct` fields, strips non-`PARQUET:field_id` metadata, and counts primitive leaves for footer admission. |
| Native Parquet writer layout (`ct-cpio`) | A (`ct-cpio` closed in `a9bca74`, `22a804e`) | `src/engine/export.rs:591-601` and `src/storage.rs:344-365` enforce caller `Limits` (`max_batch_bytes` / `max_row_group_bytes`) without `.max(128 MiB)` override and remove hardcoded `news_lake` column names. |
| Lifecycle history, occurrence scans & predicate pruning (`ct-wmtx`, `ct-clvr`, `ct-mpsp`, `ct-csyg`, `ct-vt7i`) | A− (`ct-wmtx`, `ct-clvr`, `ct-mpsp`, `ct-vt7i`, `ct-csyg` closed) | `e3f01ac` compacts superseded revisions behind the oldest active `ReleasePin` and eliminates commit map clones (`ct-wmtx`). `8f0a878` reuses admitted current-snapshot file descriptors in `OccurrenceScan` (`22.9x` planning speedup at 32 snapshots, `ct-clvr`) and qualifies `Transform::Month` partition pruning via `snapshot_files_for_month_range` (`ct-mpsp`). `9ae57d9` qualifies hot-group `CountDistinct` (`ct-vt7i`). Because `OccurrenceScan` (`src/storage/occurrences.rs:187-193`) must preserve whole-file physical row ordinals (`__docspec_row`) and month partition pruning + `replace_keys` file probing already bound file reads, blind row filter pushdown and multi-file scan concurrency (which multiplies buffer admission) are intentionally not enabled without a separate values-only selective scan endpoint (`ct-csyg`). |
| R2 feature coverage (`ct-3180`, `ct-13cn`, `ct-dmca`, `ct-sb0s`, `ct-gziq`) | B+ (`ct-3180` local on `main` `b240765`; others open) | Remote `source`-group `compare`/`changes` works locally on `docspec-rs` `main` (`b240765`) and needs isolated R2 qualification (`ct-3180`) + Python diagnostic wiring (`ct-13cn`). Consolidate scattered `group != "source"` / `require_local()` checks into one `Engine` capability boundary as `ct-dmca`, `ct-sb0s`, and `ct-gziq` are implemented. |

For native updates, distinguish unchanged **file reuse** from avoiding **reads**.
With `F` source files and `C` changed files, the current implementation probes
`F` files and executes the prepared-key relation for `F + C` joins. Actual bytes
depend on key width, file layout, pruning and query execution; measure them.

For preparation, the important comparison includes decoding, file opens, peak
memory, additional temporary bytes, retained bytes, and restart cost. Replacing
compressed data with an uncompressed cache can exchange one bottleneck for
another. Prefer the maintained engine and storage primitives where they solve
the measured problem.

Before/after reports must identify the code revision, workload, resource limits,
and measurement scope. Report local and provider results separately. A passing
local test is not production adoption, and a cheaper tiny workload is not proof
of a scale benefit.
