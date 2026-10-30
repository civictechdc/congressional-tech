"""Finite local fixture budgets; production native configuration is independent."""
import json
import os
import subprocess

import pytest
from pathlib import Path

from docspec_client.docspec import NativeDatasets
from docspec_client.binary import resolve_docspec_binary
from news_lake.storage.docspec import DocSpecClient as _NewsClient


def native_test_client(binary, workspace):
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    limits = workspace / 'test-limits.json'
    limits.write_text(json.dumps(dict(compute_threads=2, memory_bytes=512 << 20,
        scratch_bytes=256 << 20, batch_rows=2, max_batch_bytes=4 << 20,
        max_metadata_bytes=8 << 20)))
    return NativeDatasets(binary, workspace, limits=limits)


def native_test_util_binary():
    """Pause-hook checks require an explicit test-util build, never production."""
    binary = os.environ.get('DOCSPEC_TEST_UTIL_BINARY')
    if not binary:
        pytest.skip('Set DOCSPEC_TEST_UTIL_BINARY to the same-source remote,test-util build; production has no pause hooks')
    result = subprocess.run([binary, 'pause-after', '--help'], capture_output=True, timeout=10)
    if result.returncode != 0:
        pytest.fail('DOCSPEC_TEST_UTIL_BINARY does not provide the compiled test-util pause command')
    return binary


def require_native_docspec():
    """Skip absent local prerequisites; an explicitly configured bad path fails."""
    configured = os.environ.get('DOCSPEC_BINARY') or os.environ.get('DOCSPEC_BIN')
    if configured:
        return resolve_docspec_binary(configured)
    try:
        return resolve_docspec_binary()
    except FileNotFoundError:
        pytest.skip('Native DocSpec fixture requires DOCSPEC_BINARY or a local docspec executable')


_CI_PROFILE = dict(compute_threads=2, memory_bytes=2 << 30,
    scratch_bytes=2 << 30, batch_rows=8192, max_batch_bytes=8 << 20,
    max_metadata_bytes=32 << 20)


def native_ci_limits(workspace):
    """One stable profile for legacy native integration fixtures on CI."""
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    limits = workspace / 'ci-test-limits.json'
    encoded = json.dumps(_CI_PROFILE, sort_keys=True) + '\n'
    try:
        with limits.open('x') as output:
            output.write(encoded)
    except FileExistsError:
        if limits.read_text() != encoded:
            raise ValueError('Existing native CI limits differ from the shared profile')
    return limits


class NativeCITestClient(NativeDatasets):
    """Keep the native API and explicit overrides; bound omitted test limits."""

    def __init__(self, binary=None, workspace=None, *, limits=None, **kwargs):
        if limits is None:
            limits = native_ci_limits(Path.cwd() if workspace is None else workspace)
        super().__init__(binary, workspace, limits=limits, **kwargs)


class NewsCITestClient(_NewsClient):
    """Preserve the news adapter type, static methods and caller tight limits."""

    def __init__(self, workspace, binary=None, *, limits=None, **kwargs):
        if limits is None:
            limits = native_ci_limits(workspace)
        super().__init__(workspace, binary=binary, limits=limits, **kwargs)
