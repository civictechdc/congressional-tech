"""Finite local fixture budgets; production native configuration is independent."""
import json
import os
import subprocess

import pytest
from pathlib import Path

from docspec_client import NativeDatasets, resolve_docspec_binary
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


def lake_readings_table(rows):
    """Readings rows in the lake table's full schema, defaulting required lists to empty.

    Model SQL reads the lake shape (pinned-readings.sql excludes ``links`` by
    name), so a fixture that declares only the columns its test inspects is a
    relation production never supplies.
    """
    import pyarrow as pa
    from pyiceberg.io.pyarrow import schema_to_pyarrow
    from pyiceberg.schema import Schema
    from congress_api.lake.tables import load_schema
    schema = schema_to_pyarrow(Schema.model_validate(load_schema('readings')), include_field_ids=False)
    lists = {field.name: [] for field in schema if pa.types.is_large_list(field.type) and not field.nullable}
    table = pa.Table.from_pylist([{**lists, **row} for row in rows], schema=schema)

    def refuse_nulls(path, field, values):
        # pyarrow does not enforce declared nullability, so check every level.
        if not field.nullable and values.null_count:
            raise ValueError(f'Readings fixture leaves required {path} null')
        if pa.types.is_large_list(field.type) or pa.types.is_list(field.type):
            refuse_nulls(path + '[]', field.type.value_field, values.flatten())
        elif pa.types.is_struct(field.type):
            for child in field.type:
                refuse_nulls(path + '.' + child.name, child, values.field(child.name))

    for field in schema:
        refuse_nulls(field.name, field, table.column(field.name).combine_chunks())
    return table


def empty_readings(directory):
    """An empty lake readings table: D4 producers route House XML by reading, and none exists."""
    import pyarrow.parquet as pq
    path = Path(directory) / 'readings.parquet'
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(lake_readings_table([]), path)
    return path


def compatible_entry(parser, old, current, *, rows=1):
    """A registry entry with a fixture proof shaped like the CLI's: its binding and strata are
    checked, its counts are not re-derived. A page parser gets a full predicate entry bound to
    the page-parse bound (with its reader's recompute set, if any); sniff a sampled lock-only one."""
    from congress_api.lake import compatible_versions as cv
    page = parser in cv.PAGE_PARSERS
    recompute = (cv.reader_recompute_sql(parser) or cv.WHOLE) if page else cv.WHOLE
    proof = dict(scope='full' if page else 'sample', version=old, current=current,
        recompute_sha256=cv.recompute_sha256(recompute), old_input_sha256='a' * 64, new_input_sha256='a' * 64,
        rows=rows, columns=1, differences=0, only_old=0, only_new=0,
        strata=dict(completed=dict(population=rows, local=rows, sampled=rows)), lock_only=dict(recomputed=old),
        **(dict(page_parse_max_bytes=cv.page_parse_max_bytes()) if page else {}))
    return dict(parser=parser, version=old, current=current, basis='predicate' if page else 'lock_only',
        recompute_sql=recompute, reason='fixture', proof=proof)
