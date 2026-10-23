"""DocSpecLake: storage coordinator routing records into native docspec datasets."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
from typing import Any, Mapping

from news_lake.context import canonicalize_record_instants
from news_lake.contract.records import (
    CONTENT_TABLES,
    CONTRACT_VERSION,
    KIND_ORDER,
    KIND_TABLES,
    TABLE_KINDS,
    TABLE_MUTATIONS,
    validate_shape,
)
from news_lake.contract.semantics import check_corpus
from congress_shared.custody import write_atomic_bytes
from news_lake.storage.coordinator import CommitError
from news_lake.storage.releases import ReleaseError, _redact_checkpoints
from news_lake.storage.docspec.client import DocSpecClient
from news_lake.storage.docspec.compaction import _DocSpecDatasetManager
from news_lake.storage.docspec.schema import (
    APPEND_UPDATE_KEYS,
    AppendCollisionError,
    DEFAULT_COMPACT_FILE_THRESHOLD,
    DEFAULT_COMPACT_TARGET_FILE_BYTES,
    DEFAULT_LIFECYCLE_COMPACT_INTERVAL,
    content_digest,
    dataset_id_for,
    kind_arrow_schema,
    merge_upsert_batch,
    pin_group,
    pin_metadata_path,
    pin_objects,
    pin_rows,
    pin_snapshot,
    pin_version,
    records_to_arrow,
    sanitize_id,
    table_records,
    upsert_merge_spec_for_kind,
    version_ref,
)


class DocSpecLake(_DocSpecDatasetManager):
    """Route news_lake records into native datasets, one per contract table.

    Upsert tables (outlets/items/entities) merge each incoming poll against
    the stored row for its id so earlier evidence survives (C1), then submit
    the merged rows as a complete-key update. Append tables admit the initial
    batch as a build and subsequent batches as complete-key updates against the
    pinned head.
    """

    def __init__(
        self,
        client: DocSpecClient | Path | str,
        workspace_suffix: str = '',
        *,
        binary: str | None = None,
        timeout: int = 120,
        limits: Any = None,
        stream_ipc: bool = True,
        native_upsert_merge: bool = True,
        compact_target_file_bytes: int = DEFAULT_COMPACT_TARGET_FILE_BYTES,
        compact_file_threshold: int = DEFAULT_COMPACT_FILE_THRESHOLD,
        lifecycle_compact_interval: int = DEFAULT_LIFECYCLE_COMPACT_INTERVAL,
    ) -> None:
        if not isinstance(client, DocSpecClient):
            client = DocSpecClient(client, binary=binary, timeout=timeout, limits=limits)
        clean_suffix = sanitize_id(workspace_suffix) if workspace_suffix else ''
        super().__init__(
            client,
            compact_target_file_bytes=compact_target_file_bytes,
            compact_file_threshold=compact_file_threshold,
            lifecycle_compact_interval=lifecycle_compact_interval,
            workspace_suffix=clean_suffix,
        )
        self._compact_file_threshold = compact_file_threshold
        self._compact_target_file_bytes = compact_target_file_bytes
        self.stream_ipc = bool(stream_ipc)
        self.native_upsert_merge = bool(native_upsert_merge)
        self._known_ids: dict[str, set[str]] = {}
        self._known_upsert_records: dict[str, dict[str, Any]] = {}
        self.last_lookup_stats: dict[str, dict[str, Any]] = {}
        self._committed = self._load_committed_state()
        self._mutation_counts = self._load_mutation_counts()

    # -- Implement _DocSpecDatasetManager hooks ------------------------------

    @property
    def _active_pins(self) -> dict[str, Any]:
        return self._committed

    def _resolve_dataset_id(self, dataset: str) -> str:
        return self._dataset(dataset)

    def _save_dataset_state(self) -> None:
        self._save_committed_state()

    # -- State Persistence ---------------------------------------------------

    @property
    def committed(self) -> dict[str, Any]:
        return dict(self._committed)

    @committed.setter
    def committed(self, value: Mapping[str, Any]) -> None:
        self._committed = dict(value)

    def _committed_state_path(self) -> Path:
        suffix = f'-{self.workspace_suffix}' if self.workspace_suffix else ''
        return Path(self.client.workspace) / f'.news_lake_committed{suffix}.json'

    def _mutation_counts_path(self) -> Path:
        suffix = f'-{self.workspace_suffix}' if self.workspace_suffix else ''
        return Path(self.client.workspace) / f'.news_lake_mutations{suffix}.json'

    def _compacted_pins_path(self) -> Path:
        suffix = f'-{self.workspace_suffix}' if self.workspace_suffix else ''
        return Path(self.client.workspace) / f'.news_lake_compacted{suffix}.json'

    def _release_manifest_path(self, release_id: str) -> Path:
        return self._releases_dir() / f'{sanitize_id(release_id)}.json'

    def _releases_dir(self) -> Path:
        suffix = f'-{self.workspace_suffix}' if self.workspace_suffix else ''
        return Path(self.client.workspace) / f'releases{suffix}'

    def _load_committed_state(self) -> dict[str, Any]:
        path = self._committed_state_path()
        committed = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text())
                if isinstance(data, dict):
                    committed = {str(k): v for k, v in data.items() if isinstance(v, dict)}
            except (OSError, ValueError):
                committed = {}
        cpath = self._compacted_pins_path()
        compacted_pins = {}
        if cpath.is_file():
            try:
                raw_compacted = json.loads(cpath.read_text())
                if isinstance(raw_compacted, dict):
                    for ds, entry in raw_compacted.items():
                        if not isinstance(entry, dict) or not isinstance(entry.get('replacement'), dict):
                            continue
                        pin = committed.get(ds)
                        selected_ver = pin_version(pin)
                        if selected_ver and entry.get('version') == selected_ver:
                            compacted_pins[str(ds)] = {
                                'version': selected_ver,
                                'replacement': entry['replacement'],
                            }
            except (OSError, ValueError):
                compacted_pins = {}
        self._compacted_pins = compacted_pins
        return committed

    def _load_mutation_counts(self) -> dict[str, int]:
        path = self._mutation_counts_path()
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text())
            return {
                str(k): int(v)
                for k, v in data.items()
                if isinstance(v, int) and not isinstance(v, bool)
            } if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_committed_state(self) -> None:
        path = self._committed_state_path()
        write_atomic_bytes(
            path,
            json.dumps(self.committed, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=str).encode('utf-8'),
            temp_mode='fixed',
            fsync=False,
        )
        mpath = self._mutation_counts_path()
        write_atomic_bytes(
            mpath,
            json.dumps(self._mutation_counts, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8'),
            temp_mode='fixed',
            fsync=False,
        )
        valid_compacted = {}
        for ds, entry in self._compacted_pins.items():
            if not isinstance(entry, dict) or not isinstance(entry.get('replacement'), dict):
                continue
            pin = self.committed.get(ds)
            selected_ver = pin_version(pin)
            if selected_ver is None or entry.get('version') == selected_ver:
                valid_compacted[ds] = entry
        self._compacted_pins = valid_compacted
        cpath = self._compacted_pins_path()
        write_atomic_bytes(
            cpath,
            json.dumps(self._compacted_pins, ensure_ascii=False, separators=(',', ':'), allow_nan=False, default=str).encode('utf-8'),
            temp_mode='fixed',
            fsync=False,
        )

    def _record_dataset_mutation(self, dataset: str, prior_pin: Mapping[str, Any] | None, new_pin: Mapping[str, Any] | None) -> bool:
        if new_pin is None:
            return False
        prior_ver = pin_version(prior_pin)
        new_ver = pin_version(new_pin)
        if prior_ver == new_ver:
            return False
        self._mutation_counts[dataset] = self._mutation_counts.get(dataset, 0) + 1
        return True

    def _maybe_compact_lifecycle(self, datasets: list[str]) -> dict[str, Any]:
        interval = self.lifecycle_compact_interval
        if not interval or interval < 1:
            self._pending_lifecycle_compactions.clear()
            return {}
        due = [
            ds for ds in datasets
            if self._mutation_counts.get(ds, 0) >= interval
            or ds in self._pending_lifecycle_compactions
        ]
        for ds in due:
            self._pending_lifecycle_compactions.discard(ds)
        return self.compact_lifecycle(due) if due else {}

    def _dataset(self, kind_or_table: str) -> str:
        return dataset_id_for(KIND_TABLES.get(kind_or_table, kind_or_table))

    # -- Fenced transaction support ------------------------------------------

    @contextmanager
    def fenced_commit(self, control: Any, epoch: int):
        control.require_epoch(epoch)
        yield
        control.require_epoch(epoch)

    # -- Dedup and record commits --------------------------------------------

    def _dedup_incoming(self, dataset: str, records: list[dict[str, Any]], is_append: bool = True) -> list[dict[str, Any]]:
        seen_in_batch = {}
        deduped = []
        for record in records:
            rid = record['id']
            if rid in seen_in_batch:
                prior = seen_in_batch[rid]
                if is_append:
                    if prior != record:
                        raise AppendCollisionError(
                            'append_collision',
                            f'duplicate id {rid} in batch with differing values on append-only {dataset}',
                            record_id=rid,
                        )
                else:
                    merged = merge_upsert_batch([prior], [record])[0]
                    seen_in_batch[rid] = merged
                    deduped = [merged if r['id'] == rid else r for r in deduped]
                continue
            seen_in_batch[rid] = record
            deduped.append(record)
        return deduped

    def _existing_by_ids(self, pin: Mapping[str, Any], kind: str, ids: Any) -> dict[str, dict[str, Any]]:
        id_list = sorted(set(ids))
        dataset = pin['dataset']['dataset']
        if not id_list:
            self.last_lookup_stats[dataset] = {
                'requested_ids': 0,
                'requested_keys': 0,
                'matched_rows': 0,
                'rows_transferred': 0,
                'total_rows': pin_rows(pin),
            }
            return {}
        table = self.client.read_keys(
            pin, 'id', id_list, schema=kind_arrow_schema(kind)
        )
        rows = table_records(table)
        self.last_lookup_stats[dataset] = {
            'requested_ids': len(id_list),
            'requested_keys': len(id_list),
            'matched_rows': len(rows),
            'rows_transferred': table.num_rows,
            'total_rows': pin_rows(pin) or table.num_rows,
        }
        return {row['id']: row for row in rows}

    def _existing_for_append(self, pin: Mapping[str, Any], kind: str, records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Fetch existing rows for an append batch using physical update key point pruning."""
        keys = self._update_keys_for(kind)
        if len(keys) <= 1:
            found = self._existing_by_ids(pin, kind, (record['id'] for record in records))
            dataset = pin['dataset']['dataset']
            self._known_ids.setdefault(dataset, set()).update(found.keys())
            return found

        time_col = keys[0]
        id_list = sorted({record['id'] for record in records})
        id_set = set(id_list)
        dataset = pin['dataset']['dataset']
        total_rows = pin_rows(pin)
        if not id_list:
            self.last_lookup_stats[dataset] = {
                'requested_ids': 0,
                'requested_keys': 0,
                'matched_rows': 0,
                'rows_transferred': 0,
                'total_rows': total_rows,
            }
            return {}
        time_values = sorted({str(record[time_col]) for record in records})
        table = self.client.read_keys(
            pin, time_col, time_values, schema=kind_arrow_schema(kind)
        )
        rows = table_records(table)
        found = {row['id']: row for row in rows if row['id'] in id_set}
        rows_transferred = int(table.num_rows)
        known = self._known_ids.setdefault(dataset, set())
        known.update(found.keys())
        missing_known = (id_set & known) - set(found)
        if missing_known:
            fallback_table = self.client.read_keys(
                pin, 'id', sorted(missing_known), schema=kind_arrow_schema(kind)
            )
            for row in table_records(fallback_table):
                if row['id'] in id_set:
                    found[row['id']] = row
            rows_transferred += int(fallback_table.num_rows)
        self.last_lookup_stats[dataset] = {
            'requested_ids': len(id_list),
            'requested_keys': len(id_list),
            'matched_rows': len(found),
            'rows_transferred': rows_transferred,
            'total_rows': total_rows,
        }
        return found

    @staticmethod
    def _update_keys_for(kind: str) -> list[str]:
        if TABLE_MUTATIONS.get(KIND_TABLES.get(kind)) == 'append':
            return list(APPEND_UPDATE_KEYS.get(kind, ('id',)))
        return ['id']

    def _advance_relationship(self, dataset: str, kind: str, prior: Mapping[str, Any], relationship: Any) -> dict[str, Any]:
        if relationship is None or prior.get('dataset', {}).get('relationship') == relationship:
            return dict(prior)
        base_version = prior['dataset']['version']
        operation = self._operation(
            f'rel-{kind}', content_digest([base_version, relationship])
        )
        return self.client.update_table(
            dataset,
            operation,
            base_version,
            self._update_keys_for(kind),
            records_to_arrow(kind, ()),
            relationship=relationship,
        )

    def _commit_append(self, dataset: str, kind: str, records: list[dict[str, Any]], relationship: Any, *, stream_ipc: bool = False) -> dict[str, Any]:
        records = self._dedup_incoming(dataset, records, is_append=True)
        prior = self.committed.get(dataset) or self.client.try_latest(dataset)
        if prior is None:
            operation = self._operation(f'admit-{kind}', content_digest(records))
            pin = self.client.run_table(
                records_to_arrow(kind, records),
                dataset,
                operation,
                relationship=relationship,
                stream_ipc=stream_ipc,
            )
            self._known_ids.setdefault(dataset, set()).update(r['id'] for r in records)
            return pin
        existing = self._existing_for_append(prior, kind, records)
        new_records = []
        for record in records:
            stored = existing.get(record['id'])
            if stored is not None:
                if stored == record:
                    continue
                raise AppendCollisionError(
                    'append_collision',
                    f'id {record["id"]} already exists with different values on append-only {dataset}',
                    record_id=record['id'],
                )
            new_records.append(record)
        if not new_records:
            return self._advance_relationship(dataset, kind, prior, relationship)
        if self._maybe_compact_table(dataset, prior, incoming_files=1) is not None:
            self._pending_lifecycle_compactions.add(dataset)
        base_version = prior['dataset']['version']
        operation = self._operation(
            f'append-{kind}', content_digest([base_version, new_records, relationship])
        )
        pin = self.client.update_table(
            dataset,
            operation,
            base_version,
            self._update_keys_for(kind),
            records_to_arrow(kind, new_records),
            relationship=relationship,
            stream_ipc=stream_ipc,
        )
        self._known_ids.setdefault(dataset, set()).update(r['id'] for r in new_records)
        return pin

    def _commit_upsert(
        self,
        dataset: str,
        kind: str,
        records: list[dict[str, Any]],
        relationship: Any,
        *,
        native_upsert_merge: bool = True,
        stream_ipc: bool = True,
    ) -> dict[str, Any]:
        """Commit upsert records using declarative native merge (retired pre-ss-65bz fallback)."""
        records = self._dedup_incoming(dataset, records, is_append=False)
        known_records = self._known_upsert_records.setdefault(dataset, {})
        prior = self.committed.get(dataset) or self.client.try_latest(dataset)
        if prior is None:
            operation = self._operation(f'admit-{kind}', content_digest(records))
            pin = self.client.run_table(
                records_to_arrow(kind, records),
                dataset,
                operation,
                relationship=relationship,
                stream_ipc=stream_ipc,
            )
            for r in records:
                known_records[r['id']] = r
            return pin

        total_rows = pin_rows(prior)
        candidate_records = []
        merged_known = {}
        for r in records:
            rid = r['id']
            if rid in known_records:
                m = merge_upsert_batch([known_records[rid]], [r])[0]
                if m == known_records[rid]:
                    continue
                merged_known[rid] = m
            else:
                merged_known[rid] = r
            candidate_records.append(r)

        if not candidate_records:
            self.last_lookup_stats[dataset] = {
                'requested_ids': len(records),
                'requested_keys': 0,
                'matched_rows': len(records),
                'rows_transferred': 0,
                'total_rows': total_rows,
                'mode': 'native_merge',
            }
            return self._advance_relationship(dataset, kind, prior, relationship)

        if self._maybe_compact_table(dataset, prior, incoming_files=1) is not None:
            self._pending_lifecycle_compactions.add(dataset)

        base_version = prior['dataset']['version']
        merge_spec = upsert_merge_spec_for_kind(kind)
        operation = self._operation(
            f'upsert-{kind}',
            content_digest([base_version, candidate_records, relationship, merge_spec]),
        )
        pin = self.client.update_table(
            dataset,
            operation,
            base_version,
            ['id'],
            records_to_arrow(kind, candidate_records),
            relationship=relationship,
            merge=merge_spec,
            stream_ipc=stream_ipc,
        )
        known_records.update(merged_known)
        self.last_lookup_stats[dataset] = {
            'requested_ids': len(records),
            'requested_keys': 0,
            'matched_rows': 0,
            'rows_transferred': 0,
            'total_rows': total_rows,
            'mode': 'native_merge',
        }
        return pin

    def commit_records(
        self,
        records: list[dict[str, Any]],
        generation: str | None = None,
        family: str = 'news',
        *,
        ensure_all_tables: bool = False,
        native_upsert_merge: bool | None = None,
        stream_ipc: bool | None = None,
    ) -> dict[str, Any]:
        """Validate and commit one batch; returns ``{dataset: latest ReleasePin}``."""
        use_native_merge = (
            self.native_upsert_merge
            if native_upsert_merge is None
            else bool(native_upsert_merge)
        )
        use_stream_ipc = self.stream_ipc if stream_ipc is None else bool(stream_ipc)
        relationship = (
            {'kind': 'coupled', 'family': family, 'generation': generation}
            if generation is not None
            else None
        )
        batch: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            validate_shape(record)
            canonical = canonicalize_record_instants(record)
            batch.setdefault(canonical['kind'], []).append(canonical)
        pins = dict(self.committed)
        mutated = []
        for kind in KIND_ORDER:
            if kind == 'release':
                continue
            records_of_kind = batch.get(kind)
            dataset = self._dataset(kind)
            prior = pins.get(dataset)
            if not records_of_kind:
                if prior is not None and relationship is not None:
                    pins[dataset] = self._advance_relationship(dataset, kind, prior, relationship)
                    if self._record_dataset_mutation(dataset, prior, pins[dataset]):
                        mutated.append(dataset)
                elif prior is None and ensure_all_tables:
                    operation = self._operation(
                        f'admit-empty-{kind}', content_digest([dataset, relationship])
                    )
                    pins[dataset] = self.client.run_table(
                        records_to_arrow(kind, ()),
                        dataset,
                        operation,
                        relationship=relationship,
                        stream_ipc=use_stream_ipc,
                    )
                    if self._record_dataset_mutation(dataset, prior, pins[dataset]):
                        mutated.append(dataset)
                continue
            if TABLE_MUTATIONS[KIND_TABLES[kind]] == 'upsert':
                pins[dataset] = self._commit_upsert(
                    dataset,
                    kind,
                    records_of_kind,
                    relationship,
                    native_upsert_merge=use_native_merge,
                    stream_ipc=use_stream_ipc,
                )
            else:
                pins[dataset] = self._commit_append(
                    dataset,
                    kind,
                    records_of_kind,
                    relationship,
                    stream_ipc=use_stream_ipc,
                )
            if self._record_dataset_mutation(dataset, prior, pins[dataset]):
                mutated.append(dataset)
        self.committed = pins
        self._save_committed_state()
        if mutated:
            self._maybe_compact_lifecycle(mutated)
        return dict(pins)

    def seal(self, generation_id: str, family: str = 'news') -> dict[str, Any]:
        """Seal the committed datasets as one generation of ``family``."""
        if not self.committed:
            raise ValueError('seal requires committed datasets')
        members = {dataset: version_ref(pin) for dataset, pin in self.committed.items()}
        return self.client.seal_generation(
            {'family': family, 'generation': generation_id, 'members': members}
        )

    def read_dataset(self, dataset: str) -> pa.Table:
        """Read a dataset's selected source group as an Arrow table."""
        pin = self.committed.get(dataset) or self.client.latest(dataset)
        return self.client.read_arrow(pin)

    def _table_uuid(self, table_name: str, pin: Mapping[str, Any] | None = None) -> str:
        if pin is not None:
            meta_path = pin_metadata_path(pin)
            if isinstance(meta_path, str) and Path(meta_path).is_file():
                try:
                    meta = json.loads(Path(meta_path).read_text())
                    if isinstance(meta, dict) and isinstance(meta.get('table-uuid'), str):
                        return meta['table-uuid']
                except (OSError, ValueError):
                    pass
        from uuid import NAMESPACE_URL, uuid5
        return str(uuid5(NAMESPACE_URL, f'docspec-news-lake:{self.client.workspace}:{table_name}'))

    def build_release(
        self,
        release_id: str,
        recorded_at: str,
        selections: Any,
        checkpoints: Any,
        *,
        pins: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a contract-valid ``release`` record bound to exact ``DocSpecLake`` pins."""
        active_pins = dict(self.committed if pins is None else pins)
        snapshots = []
        for table_name in CONTENT_TABLES:
            dataset = dataset_id_for(table_name)
            pin = active_pins.get(dataset)
            entry: dict[str, Any] = {
                'table': table_name,
                'table_uuid': self._table_uuid(table_name, pin=pin),
            }
            if pin is not None:
                snap = pin_snapshot(pin)
                rows = pin_rows(pin)
                if snap is not None and rows > 0:
                    entry['snapshot_id'] = str(snap)
            snapshots.append(entry)
        return {
            'kind': 'release',
            'id': release_id,
            'recorded_at': recorded_at,
            'contract_version': CONTRACT_VERSION,
            'snapshots': snapshots,
            'selections': list(selections),
            'checkpoints': _redact_checkpoints(checkpoints),
        }

    def publish_release(
        self,
        control: Any,
        records: list[dict[str, Any]],
        *,
        release_id: str,
        recorded_at: str,
        selections: Any = (),
        checkpoints: Any = (),
        epoch: int | None = None,
        faults: Any = None,
    ) -> dict[str, Any]:
        """Publish one release through DocSpecLake + ControlStore."""
        from news_lake.storage.coordinator import Faults
        faults = faults if faults is not None else Faults()
        if epoch is None:
            epoch = control.claim('docspec-news-writer')
        control.require_epoch(epoch)
        payload = {
            'records': list(records),
            'recorded_at': recorded_at,
            'selections': list(selections),
            'checkpoints': _redact_checkpoints(checkpoints),
        }
        faults.before('journal_write')
        stored = control.begin_cycle(release_id, payload, epoch=epoch)
        if stored is not None:
            payload = stored
        faults.after('journal_write')
        state = control.cycle_state(release_id)
        if state == 'done':
            return self.find_release(release_id)
        if state == 'abandoned':
            raise ReleaseError(
                'cycle_abandoned',
                f'cycle {release_id} was abandoned after failed validation; publish under a new release id',
                release_id=release_id,
            )
        gen_id = sanitize_id(f'rel-{release_id}')
        if state == 'intent':
            faults.before('table_commit')
            pins = self.commit_records(
                payload['records'],
                generation=gen_id,
                family='news',
                ensure_all_tables=True,
            )
            if pins:
                self.seal(gen_id, family='news')
            faults.after('table_commit')
            payload['dataset_pins'] = pins
            control.update_cycle_payload(release_id, payload, epoch=epoch)
            control.set_cycle_state(release_id, 'committed', epoch=epoch)
            state = 'committed'

        pins = payload.get('dataset_pins') or dict(self.committed)
        release = payload.get('release')
        if release is None:
            release = self.build_release(
                release_id,
                payload['recorded_at'],
                payload['selections'],
                payload['checkpoints'],
                pins=pins,
            )
            payload['release'] = release
            control.update_cycle_payload(release_id, payload, epoch=epoch)

        pinned_records = []
        table_pins = {}
        for entry in release['snapshots']:
            table_name = entry['table']
            dataset = dataset_id_for(table_name)
            pin = pins.get(dataset)
            if pin is not None:
                table_pins[table_name] = pin
            if 'snapshot_id' not in entry or pin is None:
                continue
            kind = TABLE_KINDS[table_name]
            pinned_records.extend(
                table_records(self.client.read_arrow(pin, schema=kind_arrow_schema(kind)))
            )
        check_corpus(pinned_records + [release])
        control.mark_snapshots_validated(
            [(entry['table'], entry['snapshot_id'])
             for entry in release['snapshots'] if 'snapshot_id' in entry],
            epoch=epoch,
        )
        if state == 'committed':
            control.set_cycle_state(release_id, 'validated', epoch=epoch)
            state = 'validated'
        if state == 'validated':
            faults.before('checkpoint_stage')
            for checkpoint in payload['checkpoints']:
                key = checkpoint['connector_key']
                faults.before(f'checkpoint_stage:{key}')
                control.stage_checkpoint(release_id, checkpoint, epoch=epoch)
                faults.after(f'checkpoint_stage:{key}')
            faults.after('checkpoint_stage')
            control.set_cycle_state(release_id, 'checkpoints_staged', epoch=epoch)
            state = 'checkpoints_staged'
        if state == 'checkpoints_staged':
            faults.before('release_append')
            manifest_path = self._release_manifest_path(release_id)
            write_atomic_bytes(
                manifest_path,
                json.dumps(
                    {
                        'release': release,
                        'dataset_pins': pins,
                        'table_pins': table_pins,
                        'generation': gen_id,
                    },
                    ensure_ascii=False,
                    separators=(',', ':'),
                    allow_nan=False,
                    default=str,
                ).encode('utf-8'),
                temp_mode='fixed',
                fsync=False,
            )
            faults.after('release_append')
            control.set_cycle_state(release_id, 'released', epoch=epoch)
            state = 'released'
        if state == 'released':
            faults.before('cursor_advance')
            control.mark_available(release_id, epoch=epoch)
            control.activate_checkpoints(release_id, epoch=epoch)
            faults.after('cursor_advance')
            control.set_cycle_state(release_id, 'done', epoch=epoch)
        return release

    def abandon_cycle(
        self,
        control: Any,
        cycle_id: str,
        *,
        epoch: int | None = None,
        faults: Any = None,
    ) -> None:
        """Policy rollback of one failed publication cycle on DocSpecLake."""
        if epoch is None:
            epoch = control.claim('docspec-news-writer')
        control.require_epoch(epoch)
        row = control.cycle(cycle_id)
        if row is None:
            raise CommitError('unknown_cycle', f'no journal entry for cycle {cycle_id}')
        if row['state'] == 'abandoned':
            return
        if row['state'] in ('released', 'done'):
            raise CommitError('cycle_released', f'cycle {cycle_id} is {row["state"]} and cannot be abandoned')
        if self.find_release(cycle_id) is not None:
            raise CommitError(
                'cycle_release_appended',
                f'cycle {cycle_id} already appended its release record; run recover() instead',
            )

        baseline_release_id = control.latest_available_release()
        baseline_release = self.find_release(baseline_release_id) if baseline_release_id is not None else None
        baseline_manifest = {}
        if baseline_release_id is not None:
            manifest_path = self._release_manifest_path(baseline_release_id)
            if manifest_path.is_file():
                try:
                    baseline_manifest = json.loads(manifest_path.read_text())
                except (OSError, ValueError) as exc:
                    raise CommitError(
                        'corrupted_baseline_manifest',
                        f'baseline release manifest {baseline_release_id} is unreadable: {exc}',
                    ) from exc

        baseline_dataset_pins = baseline_manifest.get('dataset_pins') or {}
        work_plan = []
        for table_name in CONTENT_TABLES:
            dataset = dataset_id_for(table_name)
            kind = TABLE_KINDS[table_name]
            current_pin = self.committed.get(dataset) or self.client.try_latest(dataset)
            if current_pin is None:
                continue
            baseline_pin = baseline_dataset_pins.get(dataset)
            if baseline_pin is None:
                if baseline_release is None:
                    raise CommitError(
                        'no_available_baseline',
                        f'cannot abandon cycle without an available baseline for dirtied dataset {dataset}',
                    )
                raise CommitError(
                    'no_available_baseline',
                    f'dataset {dataset} was dirtied but is missing from baseline release {baseline_release_id}',
                )
            work_plan.append((table_name, dataset, kind, current_pin, baseline_pin))

        control.discard_staged_checkpoints(cycle_id, epoch=epoch)
        new_committed = dict(self.committed)
        for table_name, dataset, kind, current_pin, baseline_pin in work_plan:
            control.require_epoch(epoch)
            current_version = current_pin['dataset']['version']
            baseline_version = baseline_pin['dataset']['version']
            if current_version == baseline_version:
                new_committed[dataset] = baseline_pin
                self._known_ids.pop(dataset, None)
                continue
            current_source = pin_group(current_pin, 'source')
            baseline_source = pin_group(baseline_pin, 'source')
            current_parquet = [
                (o.get('path'), o.get('digest'), o.get('bytes'))
                for o in pin_objects(current_pin, 'source')
                if str(o.get('path', '')).endswith('.parquet')
            ]
            baseline_parquet = [
                (o.get('path'), o.get('digest'), o.get('bytes'))
                for o in pin_objects(baseline_pin, 'source')
                if str(o.get('path', '')).endswith('.parquet')
            ]
            current_rel = current_pin.get('dataset', {}).get('relationship')
            relationship = baseline_pin.get('dataset', {}).get('relationship')
            same_data = (
                current_parquet == baseline_parquet
                and current_source.get('rows', 0) == baseline_source.get('rows', 0)
            )
            if same_data and current_rel == relationship:
                new_committed[dataset] = current_pin
                self._known_ids.pop(dataset, None)
                continue
            schema = kind_arrow_schema(kind)
            keys = self._update_keys_for(kind)
            if same_data:
                replacements_table = records_to_arrow(kind, ())
                deletions_table = None
            else:
                baseline_rows = table_records(self.client.read_arrow(baseline_pin, schema=schema))
                current_rows = table_records(self.client.read_arrow(current_pin, schema=schema))
                baseline_by_id = {r['id']: r for r in baseline_rows}
                current_by_id = {r['id']: r for r in current_rows}
                to_restore = [rec for rid, rec in baseline_by_id.items() if current_by_id.get(rid) != rec]
                deleted_rows = [rec for rid, rec in current_by_id.items() if rid not in baseline_by_id]
                replacements_table = records_to_arrow(kind, to_restore)
                deletions_table = (
                    records_to_arrow(kind, deleted_rows).select(list(keys))
                    if deleted_rows
                    else None
                )

            operation = self._operation(
                f'rollback-{dataset}',
                content_digest([current_version, baseline_version, keys]),
            )
            reverted_pin = self.client.update_table(
                dataset,
                operation,
                current_version,
                keys,
                replacements_table,
                deletions=deletions_table,
                relationship=relationship,
                stream_ipc=self.stream_ipc,
            )
            new_committed[dataset] = reverted_pin
            self._known_ids.pop(dataset, None)

        self.committed = new_committed
        self._save_committed_state()
        control.set_cycle_state(cycle_id, 'abandoned', epoch=epoch)

    def find_release(self, release_id: str) -> dict[str, Any] | None:
        manifest_path = self._release_manifest_path(release_id)
        if not manifest_path.is_file():
            return None
        try:
            data = json.loads(manifest_path.read_text())
            return data.get('release') if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def read_release(self, control: Any, release_id: str, tables: Any = None) -> dict[str, Any]:
        """Read an exact published release from its pinned ReleasePins (never latest)."""
        manifest_path = self._release_manifest_path(release_id)
        if not manifest_path.is_file():
            raise ReleaseError('unknown_release', 'no release record with this id', release_id=release_id)
        manifest = json.loads(manifest_path.read_text())
        record = manifest['release']
        table_pins = manifest.get('table_pins') or {}
        status = control.availability(release_id)
        if status is None:
            raise ReleaseError(
                'unreleased_release',
                'release record exists but publication never marked it available',
                release_id=release_id,
            )
        if status == 'retired':
            raise ReleaseError(
                'retired_release',
                'release is retired in the availability registry',
                release_id=release_id,
            )
        if status != 'available':
            raise ReleaseError('unreleased_release', f'release status is {status!r}', release_id=release_id)
        if record.get('contract_version') != CONTRACT_VERSION:
            raise ReleaseError(
                'contract_version_mismatch',
                f'release contract_version {record.get("contract_version")!r} does not match reader {CONTRACT_VERSION!r}',
                release_id=release_id,
            )
        all_entries = record['snapshots']
        for entry in all_entries:
            if 'snapshot_id' not in entry:
                continue
            table_name = entry['table']
            pin = table_pins.get(table_name)
            if pin is None:
                raise ReleaseError('missing_snapshot', f'{table_name} pin is missing', release_id=release_id)
            expected_uuid = self._table_uuid(table_name, pin=pin)
            if expected_uuid != entry['table_uuid']:
                raise ReleaseError('table_uuid_mismatch', f'{table_name} UUID differs from the release', release_id=release_id)
        entries = all_entries
        if tables is not None:
            requested = set(tables)
            known = {entry['table'] for entry in entries}
            unknown = requested - known
            if unknown:
                raise ReleaseError(
                    'unknown_table',
                    f'requested tables are not pinned by this release: {sorted(unknown)}',
                    release_id=release_id,
                )
            entries = [entry for entry in entries if entry['table'] in requested]
        if table_pins:
            inputs = {
                pin['dataset']['dataset']: version_ref(pin)
                for pin in table_pins.values()
            }
            self.client.capture_inputs(inputs)
        result = {}
        for entry in entries:
            table_name = entry['table']
            if 'snapshot_id' not in entry:
                result[table_name] = []
                continue
            pin = table_pins[table_name]
            kind = TABLE_KINDS[table_name]
            result[table_name] = table_records(
                self.client.read_arrow(pin, schema=kind_arrow_schema(kind))
            )
        return {
            'release': record,
            'tables': result,
            'dataset_pins': dict(table_pins),
        }
