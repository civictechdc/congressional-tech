"""Finite local fixture budgets; production native configuration is independent."""
import json
from pathlib import Path

from congress_api.retention.docspec import NativeDatasets


def native_test_client(binary, workspace):
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    limits = workspace / 'test-limits.json'
    limits.write_text(json.dumps(dict(compute_threads=2, memory_bytes=512 << 20,
        scratch_bytes=256 << 20, batch_rows=2, max_batch_bytes=4 << 20,
        max_metadata_bytes=8 << 20)))
    return NativeDatasets(binary, workspace, limits=limits)
