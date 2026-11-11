# Measurement commands

Local timings and memory samples for the catalog rebuild and the filename viewer. Use them when you are deciding whether a change is cheap enough to adopt.

Every command here reads a fixture or a pinned local checkout. None of them fetch congressional sites, upload to R2, or authorize a publish. A timing result is evidence for a person. It is not a publication receipt.

Run from the repository root with the locked environment, for example:

```bash
.venv/bin/python scripts/measure/benchmark_catalog_grouping.py --help
```

## Catalog and viewer timings

**`benchmark_core_rebuild.py`** rebuilds retained source tables in a local overlay and compares every field with a pinned reference. Inputs stay read-only. CI runs it through `.github/scripts/offline-python.py`.

**`benchmark_catalog_grouping.py`** times grouping on a frozen local Parquet sample. It does not open R2.

**`benchmark_viewer_publication.py`** times the maintained viewer build. Each trial gets a new output directory. Failed logs stay on disk. It does not acquire source documents. Browser timings come from `benchmark_viewer_browser.mjs` against `viewer_benchmark_server.py`.

**`viewer_benchmark_server.py`** serves those already verified local viewer files over HTTP, with bounded byte ranges and browser CORS, so the browser benchmark can load them the way the public site would.

**`benchmark_viewer_browser.mjs`** drives Chromium against that local server. It does not publish.

**`main_content_cohort.py`** compares every `marked` main-content selection with the same element read by html5lib and with trafilatura, as ordered word runs in both directions, stratified by host and selector shape. Every body it reports as losing words is for a person to read in full. It reads retained bodies only.

`release_diff.py` moved into the publisher as `viewer_publication.release_comparison` (sides `--base`, `--candidate`); `viewer_publication.release_gate` runs it in the publish path.

## Cost and memory samples

**`publication_costs.py`** counts bytes, hashes, and resident memory while a fixture runs. The numbers describe that process. They do not permit a publish.

**`compare_publication_costs.py`** compares two such trials when the fixture and the measured work match.

**`measure_publication_control.py`** runs one small pinned fixture against a checkout you name, so you can compare a change with the current publisher on the same input.

**`measure_alias_preparation.py`** times alias indexing on a fixture with many names pointing at the same documents.

**`measure_preparation_decoded.py`** times decoded viewer preparation and records whether worker memory stayed under a sampled ceiling.

**`measure_preparation_resources.py`** compares in-memory catalog state and navigation buffers before and after a change, offline.

**`probe_corpus_recovery_memory.py`** compares resident memory on synthetic recovery inputs. It uses no network, no credentials, and no retained documents.

**`model_relation_rows.py`** reads one retained model build (its submitted job, step log and model spec) and writes the rows of every relation it scanned. `packages/viewer_publication/tests/fixtures/model-relation-rows.json` is its output; the repeat-cost lint (`test_phase1_model_repeat_cost.py`) scores repeated plan scans with it. Regenerate it from a newer nightly-shaped build when relation sizes move, then update the lint's tracked scores.

**`step_memory.py`** joins a watchdog timeline (`archive_watchdog.py --timeline`) to the engine's step log and prints the real memory of each statement, which statement the run's peak fell in, and the `--expect-gb` to start the job with next time. Each statement also carries its storage and the engine's compaction counts, or "not logged" where the binary writes none. To compare two runs, write each with `--json`, then run `--compare A.json B.json`: it lists the statements whose seconds, memory, pool peak, storage or counts moved, the statements in one run only, and the qualification's pass lines (ct-x00f). `--debug-log <engine stderr>`, from a run with `RUST_LOG=docspec=info,docspec::budget=debug`, adds each statement's lowest shared-budget `available` and its view copies and refusals. It needs only the standard library, so plain `python3` runs it.

**`process_rss.py`** samples resident memory for a process and its children. The other measurements import it. You do not need to run it directly.
