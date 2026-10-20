# DocSpec integration: CS 300 & evolutionary-refactoring review

These grades cover inspected paths across `docspec-rs` (`main` at `298053b`) and
the four `congressional-tech` worktrees, not the entire repository. A good grade
requires correct results, clear ownership, bounded resources, recovery after
interruption, and costs that fit the actual workload. Small fixtures establish
correctness and fixed overhead; scale experiments establish growth and any
performance crossover.

| Path | Current assessment | Evidence and next action |
| --- | --- | --- |
| Dependency preparation (`ct-adu0`, `ct-wjce`) | B+ in `docspec-typed-preparation` (was C in `75091e05`) | Preliminary `75091e05` read input-ordered Parquet parts repeatedly for hash-ordered leaves ($60.7\times$ read amplification: 995,200 decoded rows at 16,384 rows / 64-row leaves). The uncommitted `ordered.parquet` DuckDB external sort + sequential window reader fixes this while isolating `giant=1` rows and enforcing combined spill+output budgets. Run scale counters, commit, and cherry-pick into `docspec-reuse-integration`; evaluate `CatalogRows` `combine_chunks` copies in `ct-wjce`. |
| Native `replace_keys` (`ct-xl0y`, `ct-eipa`) | B+ for scale crossover; B− for key-discovery growth | Unused key-table registration removed (`a0df449`). Across 129 scale cases (`82b32df` / `71128ece`), `Update` beats `Build` at 100,000 rows (`0.783s–1.027s` vs `2.095s–2.309s`, reusing unchanged files), while 8,192-row application leaves still favor `Build` (`0.538s` vs `0.834s`) and avoid advancing native `latest`. Prepared-key relation still executes $F + C$ times; evaluate single discovery semi-join under `ct-xl0y`. |
| Python/native transport (`ct-copj`, `ct-bt1q`, `ct-3faj`, `ct-q968`) | A− for deadlines (`ct-copj`) & `SIGKILL` EOF drain (`ct-bt1q`); B for custody (`ct-3faj`) | `911228d` and `2308d23` on `docspec-rs` `main` plus `e95ff769` on `docspec-host-transport` bound request deadlines and drain owned hosts on parent `SIGKILL` via `stdin` pipe EOF. Remaining P2 gap: `docspec.py:233-235` treats HTTP 422 `"worker"` (quarantined custody) as cleanup-safe refusal; retain `source.parquet` on `"worker"` errors (`ct-3faj`) and run quiet-machine transport comparison (`ct-q968`). |
| Import disk admission (`ct-n7la`, `ct-qdkd`) | A− (`ct-n7la` closed) | `native_capacity.py` checks preparation budget + native scratch + 8 GiB headroom across same/separate filesystems before work and at bounded progress without re-walking directories. Expose operator progress/capacity view in `ct-qdkd`. |
| Nested `List`/`Struct` export (`ct-3li2`) | D — P1 bug on `docspec-rs` `main` (`715a8c2`) | `src/engine/export.rs:864-930` checks `List`/`Struct` at root only and clones child fields with their source metadata, while `:639-641` counts root columns instead of primitive leaves for footer admission. Recursively sanitize descendant fields and count primitive leaves before freezing `ct-oxg6`. |
| Native Parquet writer layout (`ct-cpio`) | C — P1 regression risk on `docspec-rs` `main` (`715a8c2`) | `src/engine/write.rs:437-455` forces `.max(128 MiB)` row-group bytes and `1_000_000` rows (overriding tighter caller `Limits.max_batch_bytes`) and hardcodes `news_lake` column names (`["resolution", "aboutness", "processor", "provider"]`). Restore caller `Limits` enforcement and remove domain-specific column names before `ct-oxg6`. |
| Lifecycle history & occurrence scans (`ct-wmtx`, `ct-clvr`, `ct-csyg`, `ct-vt7i`) | C− to B | 32 empty `Update`s slow single-row correction from `0.834s` to `4.326s` due to full row replay and map cloning (`src/catalog.rs:255-278,370-420`, `ct-wmtx`). Share current-snapshot file descriptors in `OccurrenceScan` (`ct-clvr`), qualify hot-group `CountDistinct` memory/spill (`ct-vt7i`), and sequence conservative inexact filter pushdown behind them (`ct-csyg`). |
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
