"""Thin news adapter over the shared docspec_client transport."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping

import pyarrow as pa

from news_lake.storage.docspec.schema import (
    DEFAULT_COMPACT_TARGET_FILE_BYTES,
    DEFINITION,
    table_records,
)
from docspec_client.docspec import (
    NativeDatasets,
    restore_application_schema,
)
from docspec_client.docspec_host import DocSpecFailure


class DocSpecClient:
    """Thin news adapter over the shared ``docspec_client`` transport.

    Readiness, deadlines, owned-host lifetime, exact-pin streaming, schema
    restoration and unknown-outcome producer custody all live in
    ``docspec_client``. This class keeps the historical news
    constructor and request-builder shape while adding no second transport.
    """

    def __init__(self, workspace: Path | str, binary: str | None = None, *, timeout: int = 120, limits: Any = None) -> None:
        resolved = (binary or os.environ.get('DOCSPEC_BINARY')
                    or shutil.which('docspec'))
        if not resolved:
            raise DocSpecFailure(
                ('docspec',),
                subprocess.CompletedProcess(
                    ('docspec',),
                    127,
                    stderr='no DocSpec runtime configured; set DOCSPEC_BINARY or install docspec',
                ),
            )
        self._native = NativeDatasets(resolved, workspace, timeout=timeout, limits=limits)
        self.binary = self._native.binary
        self.workspace = self._native.workspace
        self.limits = self._native.limits
        self.timeout = timeout
        self._dataset_schemas: dict[str, pa.Schema] = {}

    @classmethod
    def default_binary_path(cls) -> str | None:
        """The configured immutable runtime, never a mutable developer build."""
        return os.environ.get('DOCSPEC_BINARY') or shutil.which('docspec')

    @contextmanager
    def serve(self):
        """The shared transport owns one persistent host for this client."""
        yield self

    def close(self) -> None:
        self._native.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- operations ----------------------------------------------------------

    def hash_input(self, path: Path | str) -> str:
        return self._native.hash_input(path)

    def latest(self, dataset: str) -> dict[str, Any]:
        return self._native.latest(dataset)

    def try_latest(self, dataset: str) -> dict[str, Any] | None:
        try:
            return self.latest(dataset)
        except DocSpecFailure as error:
            if error.code == 'no_release' or 'no_release' in (error.stderr or ''):
                return None
            raise

    def release(self, dataset: str, version: str) -> dict[str, Any]:
        return self._native.release(dataset, version)

    def inspect(self, dataset: str) -> dict[str, Any]:
        return self._native.inspect(dataset)

    def refresh(self, spec: dict[str, Any]) -> dict[str, Any]:
        return self._native.refresh(spec)

    def plan_refresh(self, spec: dict[str, Any]) -> dict[str, Any]:
        return self._native.plan_refresh(spec)

    def seal_generation(self, spec: dict[str, Any]) -> dict[str, Any]:
        return self._native.seal_generation(spec)

    def export(self, spec: dict[str, Any]) -> dict[str, Any]:
        return self._native.export(spec)

    def latest_export(self, dataset: str, channel: str) -> dict[str, Any]:
        return self._native.latest_export(dataset, channel)

    def try_latest_export(self, dataset: str, channel: str) -> dict[str, Any] | None:
        return self._native.try_latest_export(dataset, channel)

    def export_pin(self, dataset: str, operation: str) -> dict[str, Any]:
        return self._native.export_pin(dataset, operation)

    def try_export_pin(self, dataset: str, operation: str) -> dict[str, Any] | None:
        return self._native.try_export_pin(dataset, operation)

    def compact(
        self,
        spec: Any,
        *,
        operation: str | None = None,
        version: str | None = None,
        group: str = 'source',
        files: Any = (),
        target_file_bytes: int = DEFAULT_COMPACT_TARGET_FILE_BYTES,
    ) -> dict[str, Any]:
        if isinstance(spec, str):
            return self._native.compact(
                spec,
                operation=operation,
                version=version,
                group=group,
                files=files,
                target_file_bytes=target_file_bytes,
            )
        return self._native.compact(spec)

    def compact_table(
        self,
        dataset: str,
        *,
        operation: str,
        version: str,
        group: str = 'source',
        files: Any = (),
        target_file_bytes: int = DEFAULT_COMPACT_TARGET_FILE_BYTES,
    ) -> dict[str, Any]:
        return self._native.compact_table(
            dataset,
            operation=operation,
            version=version,
            group=group,
            files=files,
            target_file_bytes=target_file_bytes,
        )

    def compact_lifecycle(self, dataset: str) -> dict[str, Any]:
        return self._native.compact_lifecycle(dataset)

    def _projected_schema(
        self,
        dataset: str,
        columns: list[str] | None,
        schema: pa.Schema | None,
        group: str = 'source',
    ) -> pa.Schema | None:
        if schema is None and group == 'source':
            schema = self._dataset_schemas.get(dataset)
        if schema is not None and columns is not None:
            return pa.schema([schema.field(name) for name in columns], metadata=schema.metadata)
        return schema

    @contextmanager
    def source_batches(self, release_pin: Mapping[str, Any], *, columns: list[str] | None = None, schema: pa.Schema | None = None):
        """Stream projected Arrow RecordBatches from an exact release pin."""
        dataset = release_pin['dataset']['dataset']
        target_schema = self._projected_schema(dataset, columns, schema, group='source')
        with self._native.source_batches(release_pin, columns=columns, schema=None) as reader:
            if target_schema is None:
                yield reader
            else:
                def restored_batches():
                    for batch in reader:
                        tbl = restore_application_schema(
                            pa.Table.from_batches([batch], schema=reader.schema),
                            expected_schema=target_schema,
                        )
                        yield from tbl.to_batches()

                with pa.RecordBatchReader.from_batches(target_schema, restored_batches()) as restored:
                    yield restored

    def iter_records(self, release_pin: Mapping[str, Any], *, columns: list[str] | None = None, schema: pa.Schema | None = None):
        """Stream projected records batch-by-batch without materializing a full table."""
        with self.source_batches(release_pin, columns=columns, schema=schema) as reader:
            for batch in reader:
                if batch.num_rows == 0:
                    continue
                yield from table_records(pa.Table.from_batches([batch], schema=reader.schema))

    def read_arrow(self, release_pin: Mapping[str, Any], group: str = 'source', *, columns: list[str] | None = None, schema: pa.Schema | None = None) -> pa.Table:
        dataset = release_pin['dataset']['dataset']
        target_schema = self._projected_schema(dataset, columns, schema, group=group)
        table = self._native.read_arrow(release_pin, group, columns=columns, schema=None)
        if target_schema is not None:
            return restore_application_schema(table, expected_schema=target_schema)
        return table

    def read_keys(
        self,
        release_pin: Mapping[str, Any],
        key: str,
        values: Any,
        *,
        columns: list[str] | None = None,
        schema: pa.Schema | None = None,
    ) -> pa.Table:
        """Stream only rows matching ``values`` on ``key`` from an exact release pin."""
        dataset = release_pin['dataset']['dataset']
        if schema is None and columns is None:
            schema = self._dataset_schemas.get(dataset)
        elif schema is not None and columns is not None:
            schema = pa.schema([schema.field(name) for name in columns])
        table = self._native.read_keys(
            release_pin, key, values, columns=columns, schema=None
        )
        if schema is not None:
            return restore_application_schema(table, expected_schema=schema)
        return table

    @contextmanager
    def changes_batches(
        self,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        *,
        group: str = 'source',
        identity: str = 'occurrences',
        force_full: bool = False,
    ):
        """Stream one exact change stream and its ``docspec.change`` descriptor."""
        with self._native.changes_batches(
            before, after, group=group, identity=identity, force_full=force_full
        ) as result:
            yield result

    def read_changes(
        self,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        *,
        group: str = 'source',
        identity: str = 'occurrences',
        force_full: bool = False,
    ) -> dict[str, Any]:
        """Consume one change stream, returning ``dict(descriptor, table, ...)``."""
        return self._native.read_changes(
            before, after, group=group, identity=identity, force_full=force_full
        )

    def capture_inputs(self, inputs: Any) -> Any:
        return self._native.capture_inputs(inputs)

    def run_ipc(
        self,
        table: pa.Table,
        dataset: str,
        operation: str,
        definition: str = DEFINITION,
        relationship: Any = None,
        base: str | None = None,
        *,
        native_types: bool = False,
    ) -> dict[str, Any]:
        """Stream one caller-bounded Arrow table as a dataset build over ``POST /run`` IPC."""
        self._dataset_schemas[dataset] = table.schema
        return self._native.run_ipc(
            table,
            dataset=dataset,
            operation=operation,
            definition=definition,
            relationship=relationship,
            base=base,
            native_types=native_types,
        )

    def update_ipc(
        self,
        dataset: str,
        operation: str,
        base: str,
        keys: Any,
        replacements_table: pa.Table,
        deletions: pa.Table | None = None,
        definition: str = DEFINITION,
        relationship: Any = None,
        *,
        merge: Any = None,
        native_types: bool = False,
    ) -> dict[str, Any]:
        """Stream replacement rows by key over ``POST /updates/run`` IPC."""
        self._dataset_schemas[dataset] = replacements_table.schema
        return self._native.update_ipc(
            replacements_table,
            dataset=dataset,
            operation=operation,
            definition=definition,
            base=base,
            keys=list(keys),
            deletions=deletions,
            relationship=relationship,
            merge=merge,
            native_types=native_types,
        )

    def run_table(
        self,
        table: pa.Table,
        dataset: str,
        operation: str,
        definition: str = DEFINITION,
        relationship: Any = None,
        base: str | None = None,
        *,
        stream_ipc: bool = False,
        native_types: bool = False,
    ) -> dict[str, Any]:
        """Admit one caller-bounded Arrow table as a dataset build."""
        self._dataset_schemas[dataset] = table.schema
        return self._native.run_table(
            table,
            dataset=dataset,
            operation=operation,
            definition=definition,
            relationship=relationship,
            base=base,
            stream_ipc=stream_ipc,
            native_types=native_types,
        )

    def update_table(
        self,
        dataset: str,
        operation: str,
        base: str,
        keys: Any,
        replacements_table: pa.Table,
        deletions: pa.Table | None = None,
        definition: str = DEFINITION,
        relationship: Any = None,
        *,
        merge: Any = None,
        stream_ipc: bool = False,
        native_types: bool = False,
    ) -> dict[str, Any]:
        """Replace or insert complete rows by key against the exact selected base."""
        self._dataset_schemas[dataset] = replacements_table.schema
        return self._native.update_table(
            replacements_table,
            dataset=dataset,
            operation=operation,
            definition=definition,
            base=base,
            keys=list(keys),
            deletions=deletions,
            relationship=relationship,
            merge=merge,
            stream_ipc=stream_ipc,
            native_types=native_types,
        )

    def retained_producer_inputs(self) -> Any:
        return self._native.retained_producer_inputs()
