# Unchanged recovery index reuse

The selected viewer pointer now binds the exact raw and release manifest bytes,
filenames/groups hashes, validated and sorted accepted mappings (including object
absence), the full Git revision, and installed Python package versions. A matching
refresh verifies the small selected status object and public path, then rereads the
raw selector, accepted object and viewer pointer. It reads no table bytes and makes
no writes. This proves current recovery inputs, not full remote catalog integrity.

A missing receipt or changed input rebuilds against the two verified immutable
files. Missing and empty accepted mappings still derive catalog aliases; refresh
never writes accepted.json. Explicit acceptance remains a separate operation.
Descriptor and input receipt select together through the original viewer ETag.

Verification (macOS arm64, Python 3.12.13, PyArrow 25.0.1): 35 focused tests passed
in 5.84 seconds. The matrix covers mapping edits with the same count, row deletion,
whole-object absence, empty mappings, code/runtime changes, corrupt status bytes,
concurrent raw/viewer/mapping changes, input validation and immutable publication
failures. The exact no-op tests assert zero table downloads, zero table-object
reads and zero writes for present, empty and absent accepted mappings.

Command:
`PYTHONPATH=apps/site/scripts:scripts .venv/bin/python -m pytest .github/tests/test_viewer_r2.py tests/test_filename_recoveries.py -q`
