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

## Cost and memory samples

**`publication_costs.py`** counts bytes, hashes, and resident memory while a fixture runs. The numbers describe that process. They do not permit a publish.

**`compare_publication_costs.py`** compares two such trials when the fixture and the measured work match.

**`measure_publication_control.py`** runs one small pinned fixture against a checkout you name, so you can compare a change with the current publisher on the same input.

**`measure_alias_preparation.py`** times alias indexing on a fixture with many names pointing at the same documents.

**`measure_preparation_decoded.py`** times decoded viewer preparation and records whether worker memory stayed under a sampled ceiling.

**`measure_preparation_resources.py`** compares in-memory catalog state and navigation buffers before and after a change, offline.

**`probe_corpus_recovery_memory.py`** compares resident memory on synthetic recovery inputs. It uses no network, no credentials, and no retained documents.

**`process_rss.py`** samples resident memory for a process and its children. The other measurements import it. You do not need to run it directly.
