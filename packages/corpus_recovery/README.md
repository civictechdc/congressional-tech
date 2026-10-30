# Corpus recovery

Python library that checks recovered committee documents and adds them to the raw archive.

Committee sites and the Library of Congress Web Harvest sometimes hold a hearing PDF or HTML page that the archive does not. This package is the code that turns a reviewed local copy into archive rows and, later, into a catalog update. The commands you actually run are in [`scripts/corpus_recovery`](../../scripts/corpus_recovery/README.md). Import this package when you are calling that logic from another command or a test.

```python
from corpus_recovery.reconcile import import_retained, reconcile
```

Import each operation from its owning module.

The package is installed with the rest of the workspace (`uv sync --locked`). It does not download documents. Fetching from Web Harvest is [`scripts/webharvest`](../../scripts/webharvest/README.md).

## What you can ask it to do

| Module | Role |
| --- | --- |
| `html` | Reads archived HTML and labels it: a real document body, an empty page, a "no prepared statement" page, or an error or challenge page. The caller still has to check the archive digest, the source URL, and any URL that was deliberately deferred. |
| `govinfo` | Validates a downloaded GovInfo ZIP and retains all members and its acquisition receipt, independently of the selected document's recovery mapping. |
| `inventory` | Loads a sealed batch, compares it with objects already stored, and checks that a file's digest still matches the manifest. |
| `reconcile` | Reconciles accepted recovery mappings against raw captures, stages provenance rows, and imports retained bodies through the common receipt writer. |

## What it will not do

It will not treat a download as success. A batch is usable only when the named files match the hashes recorded in its manifest.

Accepted recovery labels enter raw as provenance records and are consumed by the
archive model and publisher; the old catalog/viewer publication and shared-index
import dispatchers are retired.
