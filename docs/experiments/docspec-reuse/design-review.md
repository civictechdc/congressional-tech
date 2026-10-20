# DocSpec integration: CS 300 review

These grades cover inspected paths, not the entire engine. A good grade requires
correct results, clear ownership, bounded resources, recovery after interruption,
and costs that fit the actual workload. Small fixtures establish correctness and
fixed overhead; scale experiments establish growth and any performance crossover.

| Path | Current assessment | Evidence and next action |
| --- | --- | --- |
| Dependency preparation | C for the preliminary typed cache; not approved | It preserves types and recovery, but reads input-ordered Parquet parts repeatedly for hash-ordered leaves. At 16,384 rows and 64-row leaves, it decoded 995,200 rows. Fix the layout before merging (`ct-adu0`). |
| Native `replace_keys` | B−; performance grade provisional | It probes each source file's keys and shares unchanged files. The prepared key relation is scanned for every probe and changed-file join. Measure rows, files, changed keys, and history separately (`ct-xl0y`). |
| Temporary key table | B after the proposed correction | A key-matching relation needs Parquet files, not a registered Iceberg table. Removing that registration preserves the maintained writer and protected attempt path. Red/green tests cover schema IDs, duplicates, nulls and retained failed work. This is a constant reduction, not proof of faster scaling. |
| Python/native transport | C before; replacement under review | A process per call and temporary Arrow read files repeat work. The persistent host removes those costs, but deadlines and producer-file lifetime must remain correct before adoption (`ct-q968`, `ct-copj`). |
| Import disk admission | C before; replacement under review | The old path reaches native disk refusal after preparing the corpus. Check preparation plus native scratch first, enforce the preparation budget, and reuse completed work (`ct-n7la`). |
| R2 feature coverage | Incomplete | Schema/backfill, evidence updates, refreshes, and comparisons still refuse remote storage. Extend the existing engine and qualify each operation; removing a backend guard alone is insufficient (`ct-dmca`, `ct-sb0s`, `ct-gziq`, `ct-13cn`). |

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
