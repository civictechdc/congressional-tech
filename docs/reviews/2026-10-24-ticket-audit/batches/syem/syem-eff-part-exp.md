# syem efficiency, export-pins publishing (part C)

Code: `viewer_publication/publication_cli.py:129-180` (export-pins), `filename_exports.py:736-1009` (`export_viewer_pins`), `client.py:266-349` (`publish_manifest_pointer`, `ConditionalManifestPublisher`). These files are identical at c858a5a2 and origin/main 56cca36d.

Measurement: `syem-eff-exp-measure.py`. It scales the `test_filename_exports._sample_tables` fixture to 20,000 rows with 18 columns, then runs the local path under cProfile at c858a5a2. Total 2.20 s:
- `publish_occurrence_parquet` ×2: 1.48 s. Self time is dominated by `filename_budget.python_estimate/containers`, 40,002 calls, about 22 µs each.
- `fold_source_readings_table`: 0.34 s.
- `_sort_components_table`: 0.13 s.
- `compute_facet_entries` ×2: 0.11 s.
- `_sort_sources_table`: 0.04 s.
- `file_identity` ×4: 0.002 s.

On the same table, the Arrow-native equivalents took 0.016 s (facets via `pc.value_counts`) and 0.027 s (`sort_by`).

Variables: N rows (1.68M filename rows), K columns (about 400 on the catalog tables, per the 4t6s pass), G row groups, O occurrences, F output files (4), P bytes per file.

## 1. The local path re-implements the docspec-rs export
- **Big O:**
  - Time: O(N·K) Python object creation in `compute_facet_entries` (`filename_exports.py:507`, `table.to_pylist()` of the whole table, called twice).
  - Time: O(N·K) in `_sort_components_table` (`:699-705`, whole-table `to_pylist` just to build a sort key).
  - Time: O(N log N) Python sort in `_sort_sources_table` (`:691-696`).
  - Time: O(O) Python decoded-size estimation (`filename_budget.py:44-52`, recursive `containers`).
  - Memory: O(N·K) Python dicts. At 1.68M × ~400 columns that is hundreds of millions of objects, likely more than RAM (reasoned, not measured at scale).
  - Measured per-row cost at K=18: about 110 µs per row overall. Extrapolated to 1.68M rows that is about 3 minutes before any K scaling (reasoned).
- **Do once:** each written file is read for its hash 2 more times on the publish path:
  - `file_identity` after the write (`:842,861,903,931` → `custody.verify_local_file`);
  - `put_immutable_asset` re-hashes it (`client.py:331-332`), because the CLI passes no `validation` (`publication_cli.py:163-165`), although the method accepts one (`client.py:327-329`);
  - then the upload reads it a third time.

  `compute_browse_ranges` (`:470-500`) also re-reads and decompresses every row group's key columns and takes min/max in Python, even though the file was written with `write_statistics=True`.
- **The easy way:**
  - docspec-rs `export` already does fold-readings, global sort, child tables, GROUPING SETS facets and browse ranges (`docspec-rs/src/export.rs:184-230,380-392`). It returns digest and bytes in `ObjectRef` (`model/id.rs:68-73`), and `export_viewer_pins` already has that path (`:763-818`).
  - If any local step had to stay: `pc.value_counts`, `Table.sort_by`, Parquet footer statistics (`metadata.row_group(i).column(j).statistics`), and passing the `file_identity` result as `validation=`.
- **Plan impact:** under decision 6 this settles WS6 step 6 without the timing exercise. Keep the native export and delete the local path:
  - `compute_facet_entries`, `compute_browse_ranges`, `fold_source_readings_table`, `_sort_*`, `build_export_pin_descriptor`;
  - `filename_budget.py` once `filename_native` goes (WS6 conditional).

  First add a parity test of local against native on the fixture, so nothing the viewer reads is lost.

## 2. Publishing does not use R2's own integrity primitives
- **Big O:** per release, O(F) PUTs plus O(F·P) local hashing. Fine in count; the issue is what gets verified.
- **Hard way:**
  - The SHA-256 is computed locally and only recorded in the receipt (`client.py:331-332, 347`). It is never sent, so R2 cannot reject corrupted bytes.
  - A 412 becomes `etag="existing-immutable"` with no comparison (`client.py:344-348, 376-380`; WS6 step 2 plans a byte comparison).
- **The easy way:**
  - Send `ChecksumSHA256=base64(digest)` on every create-only PUT. R2 then verifies the bytes server-side.
  - On a 412, `HeadObject(ChecksumMode='ENABLED')` compares the stored checksum in one small request, with no download.
  - The same primitive serves WS2's "one verifier" for raw `.gz`/`.pdf` collisions, provided raw writes also send the checksum.
  - Reasoned, not measured: R2's HEAD checksum echo needs one live probe, which I did not run (no network).
- **Native path:** the engine's export objects are already content-addressed (`ObjectRef.digest`). In remote mode they already sit in R2, so a server-side `CopyObject` with `IfNoneMatch` into `releases/<id>/` (or pointing the manifest at them) avoids the download and re-upload.
  - Today the CLI uploads `args.directory/*.parquet`, which the native path never writes (only `manifest.json`, `filename_exports.py:808`). A native-mode release therefore uploads no data files (reasoned from code).

## 3. Pointer flip
`publish_manifest_pointer` is one conditional PUT (`client.py:294-306`). That is the right primitive; leave it. The CLI never passes `expected_etag` (`publication_cli.py:172`), so a second release hits a 412 on `IfNoneMatch` and fails. That fails closed; WS6 step 1 covers it.
