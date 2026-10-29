# Corpus recovery

Python library that checks recovered committee documents and adds them to the raw archive.

Committee sites and the Library of Congress Web Harvest sometimes hold a hearing PDF or HTML page that the archive does not. This package is the code that turns a reviewed local copy into archive rows and, later, into a catalog update. The commands you actually run are in [`scripts/corpus_recovery`](../../scripts/corpus_recovery/README.md). Import this package when you are calling that logic from another command or a test.

```python
from corpus_recovery.admission import verify_import
```

Import each operation from its owning module. Importing this package or its admission checks leaves the archive implementation unselected until a caller needs it.

The package is installed with the rest of the workspace (`uv sync --locked`). It does not download documents. Fetching from Web Harvest is [`scripts/webharvest`](../../scripts/webharvest/README.md).

## What you can ask it to do

| Module | Role |
| --- | --- |
| `html` | Reads archived HTML and labels it: a real document body, an empty page, a "no prepared statement" page, or an error or challenge page. The caller still has to check the archive digest, the source URL, and any URL that was deliberately deferred. |
| `assemble` | Builds the capture rows and ZIP receipts for one sealed batch, offline. |
| `govinfo` | Validates a downloaded GovInfo ZIP and retains all members and its acquisition receipt, independently of the selected document's recovery mapping. |
| `transfer` | `import_batch` writes those bodies and index rows. Each write is conditional. An uncertain response is reconciled by reading the object back, not by repeating the upload. |
| `inventory` | Loads a sealed batch, compares it with objects already stored, and checks that a file's digest still matches the manifest. |
| `admission` | `verify_import` checks that an import finished and that the readiness report still matches the batch. |
| `mappings` | Merges filename decisions onto the current accepted map, then publishes that map. A conflicting edit to an old decision is refused. |
| `guards` | `RecoveryGuard` and `active_cloud_writers` refuse a write when another job still holds the archive, or when the local pins have changed. |
| `preservation` | Compares the imported index with the baseline so existing rows are still present and new rows are only the ones this batch added. |
| `acknowledge` | After a lost upload response, reads the object that is actually stored and decides whether the write landed. It does not upload again. |

## What it will not do

It will not treat a download as success. A batch is usable only when the named files match the hashes recorded in its manifest. Import commands default to that check. They write only when the caller passes `--execute`.

Accepted recovery labels enter raw as records in `recoveries/accepted.json`. The
archive model and publisher consume them; the old catalog/viewer publication
dispatcher is retired. Raw guards, admission, body custody and mappings remain.
