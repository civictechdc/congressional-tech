# Reuse unchanged Committee Explorer publications

The published Parquet tables are now reusable maintained output. A matching
receipt lets the exporter skip parsing, model construction, matching, graph
validation, and table encoding. The publisher still verifies all retained file
hashes before using those bytes. It creates no additional copy of the model as
an intermediate cache.

The receipt covers every supplied input file, additions/removals of YouTube
files, ordered transcript inputs and their retained local URIs, selection and
format options, and an explicit `--as-of`. It also covers the exporter, adapters,
schema, bundled lookup tables, Python, Pydantic, and PyArrow versions. Persistent
IDs, issue-history bytes, and the original publication manifest must match.
Changes rebuild using the existing validated path. Frontend-only code changes
do not invalidate the data. Changing only the pipeline commit does not invalidate
unchanged source bytes: reused data keeps its original source revision and times.

CI restores the receipt with persistent state and supplies the existing browser
publication through `--reuse-from`. A clean runner can recover the original full
Parquet publication from those verified files. The public publication ID and
bytes remain identical after packaging. A missing receipt performs one normal
rebuild and creates the receipt for later runs. Corrupt published bytes fail
verification before the output pointer changes.

Validation on September 28, 2026:

- Integration tests export and package a fixture, restore state into a clean
  directory, prohibit model assembly, then verify that reuse and packaging
  reproduce the original publications exactly.
- Regression tests cover changed native facts with stable IDs; changed selection,
  explicit time, format, issue decisions, collection receipts, YouTube files,
  transcript names, code, schemas, lookup data, dependencies, and identity/history
  bytes; plus corruption and first-run behavior.
- On the local warm filesystem, hashing full retained inputs and code took
  **0.084 seconds**; hashing **903 MB** of IDs/history/manifest took **0.421 seconds**;
  verifying the **225 MB** Parquet publication took **0.116 seconds**; copying it
  took **0.210 seconds**. These constituent reuse operations totaled **0.83 seconds**.
  They were measured against existing full-data artifacts. This is not a
  full-size cache-hit or GitHub Actions timing; the fixture test exercises the
  complete reuse path. CI still installs packages, restores/packs state, and
  verifies/deploys the publication.

**Changed-input incremental updates remain unfinished.** Any changed input still
rebuilds the full combined model because matching and issue retention currently
depend on several source families. The existing retained repeat-build log reports
489.63 seconds for its earlier full JSON export; that historical measurement is
context, not a direct performance comparison with the current Parquet exporter.
Splitting changed-input work into independently maintained tables requires a
separate change with checks for cross-source links, deletions, and issue history.
