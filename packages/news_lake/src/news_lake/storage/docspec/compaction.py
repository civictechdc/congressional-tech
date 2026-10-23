"""Shared compaction logic and dataset management for DocSpecLake and DocSpecNewsViews."""
from __future__ import annotations

from typing import Any, Mapping

from news_lake.storage.docspec.schema import (
    DEFAULT_COMPACT_FILE_THRESHOLD,
    DEFAULT_COMPACT_TARGET_FILE_BYTES,
    DEFAULT_LIFECYCLE_COMPACT_INTERVAL,
    content_digest,
    pin_group,
    pin_version,
    sanitize_id,
)


def _table_pin_parquet_objects(table_pin: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Return distinct active Parquet data file objects from a TablePin."""
    if not isinstance(table_pin, dict):
        return []
    objects = table_pin.get('objects') or ()
    seen = set()
    result = []
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        path = obj.get('path')
        if isinstance(path, str) and path.endswith('.parquet') and path not in seen:
            seen.add(path)
            result.append(obj)
    return result


def _undersized_parquet_files(
    table_pin: Mapping[str, Any] | None,
    target_file_bytes: int = DEFAULT_COMPACT_TARGET_FILE_BYTES,
) -> list[str]:
    """Return paths of active Parquet data files smaller than ``target_file_bytes``."""
    limit = (
        int(target_file_bytes)
        if target_file_bytes and int(target_file_bytes) > 0
        else DEFAULT_COMPACT_TARGET_FILE_BYTES
    )
    return [
        obj['path']
        for obj in _table_pin_parquet_objects(table_pin)
        if int(obj.get('bytes') or 0) < limit
    ]


class _DocSpecDatasetManager:
    """Shared base class eliminating duplicated compaction and pin-state methods.

    Subclasses (DocSpecLake and DocSpecNewsViews) manage local dataset pins and
    share lifecycle and table compaction routines against the native docspec engine.
    """

    def __init__(
        self,
        client: Any,
        *,
        compact_target_file_bytes: int | None = None,
        compact_file_threshold: int | None = None,
        lifecycle_compact_interval: int | None = None,
        workspace_suffix: str | None = None,
    ) -> None:
        self.client = client
        self.compact_target_file_bytes = compact_target_file_bytes
        self.compact_file_threshold = compact_file_threshold
        self.lifecycle_compact_interval = (
            lifecycle_compact_interval
            if lifecycle_compact_interval is not None
            else DEFAULT_LIFECYCLE_COMPACT_INTERVAL
        )
        self.workspace_suffix = workspace_suffix
        self.lifecycle_compactions: list[dict[str, Any]] = []
        self.table_compactions: list[dict[str, Any]] = []
        self._mutation_counts: dict[str, int] = {}
        self._pending_lifecycle_compactions: set[str] = set()
        self._compacted_pins: dict[str, Any] = {}

    # -- Subclass contract hooks ---------------------------------------------

    @property
    def _active_pins(self) -> dict[str, Any]:
        """Dictionary of currently committed or pinned datasets."""
        raise NotImplementedError

    def _resolve_dataset_id(self, dataset: str) -> str:
        """Resolve a table name or dataset name to its native dataset id."""
        raise NotImplementedError

    def _save_dataset_state(self) -> None:
        """Persist committed or view pin state to disk."""
        raise NotImplementedError

    # -- Shared Compaction and Pin State -------------------------------------

    def _operation(self, label: str, digest: str) -> str:
        name = f'{label}-{digest[:16]}'
        if self.workspace_suffix:
            name = f'{name}-{self.workspace_suffix}'
        return sanitize_id(name)

    def _effective_source_table_pin(self, dataset: str, pin: Mapping[str, Any] | None) -> dict[str, Any]:
        if not isinstance(pin, dict):
            return {}
        ver = pin_version(pin)
        compacted = self._compacted_pins.get(dataset)
        if isinstance(compacted, dict) and compacted.get('version') == ver:
            replacement = compacted.get('replacement')
            if isinstance(replacement, dict):
                return replacement
        return pin_group(pin, 'source')

    def active_parquet_files(self, dataset: str, *, pin: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """Return active Parquet data file objects for ``dataset``."""
        resolved = self._resolve_dataset_id(dataset)
        target_pin = (
            pin
            or self._active_pins.get(resolved)
            or self.client.try_latest(resolved)
        )
        if target_pin is None:
            return []
        table_pin = self._effective_source_table_pin(resolved, target_pin)
        return _table_pin_parquet_objects(table_pin)

    def compact_table(
        self,
        dataset: str,
        *,
        pin: Mapping[str, Any] | None = None,
        target_file_bytes: int | None = None,
        compact_file_threshold: int | None = None,
        force: bool = True,
    ) -> dict[str, Any] | None:
        """Run native table compaction on undersized Parquet files of ``dataset``."""
        if getattr(self.client._native, 'remote', None) is not None:
            return None
        resolved = self._resolve_dataset_id(dataset)
        target_pin = (
            pin
            or self._active_pins.get(resolved)
            or self.client.try_latest(resolved)
        )
        if target_pin is None:
            return None
        limit = (
            int(target_file_bytes)
            if target_file_bytes is not None
            else int(self.compact_target_file_bytes or DEFAULT_COMPACT_TARGET_FILE_BYTES)
        )
        if limit <= 0:
            limit = DEFAULT_COMPACT_TARGET_FILE_BYTES
        table_pin = self._effective_source_table_pin(resolved, target_pin)
        undersized = _undersized_parquet_files(table_pin, limit)
        if len(undersized) < 2:
            return None
        if compact_file_threshold is not None or not force:
            threshold = (
                self.compact_file_threshold
                if compact_file_threshold is None
                else compact_file_threshold
            )
            if not threshold or threshold < 1 or len(undersized) < threshold:
                return None
        ver = target_pin['dataset']['version']
        operation = self._operation(
            f'compact-{resolved}',
            content_digest([ver, undersized, limit]),
        )
        report = self.client.compact({
            'dataset': resolved,
            'operation': operation,
            'version': ver,
            'group': 'source',
            'files': undersized,
            'target_file_bytes': limit,
        })
        if isinstance(report, dict) and isinstance(report.get('replacement'), dict):
            self._compacted_pins[resolved] = {
                'version': ver,
                'replacement': report['replacement'],
            }
            self._save_dataset_state()
        input_files = list((report or {}).get('input_files') or undersized)
        output_files = list((report or {}).get('output_files') or ())
        entry = {
            'dataset': resolved,
            'version': ver,
            'operation': operation,
            'group': 'source',
            'files_before': len(input_files),
            'files_after': len(output_files),
            'rewritten_files': len(input_files),
            'produced_files': len(output_files),
            **(report if isinstance(report, dict) else {}),
        }
        self.table_compactions.append(entry)
        return entry

    def compact_tables(
        self,
        datasets: Any = None,
        *,
        target_file_bytes: int | None = None,
        compact_file_threshold: int | None = None,
        force: bool = True,
    ) -> dict[str, Any]:
        """Run native table compaction across committed (or specified) datasets."""
        targets = list(self._active_pins if datasets is None else datasets)
        results = {}
        for dataset in targets:
            resolved = self._resolve_dataset_id(dataset)
            report = self.compact_table(
                resolved,
                target_file_bytes=target_file_bytes,
                compact_file_threshold=compact_file_threshold,
                force=force,
            )
            if report is not None:
                results[resolved] = report
        return results

    def _maybe_compact_table(
        self,
        dataset: str,
        pin: Mapping[str, Any] | None,
        *,
        incoming_files: int = 1,
    ) -> dict[str, Any] | None:
        threshold = self.compact_file_threshold
        if not threshold or threshold < 1 or pin is None:
            return None
        resolved = self._resolve_dataset_id(dataset)
        limit = int(self.compact_target_file_bytes or DEFAULT_COMPACT_TARGET_FILE_BYTES)
        if limit <= 0:
            limit = DEFAULT_COMPACT_TARGET_FILE_BYTES
        table_pin = self._effective_source_table_pin(resolved, pin)
        undersized = _undersized_parquet_files(table_pin, limit)
        if len(undersized) < 2 or len(undersized) + int(incoming_files) < threshold:
            return None
        return self.compact_table(resolved, pin=pin, target_file_bytes=limit, force=True)

    def compact_lifecycle(self, datasets: Any = None) -> dict[str, Any]:
        """Compact obsolete lifecycle revisions for local datasets."""
        if getattr(self.client._native, 'remote', None) is not None:
            return {}
        targets = list(self._active_pins if datasets is None else datasets)
        results = {}
        for dataset in targets:
            report = self.client.compact_lifecycle(dataset)
            self._mutation_counts[dataset] = 0
            entry = {'dataset': dataset, **(report if isinstance(report, dict) else {})}
            self.lifecycle_compactions.append(entry)
            results[dataset] = report
        if results:
            self._save_dataset_state()
        return results
