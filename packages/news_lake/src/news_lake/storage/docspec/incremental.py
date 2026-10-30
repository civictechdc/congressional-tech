"""Incremental bridge delta propagation engine for DocSpecNewsViews.

CS300 Capstone Audit Architecture & Algorithm Overview:
------------------------------------------------------
The news lake maintains three materialized relational bridges (bridges.py):
1. ``entity_roots`` (keyed by ``entity_id``):
   Maps every person entity to its canonical root entity ID, resolving merges
   and identity decisions natively.
2. ``selected_mentions`` (keyed by ``mention_id``):
   Projects mention spans for winning extraction/disambiguation processor runs
   targeting active article versions.
3. ``survivor_items`` (keyed by ``item_id``):
   Projects active (non-superseded) item metadata, effective publication dates,
   story cluster membership, and cross-date syndication text groups.

Incremental Delta Algorithm:
---------------------------
Rather than scanning entire multi-gigabyte Iceberg tables or Parquet corpuses,
incremental updates detect forward changes from committed source dataset pins:
- Source deltas are read via ``DocSpecClient.changes_batches`` (forward changes)
  or targeted Parquet file differences.
- Entity Roots Delta:
  Computes transitive closures only over entity IDs affected by new
  ``news.identity_decisions`` or modified ``news.entities``. Uses targeted
  ``read_keys`` to fetch only necessary peer entities.
- Selected Mentions Delta:
  Evaluates processor selection criteria on incoming ``news.runs`` and
  ``news.mentions``. Only mentions belonging to reassigned version slots or
  new winning runs are recomputed.
- Survivor Items Delta:
  Tracks affected item IDs from incoming items, versions, discoveries, and story
  members. Resolves cross-date text syndication (identical text group IDs)
  by targeted ``read_keys`` lookups across text group peers, updating only
  the items whose syndication status flipped between unique and syndicated.
- Atomic Merge & Compaction:
  Derived changes and deletions are written natively to the bridge datasets
  via ``DocSpecClient.update_table``, keeping record snapshots consistent
  without full table rescans.
"""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from congress_shared.custody import write_atomic_bytes
from docspec_client import DocSpecFailure, restore_application_schema
from news_lake.analysis import bridges
from news_lake.analysis.cluster import text_group_key
from news_lake.analysis.views import _publication_date
from news_lake.context import parse_instant
from news_lake.contract.records import CONTENT_TABLES, TABLE_KINDS
from news_lake.identity.decisions import apply_decisions
from news_lake.storage.docspec.schema import (
    content_digest,
    dataset_id_for,
    kind_arrow_schema,
    pin_objects,
    pin_rows,
    pin_version,
    str_canonical,
    table_records,
)

_DATASET_TO_TABLE: dict[str, str] = {dataset_id_for(t): t for t in CONTENT_TABLES}


def _strip_nulls(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_nulls(v) for v in value]
    return value


def _compact_run_meta(run: Mapping[str, Any]) -> dict[str, Any]:
    """Extract minimal metadata required for run selection ranking."""
    return {
        'id': run['id'],
        'processor': run['processor'],
        'processor_version': run['processor_version'],
        'config_hash': run['config_hash'],
        'status': run['status'],
        'finished_at': run['finished_at'],
    }


def _is_run_eligible(
    run: Mapping[str, Any] | None,
    pinned_triples: set[tuple[str, str, str]],
) -> bool:
    """Check if a processor run matches configured selections and succeeded."""
    return (
        isinstance(run, (dict, Mapping))
        and run.get('status') == 'succeeded'
        and (run.get('processor'), run.get('processor_version'), run.get('config_hash')) in pinned_triples
    )


def _run_rank(run: Mapping[str, Any]) -> tuple[Any, str]:
    """Rank runs chronologically by completion instant, then by ID."""
    return (parse_instant(run['finished_at']), run['id'])


def _select_version_assignments(
    runs_by_id: Mapping[str, Mapping[str, Any]],
    selections: Sequence[Mapping[str, Any]] | None,
) -> dict[str, str]:
    """Select the highest-ranked winning run for each (processor, version_id) pair."""
    pinned = {
        (s['processor'], s['processor_version'], s['config_hash'])
        for s in (selections or ())
    }
    best: dict[str, tuple[tuple[Any, str], str]] = {}
    for run in runs_by_id.values():
        if not _is_run_eligible(run, pinned):
            continue
        rank = _run_rank(run)
        for ref in run.get('inputs', ()):
            if not isinstance(ref, (dict, Mapping)) or ref.get('kind') != 'version':
                continue
            key = f"{run['processor']}:{ref['id']}"
            if key not in best or rank > best[key][0]:
                best[key] = (rank, run['id'])
    return {key: run_id for key, (_, run_id) in best.items()}


def _unwrap_records(
    records_or_release_read: Any,
    selections: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], Sequence[Mapping[str, Any]], str | None]:
    """Extract flat record list, selections, and release ID from input."""
    if isinstance(records_or_release_read, dict) and 'tables' in records_or_release_read:
        flat = [
            record
            for rows in records_or_release_read['tables'].values()
            for record in rows
        ]
        release = records_or_release_read['release']
        if selections is None:
            selections = release.get('selections', ())
        return flat, selections, release['id']
    return (
        list(records_or_release_read),
        (() if selections is None else selections),
        None,
    )


def _extract_release_meta(
    records_or_release_read: Any,
    selections: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Extract selections and release ID if present."""
    if isinstance(records_or_release_read, dict) and 'release' in records_or_release_read:
        release = records_or_release_read['release']
        if selections is None:
            selections = release.get('selections', ())
        return list(selections), release.get('id')
    return list(() if selections is None else selections), None


def _summarize_source_pins(
    source_pins: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Produce a concise digest summary of source table pins for change detection."""
    summary = {}
    for table_name, pin in (source_pins or {}).items():
        summary[table_name] = {
            'version': pin_version(pin),
            'rows': pin_rows(pin),
            'objects': [
                obj.get('path')
                for obj in pin_objects(pin)
                if isinstance(obj, dict) and isinstance(obj.get('path'), str)
            ],
        }
    return summary


class IncrementalBridgeMixin:
    """Mixin implementing incremental relational bridge derivation and updates.

    Eliminates full table rescans by detecting forward changes from source table
    pins, fetching only affected keys via targeted IPC lookups, and updating
    bridge Parquet files via native delta operations.
    """

    # Contracts expected from host class (DocSpecNewsViews):
    client: Any
    pins: dict[str, Any]
    _bridge_versions: dict[str, Any]
    _mutation_counts: dict[str, int]
    _source_pins: dict[str, Any]
    _selections: list[dict[str, Any]]
    _decisions: dict[str, Any]
    _decision_roots: dict[str, Any]
    _runs: dict[str, Any]
    _compacted_pins: dict[str, Any]
    _pending_lifecycle_compactions: set[str]
    last_bridge_diff: dict[str, Any]
    lifecycle_compact_interval: int | None

    def _operation(self, label: str, digest: str) -> str:
        raise NotImplementedError

    def _save_views_state(self) -> None:
        raise NotImplementedError

    def _maybe_compact_table(self, dataset: str, pin: Any, incoming_files: int = 1) -> Any:
        raise NotImplementedError

    def compact_lifecycle(self, datasets: Any = None) -> Any:
        raise NotImplementedError

    def _record_view_mutation(self, dataset: str, *, is_bridge: bool = False) -> None:
        raise NotImplementedError

    def _committed_state_path(self) -> Path:
        raise NotImplementedError

    @staticmethod
    def _unwrap(records_or_release_read: Any, selections: Any = None) -> tuple[list[dict[str, Any]], Any, str | None]:
        return _unwrap_records(records_or_release_read, selections)

    @staticmethod
    def _extract_release_meta(records_or_release_read: Any, selections: Any = None) -> tuple[list[dict[str, Any]], str | None]:
        return _extract_release_meta(records_or_release_read, selections)

    def _resolve_source_pins(self, records_or_release_read: Any = None) -> dict[str, Any]:
        """Return ``{table_name: ReleasePin}`` from release_read or committed lake state."""
        raw_pins = None
        if isinstance(records_or_release_read, dict) and isinstance(records_or_release_read.get('dataset_pins'), dict):
            raw_pins = records_or_release_read['dataset_pins']
        if not raw_pins:
            cpath = self._committed_state_path()
            if cpath.is_file():
                try:
                    loaded = json.loads(cpath.read_text())
                    if isinstance(loaded, dict):
                        raw_pins = loaded
                except (OSError, ValueError):
                    raw_pins = None
        if not raw_pins:
            return {}
        resolved = {}
        for key, pin in raw_pins.items():
            if not isinstance(pin, dict):
                continue
            table_name = key if key in TABLE_KINDS else _DATASET_TO_TABLE.get(key)
            if table_name is not None:
                resolved[table_name] = pin
        return resolved

    @staticmethod
    def _summarize_source_pins(source_pins: Any) -> dict[str, dict[str, Any]]:
        return _summarize_source_pins(source_pins)

    def _read_table_delta(self, table_name: str, new_pin: Any, prior_info: Any) -> list[dict[str, Any]]:
        """Fetch only changed/added records for ``table_name`` since ``prior_info`` via ``/changes``."""
        if new_pin is None:
            return []
        new_version = pin_version(new_pin)
        new_rows = pin_rows(new_pin)
        new_objects = [
            obj.get('path') for obj in pin_objects(new_pin)
            if isinstance(obj, dict) and isinstance(obj.get('path'), str)
        ]
        if new_rows == 0:
            return []
        prior_version = (prior_info or {}).get('version')
        prior_rows = (prior_info or {}).get('rows', 0)
        prior_objects = (prior_info or {}).get('objects') or []
        if prior_version is not None and (
            new_version == prior_version
            or (new_objects == prior_objects and new_rows == prior_rows)
        ):
            return []

        dataset = dataset_id_for(table_name)
        kind = TABLE_KINDS[table_name]
        schema = kind_arrow_schema(kind)
        if prior_version is None or prior_rows == 0:
            return table_records(self.client.read_arrow(new_pin, schema=schema))
        try:
            prior_pin = self.client.release(dataset, prior_version)
            with self.client.changes_batches(
                prior_pin,
                new_pin,
                group='source',
                identity='occurrences',
                force_full=False,
            ) as (descriptor, reader):
                if isinstance(descriptor, dict) and descriptor.get('path') in ('forward_changes', 'unchanged'):
                    batches = list(reader)
                    change_table = pa.Table.from_batches(batches, schema=reader.schema)
                else:
                    change_table = None
            if change_table is not None:
                if change_table.num_rows == 0:
                    return []
                after_table = change_table.filter(pc.equal(change_table['side'], 'after'))
                if after_table.num_rows == 0:
                    return []
                values_col = after_table['values'].combine_chunks()
                unpacked = pa.Table.from_batches([pa.RecordBatch.from_struct_array(values_col)])
                restored = restore_application_schema(unpacked, expected_schema=schema)
                by_id = {}
                for row in table_records(restored):
                    by_id[row['id']] = row
                return list(by_id.values())
        except DocSpecFailure:
            pass

        # Fallback if prior_version is unavailable: read newly added Parquet objects
        added_paths = [
            p for p in new_objects
            if p.endswith('.parquet') and p not in set(prior_objects)
        ]
        if added_paths and all(Path(p).is_file() for p in added_paths):
            tables = [
                restore_application_schema(pq.read_table(p), expected_schema=schema)
                for p in added_paths
            ]
            by_id = {}
            for tbl in tables:
                for row in table_records(tbl):
                    by_id[row['id']] = row
            return list(by_id.values())
        return table_records(self.client.read_arrow(new_pin, schema=schema))

    def _init_incremental_state(
        self,
        records: Sequence[Mapping[str, Any]],
        selections: Sequence[Mapping[str, Any]] | None,
        source_pins: Mapping[str, Mapping[str, Any]] | None,
    ) -> None:
        """Seed baseline state caches (identity decisions, winning runs, source pins)."""
        self._source_pins = self._summarize_source_pins(source_pins)
        self._selections = [dict(s) for s in (selections or ())]
        self._decisions = {
            r['id']: r for r in records if r.get('kind') == 'identity_decision'
        }
        decision_eids = set()
        for dec in self._decisions.values():
            for field in ('left_id', 'right_id'):
                if field in dec:
                    decision_eids.add(dec[field])
        if self._decisions:
            decision_result = apply_decisions(records)
            roots = decision_result.get('roots', {})
            self._decision_roots = {eid: roots.get(eid, eid) for eid in sorted(decision_eids)}
        else:
            self._decision_roots = {}
        self._runs = {
            r['id']: _compact_run_meta(r)
            for r in records
            if r.get('kind') == 'run'
            and r.get('processor') != 'extract'
            and r.get('status') == 'succeeded'
        }

    def materialize(self, records_or_release_read: Any, selections: Any = None) -> dict[str, Any]:
        """Admit the three bridge datasets; stores and returns ``{dataset: ReleasePin}``."""
        source_pins = self._resolve_source_pins(records_or_release_read)
        if (
            isinstance(records_or_release_read, dict)
            and 'tables' in records_or_release_read
            and not records_or_release_read['tables']
            and source_pins
        ):
            selections, _ = self._extract_release_meta(records_or_release_read, selections)
            records = []
            for table_name, pin in source_pins.items():
                kind = TABLE_KINDS[table_name]
                records.extend(
                    table_records(self.client.read_arrow(pin, schema=kind_arrow_schema(kind)))
                )
        else:
            records, selections, _ = self._unwrap(records_or_release_read, selections)

        bridge_defs = {
            'entity_roots': (
                'entity_id',
                bridges.ENTITY_ROOTS_SCHEMA,
                bridges.entity_roots_rows(records),
            ),
            'selected_mentions': (
                'mention_id',
                bridges.SELECTED_MENTIONS_SCHEMA,
                bridges.selected_mentions_rows(records, selections),
            ),
            'survivor_items': (
                'item_id',
                bridges.SURVIVOR_ITEMS_SCHEMA,
                bridges.survivor_items_rows(records, selections),
            ),
        }
        pins = {}
        for dataset, (key_col, schema, rows) in bridge_defs.items():
            table = pa.Table.from_pylist(rows, schema=schema)
            stripped = _strip_nulls(rows)
            operation = self._operation(
                f'materialize-{dataset}', content_digest(stripped)
            )
            pin = self.client.run_table(table, dataset, operation, stream_ipc=True)
            pins[dataset] = pin
            self._bridge_versions[dataset] = pin_version(pin)
            self._compacted_pins.pop(dataset, None)
        self.pins.update(pins)
        self._init_incremental_state(records, selections, source_pins)
        self._save_views_state()
        return dict(pins)

    def _apply_bridge_delta(
        self,
        dataset: str,
        key_col: str,
        schema: pa.Schema,
        prior_pin: Mapping[str, Any],
        candidate_rows: list[dict[str, Any]],
        removed_keys: Sequence[str],
        prior_by_key: Mapping[str, Any],
        rows_recomputed: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Apply derived replacements and deletions to a bridge dataset natively."""
        prior_ver = pin_version(prior_pin)
        changed_rows = [
            row for row in candidate_rows
            if str_canonical(prior_by_key.get(row[key_col])) != str_canonical(_strip_nulls(row))
        ]
        removed_keys_clean = sorted(k for k in set(removed_keys) if k in prior_by_key)
        stats = {
            'rows_recomputed': rows_recomputed,
            'changed_rows': len(changed_rows),
            'removed_keys': len(removed_keys_clean),
            'full_table_reads': 0,
            'updated': bool(changed_rows or removed_keys_clean),
        }
        if not changed_rows and not removed_keys_clean:
            self.pins[dataset] = prior_pin
            self._bridge_versions[dataset] = prior_ver
            return dict(prior_pin), stats

        compacted = self._maybe_compact_table(
            dataset,
            prior_pin,
            incoming_files=1 if changed_rows else 0,
        )
        interval = self.lifecycle_compact_interval
        if interval and interval >= 1 and (
            compacted is not None
            or self._mutation_counts.get(dataset, 0) + 1 >= interval
        ):
            self.compact_lifecycle([dataset])
            self._pending_lifecycle_compactions.add(dataset)

        replacements_table = pa.Table.from_pylist(changed_rows, schema=schema)
        deletions_table = (
            pa.Table.from_pylist(
                [{key_col: key} for key in removed_keys_clean],
                schema=pa.schema([schema.field(key_col)]),
            )
            if removed_keys_clean
            else None
        )
        operation = self._operation(
            f'update-{dataset}',
            content_digest([prior_ver, _strip_nulls(changed_rows), removed_keys_clean]),
        )
        pin = self.client.update_table(
            dataset,
            operation,
            prior_ver,
            [key_col],
            replacements_table,
            deletions=deletions_table,
            stream_ipc=True,
        )
        self.pins[dataset] = pin
        self._bridge_versions[dataset] = pin_version(pin)
        self._compacted_pins.pop(dataset, None)
        self._record_view_mutation(dataset, is_bridge=True)
        return pin, stats

    def _update_entity_roots_incremental(
        self,
        prior_pin: Mapping[str, Any],
        source_pins: Mapping[str, Any],
        delta_entities: list[dict[str, Any]],
        delta_decisions: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Incrementally update entity_roots bridge when entities or decisions change."""
        if not delta_entities and not delta_decisions:
            return self._apply_bridge_delta(
                'entity_roots', 'entity_id', bridges.ENTITY_ROOTS_SCHEMA,
                prior_pin, [], [], {}, 0,
            )
        entities_pin = source_pins.get('news.entities')
        delta_entities_by_id = {r['id']: r for r in delta_entities}
        for dec in delta_decisions:
            self._decisions[dec['id']] = dec

        decision_eids = set()
        for dec in self._decisions.values():
            for field in ('left_id', 'right_id'):
                if field in dec:
                    decision_eids.add(dec[field])

        new_decision_roots = dict(self._decision_roots)
        if self._decisions and (delta_decisions or (decision_eids & set(delta_entities_by_id))):
            missing_dec_eids = sorted(decision_eids - set(delta_entities_by_id))
            dec_entities = dict(delta_entities_by_id)
            if missing_dec_eids and entities_pin is not None:
                fetched = table_records(
                    self.client.read_keys(
                        entities_pin, 'id', missing_dec_eids, schema=kind_arrow_schema('entity'),
                    )
                )
                for ent in fetched:
                    dec_entities[ent['id']] = ent
            decision_result = apply_decisions(
                list(dec_entities.values()) + list(self._decisions.values())
            )
            roots_map = decision_result.get('roots', {})
            new_decision_roots = {eid: roots_map.get(eid, eid) for eid in sorted(decision_eids)}

        affected_eids = set(delta_entities_by_id)
        for eid in set(self._decision_roots) | set(new_decision_roots):
            if self._decision_roots.get(eid, eid) != new_decision_roots.get(eid, eid):
                affected_eids.add(eid)
        for eid, root_id in new_decision_roots.items():
            if root_id in delta_entities_by_id:
                affected_eids.add(eid)
        self._decision_roots = new_decision_roots

        needed_entity_ids = set(affected_eids) | {
            self._decision_roots.get(eid, eid) for eid in affected_eids
        }
        entity_map = dict(delta_entities_by_id)
        missing_entity_ids = sorted(needed_entity_ids - set(entity_map))
        if missing_entity_ids and entities_pin is not None:
            fetched = table_records(
                self.client.read_keys(
                    entities_pin, 'id', missing_entity_ids, schema=kind_arrow_schema('entity'),
                )
            )
            for ent in fetched:
                entity_map[ent['id']] = ent

        prior_by_key = {}
        if affected_eids:
            prior_rows = table_records(
                self.client.read_keys(
                    prior_pin, 'entity_id', sorted(affected_eids),
                    schema=bridges.ENTITY_ROOTS_SCHEMA,
                )
            )
            prior_by_key = {row['entity_id']: _strip_nulls(row) for row in prior_rows}

        candidate_rows = []
        for eid in sorted(affected_eids):
            entity = entity_map.get(eid)
            if entity is None:
                continue
            root_id = self._decision_roots.get(eid, eid)
            root_entity = entity_map.get(root_id, entity)
            candidate_rows.append({
                'entity_id': eid,
                'person_root_id': root_id,
                'entity_type': root_entity.get('entity_type', entity['entity_type']),
                'name': root_entity.get('name', entity['name']),
            })
        return self._apply_bridge_delta(
            'entity_roots', 'entity_id', bridges.ENTITY_ROOTS_SCHEMA,
            prior_pin, candidate_rows, [], prior_by_key, len(candidate_rows),
        )

    def _update_selected_mentions_incremental(
        self,
        prior_pin: Mapping[str, Any],
        source_pins: Mapping[str, Any],
        delta_mentions: list[dict[str, Any]],
        reassigned_mention_versions: set[str],
        pinned_processors: set[str],
        is_winning_run: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Incrementally update selected_mentions bridge when mentions or runs change."""
        if not delta_mentions and not reassigned_mention_versions:
            return self._apply_bridge_delta(
                'selected_mentions', 'mention_id', bridges.SELECTED_MENTIONS_SCHEMA,
                prior_pin, [], [], {}, 0,
            )
        mentions_pin = source_pins.get('news.mentions')
        candidate_mentions = {m['id']: m for m in delta_mentions}
        prior_by_key = {}
        removed_keys = set()

        if reassigned_mention_versions:
            prior_ver_rows = table_records(
                self.client.read_keys(
                    prior_pin, 'version_id', sorted(reassigned_mention_versions),
                    schema=bridges.SELECTED_MENTIONS_SCHEMA,
                )
            )
            for row in prior_ver_rows:
                prior_by_key[row['mention_id']] = _strip_nulls(row)
                removed_keys.add(row['mention_id'])
            if mentions_pin is not None:
                source_ver_mentions = table_records(
                    self.client.read_keys(
                        mentions_pin, 'version_id', sorted(reassigned_mention_versions),
                        schema=kind_arrow_schema('mention'),
                    )
                )
                for m in source_ver_mentions:
                    candidate_mentions[m['id']] = m

        lookup_mids = sorted(set(candidate_mentions) - set(prior_by_key))
        if lookup_mids:
            existing_rows = table_records(
                self.client.read_keys(
                    prior_pin, 'mention_id', lookup_mids,
                    schema=bridges.SELECTED_MENTIONS_SCHEMA,
                )
            )
            for row in existing_rows:
                prior_by_key[row['mention_id']] = _strip_nulls(row)

        candidate_rows = []
        for mid in sorted(candidate_mentions):
            record = candidate_mentions[mid]
            if record.get('resolution') != 'resolved' or record.get('entity_id') is None:
                continue
            run = self._runs.get(record['run_id'])
            if run is None or run['processor'] not in pinned_processors:
                continue
            if not is_winning_run(run['processor'], record['version_id'], record['run_id']):
                continue
            removed_keys.discard(mid)
            candidate_rows.append({
                'mention_id': mid,
                'version_id': record['version_id'],
                'run_id': record['run_id'],
                'entity_id': record['entity_id'],
                'surface': record['surface'],
                'aboutness': record['aboutness'],
                'occurrences': [
                    {'field': span['field'], 'start': span['start'], 'end': span['end']}
                    for span in record['occurrences']
                ],
            })
        return self._apply_bridge_delta(
            'selected_mentions', 'mention_id', bridges.SELECTED_MENTIONS_SCHEMA,
            prior_pin, candidate_rows, sorted(removed_keys), prior_by_key, len(candidate_mentions),
        )

    def _update_survivor_items_incremental(
        self,
        prior_pin: Mapping[str, Any],
        source_pins: Mapping[str, Any],
        delta_items: list[dict[str, Any]],
        delta_versions: list[dict[str, Any]],
        delta_discoveries: list[dict[str, Any]],
        delta_story_members: list[dict[str, Any]],
        reassigned_cluster_versions: set[str],
        pinned_processors: set[str],
        is_winning_run: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Incrementally update survivor_items bridge with cross-date text syndication."""
        if (
            not delta_items
            and not delta_versions
            and not delta_discoveries
            and not delta_story_members
            and not reassigned_cluster_versions
        ):
            return self._apply_bridge_delta(
                'survivor_items', 'item_id', bridges.SURVIVOR_ITEMS_SCHEMA,
                prior_pin, [], [], {}, 0,
            )
        items_pin = source_pins.get('news.items')
        versions_pin = source_pins.get('news.versions')
        discoveries_pin = source_pins.get('news.discoveries')
        story_members_pin = source_pins.get('news.story_members')

        directly_affected_item_ids = (
            {r['id'] for r in delta_items}
            | {r['item_id'] for r in delta_versions}
            | {r['item_id'] for r in delta_discoveries}
        )
        story_affected_vids = (
            {r['version_id'] for r in delta_story_members}
            | set(reassigned_cluster_versions)
        )
        prior_by_key = {}
        if story_affected_vids:
            ver_survivors = table_records(
                self.client.read_keys(
                    prior_pin, 'current_version_id', sorted(story_affected_vids),
                    schema=bridges.SURVIVOR_ITEMS_SCHEMA,
                )
            )
            for row in ver_survivors:
                directly_affected_item_ids.add(row['item_id'])
                prior_by_key[row['item_id']] = _strip_nulls(row)

        missing_prior_iids = sorted(directly_affected_item_ids - set(prior_by_key))
        if missing_prior_iids:
            fetched_prior = table_records(
                self.client.read_keys(
                    prior_pin, 'item_id', missing_prior_iids,
                    schema=bridges.SURVIVOR_ITEMS_SCHEMA,
                )
            )
            for row in fetched_prior:
                prior_by_key[row['item_id']] = _strip_nulls(row)

        items_by_id = {
            r['id']: r for r in delta_items if r['id'] in directly_affected_item_ids
        }
        missing_item_ids = sorted(directly_affected_item_ids - set(items_by_id))
        if missing_item_ids and items_pin is not None:
            fetched_items = table_records(
                self.client.read_keys(
                    items_pin, 'id', missing_item_ids, schema=kind_arrow_schema('item'),
                )
            )
            for item in fetched_items:
                items_by_id[item['id']] = item

        removed_keys = set()
        active_survivors = []
        for iid in sorted(directly_affected_item_ids):
            item = items_by_id.get(iid)
            if item is None or item.get('superseded_by'):
                if iid in prior_by_key:
                    removed_keys.add(iid)
                continue
            active_survivors.append(item)

        needed_vids = {
            item['current_version_id']
            for item in active_survivors
            if item.get('current_version_id') is not None
        }
        versions_by_id = {
            r['id']: r for r in delta_versions if r['id'] in needed_vids
        }
        missing_vids = sorted(needed_vids - set(versions_by_id))
        if missing_vids and versions_pin is not None:
            fetched_versions = table_records(
                self.client.read_keys(
                    versions_pin, 'id', missing_vids, schema=kind_arrow_schema('version'),
                )
            )
            for ver in fetched_versions:
                versions_by_id[ver['id']] = ver

        items_needing_discoveries = []
        for item in active_survivors:
            vid = item.get('current_version_id')
            ver = versions_by_id.get(vid) if vid is not None else None
            if ver is None or _publication_date(ver.get('publication')) is None:
                items_needing_discoveries.append(item['id'])
        discoveries_by_item: dict[str, list[dict[str, Any]]] = {}
        if items_needing_discoveries:
            if discoveries_pin is not None:
                fetched_disc = table_records(
                    self.client.read_keys(
                        discoveries_pin, 'item_id', sorted(items_needing_discoveries),
                        schema=kind_arrow_schema('discovery'),
                    )
                )
                for d in fetched_disc:
                    discoveries_by_item.setdefault(d['item_id'], []).append(d)
            else:
                for d in delta_discoveries:
                    discoveries_by_item.setdefault(d['item_id'], []).append(d)

        story_by_version = {}
        vids_needing_story_lookup = set()
        for item in active_survivors:
            vid = item.get('current_version_id')
            if vid is None:
                continue
            prior_row = prior_by_key.get(item['id'])
            if (
                prior_row is not None
                and prior_row.get('current_version_id') == vid
                and vid not in story_affected_vids
            ):
                if 'story_id' in prior_row:
                    story_by_version[vid] = prior_row['story_id']
            else:
                vids_needing_story_lookup.add(vid)

        if vids_needing_story_lookup:
            story_members = []
            if story_members_pin is not None:
                story_members = table_records(
                    self.client.read_keys(
                        story_members_pin, 'version_id', sorted(vids_needing_story_lookup),
                        schema=kind_arrow_schema('story_member'),
                    )
                )
            else:
                story_members = [
                    m for m in delta_story_members if m['version_id'] in vids_needing_story_lookup
                ]
            for record in story_members:
                run = self._runs.get(record['run_id'])
                if run is None or run['processor'] not in pinned_processors:
                    continue
                if is_winning_run(run['processor'], record['version_id'], record['run_id']):
                    story_by_version.setdefault(record['version_id'], record['story_id'])

        candidate_by_id = {}
        for item in active_survivors:
            iid = item['id']
            vid = item.get('current_version_id')
            ver = versions_by_id.get(vid) if vid is not None else None
            pub_date_str = _publication_date(ver.get('publication')) if ver is not None else None
            if pub_date_str is None:
                discovery_dates = {
                    d
                    for discovery in discoveries_by_item.get(iid, ())
                    if (d := _publication_date(discovery.get('reported_publication'))) is not None
                }
                if len(discovery_dates) == 1:
                    pub_date_str = discovery_dates.pop()
            effective_pub_date = date.fromisoformat(pub_date_str) if pub_date_str is not None else None
            story_id = story_by_version.get(ver['id']) if ver is not None else None
            text_group_id = (
                text_group_key(ver['text'])
                if (ver is not None and isinstance(ver.get('text'), str))
                else None
            )
            candidate_by_id[iid] = {
                'item_id': iid,
                'outlet_id': item.get('outlet_id'),
                'current_version_id': ver['id'] if ver is not None else None,
                'effective_pub_date': effective_pub_date,
                'story_id': story_id,
                'text_group_id': text_group_id,
                'identical_text_group_id': None,
            }

        # Resolve cross-date syndication for affected text_group_ids via targeted read_keys
        affected_text_groups = {
            row['text_group_id']
            for row in candidate_by_id.values()
            if row.get('text_group_id') is not None
        } | {
            row['text_group_id']
            for row in prior_by_key.values()
            if row.get('text_group_id') is not None
        }
        untouched_peers_by_id = {}
        if affected_text_groups:
            peer_rows = table_records(
                self.client.read_keys(
                    prior_pin, 'text_group_id', sorted(affected_text_groups),
                    schema=bridges.SURVIVOR_ITEMS_SCHEMA,
                )
            )
            for peer in peer_rows:
                pid = peer['item_id']
                if pid not in prior_by_key:
                    prior_by_key[pid] = _strip_nulls(peer)
                if pid not in directly_affected_item_ids:
                    untouched_peers_by_id[pid] = {
                        'item_id': pid,
                        'outlet_id': peer.get('outlet_id'),
                        'current_version_id': peer.get('current_version_id'),
                        'effective_pub_date': peer.get('effective_pub_date'),
                        'story_id': peer.get('story_id'),
                        'text_group_id': peer.get('text_group_id'),
                        'identical_text_group_id': peer.get('identical_text_group_id'),
                    }

            group_counts: dict[str, int] = {}
            for row in list(candidate_by_id.values()) + list(untouched_peers_by_id.values()):
                tg = row.get('text_group_id')
                if tg is not None:
                    group_counts[tg] = group_counts.get(tg, 0) + 1

            for row in candidate_by_id.values():
                tg = row.get('text_group_id')
                row['identical_text_group_id'] = (
                    tg if (tg is not None and group_counts.get(tg, 0) > 1) else None
                )
            for pid, peer_row in untouched_peers_by_id.items():
                tg = peer_row.get('text_group_id')
                new_identical = tg if (tg is not None and group_counts.get(tg, 0) > 1) else None
                if peer_row.get('identical_text_group_id') != new_identical:
                    peer_row['identical_text_group_id'] = new_identical
                    candidate_by_id[pid] = peer_row

        candidate_rows = [candidate_by_id[iid] for iid in sorted(candidate_by_id)]
        rows_recomputed = len(active_survivors) + len(
            [pid for pid in untouched_peers_by_id if pid in candidate_by_id]
        )
        return self._apply_bridge_delta(
            'survivor_items', 'item_id', bridges.SURVIVOR_ITEMS_SCHEMA,
            prior_pin, candidate_rows, sorted(removed_keys), prior_by_key, rows_recomputed,
        )

    def update_bridges(self, records_or_release_read: Any, selections: Any = None) -> dict[str, Any]:
        """Derive incremental bridge updates from pinned release deltas and targeted ``read_keys``."""
        prior_pins = {
            dataset: (self.pins.get(dataset) or self.client.try_latest(dataset))
            for dataset in ('entity_roots', 'selected_mentions', 'survivor_items')
        }
        if any(pin is None for pin in prior_pins.values()):
            pins = self.materialize(records_or_release_read, selections=selections)
            self.last_bridge_diff = {
                ds: {
                    'rows_recomputed': pin_rows(pin),
                    'changed_rows': pin_rows(pin),
                    'removed_keys': 0,
                    'full_table_reads': 0,
                    'updated': True,
                }
                for ds, pin in pins.items()
            }
            return pins

        source_pins = self._resolve_source_pins(records_or_release_read)
        selections_list, _ = self._extract_release_meta(records_or_release_read, selections)

        bridge_source_tables = (
            'news.entities',
            'news.identity_decisions',
            'news.runs',
            'news.mentions',
            'news.items',
            'news.versions',
            'news.discoveries',
            'news.story_members',
        )
        delta_tables = {
            table_name: self._read_table_delta(
                table_name,
                source_pins.get(table_name),
                self._source_pins.get(table_name),
            )
            for table_name in bridge_source_tables
        }
        if not isinstance(records_or_release_read, dict):
            raw_records, _, _ = self._unwrap(records_or_release_read, selections)
            for table_name in bridge_source_tables:
                if not delta_tables[table_name]:
                    kind = TABLE_KINDS[table_name]
                    delta_tables[table_name] = [
                        r for r in raw_records if isinstance(r, dict) and r.get('kind') == kind
                    ]

        prior_runs = dict(self._runs)
        delta_runs = delta_tables['news.runs']
        for run in delta_runs:
            if run.get('processor') != 'extract' and run.get('status') == 'succeeded':
                self._runs[run['id']] = _compact_run_meta(run)

        normalized_selections = [dict(s) for s in selections_list]
        pinned_triples = {
            (s['processor'], s['processor_version'], s['config_hash'])
            for s in normalized_selections
        }
        pinned_processors = {s['processor'] for s in normalized_selections}
        delta_version_ids = {r['id'] for r in delta_tables['news.versions']}

        max_prior_rank_by_proc: dict[str, Any] = {}
        for r in prior_runs.values():
            if _is_run_eligible(r, pinned_triples):
                proc = r['processor']
                rank = _run_rank(r)
                if proc not in max_prior_rank_by_proc or rank > max_prior_rank_by_proc[proc]:
                    max_prior_rank_by_proc[proc] = rank

        max_eligible_rank_by_proc = dict(max_prior_rank_by_proc)
        eligible_delta_runs = []
        has_backdated_delta_run = False
        for run in delta_runs:
            if not _is_run_eligible(run, pinned_triples):
                continue
            eligible_delta_runs.append(run)
            proc = run['processor']
            rank = _run_rank(run)
            if proc in max_prior_rank_by_proc and rank < max_prior_rank_by_proc[proc]:
                has_backdated_delta_run = True
            if proc not in max_eligible_rank_by_proc or rank > max_eligible_rank_by_proc[proc]:
                max_eligible_rank_by_proc[proc] = rank

        reassigned_mention_versions: set[str] = set()
        reassigned_cluster_versions: set[str] = set()
        delta_selected_runs: dict[str, str] = {}
        full_selected_runs: list[dict[str, str] | None] = [None]

        def _load_full_selected_runs() -> dict[str, str]:
            if full_selected_runs[0] is not None:
                return full_selected_runs[0]
            runs_pin = source_pins.get('news.runs')
            if runs_pin is not None:
                all_runs = {
                    r['id']: r
                    for r in table_records(
                        self.client.read_arrow(runs_pin, schema=kind_arrow_schema('run'))
                    )
                    if r.get('processor') != 'extract' and r.get('status') == 'succeeded'
                }
            else:
                all_runs = {r['id']: r for r in delta_runs if r.get('processor') != 'extract'}
            full_selected_runs[0] = _select_version_assignments(all_runs, normalized_selections)
            return full_selected_runs[0]

        if normalized_selections != self._selections or has_backdated_delta_run:
            runs_pin = source_pins.get('news.runs')
            if runs_pin is not None:
                all_runs = {
                    r['id']: r
                    for r in table_records(
                        self.client.read_arrow(runs_pin, schema=kind_arrow_schema('run'))
                    )
                    if r.get('processor') != 'extract' and r.get('status') == 'succeeded'
                }
            else:
                all_runs = {r['id']: r for r in delta_runs if r.get('processor') != 'extract'}
            old_selected = _select_version_assignments(
                {rid: all_runs[rid] for rid in prior_runs if rid in all_runs},
                self._selections,
            )
            new_selected = _select_version_assignments(all_runs, normalized_selections)
            full_selected_runs[0] = new_selected
            for slot_key in set(old_selected) | set(new_selected):
                old_run = old_selected.get(slot_key)
                new_run = new_selected.get(slot_key)
                if old_run != new_run:
                    proc, vid = slot_key.split(':', 1)
                    if proc == 'mentions' and (old_run is not None or vid not in delta_version_ids):
                        reassigned_mention_versions.add(vid)
                    elif proc == 'cluster':
                        reassigned_cluster_versions.add(vid)
        else:
            for run in sorted(eligible_delta_runs, key=_run_rank):
                proc = run['processor']
                for ref in run.get('inputs', ()):
                    if not isinstance(ref, (dict, Mapping)) or ref.get('kind') != 'version':
                        continue
                    vid = ref['id']
                    delta_selected_runs[f"{proc}:{vid}"] = run['id']
                    if vid not in delta_version_ids:
                        if proc == 'mentions':
                            reassigned_mention_versions.add(vid)
                        elif proc == 'cluster':
                            reassigned_cluster_versions.add(vid)

        def is_winning_run(processor: str, version_id: str, run_id: str) -> bool:
            run = self._runs.get(run_id)
            if not _is_run_eligible(run, pinned_triples):
                return False
            if full_selected_runs[0] is not None:
                return full_selected_runs[0].get(f"{processor}:{version_id}") == run_id
            slot_key = f"{processor}:{version_id}"
            if slot_key in delta_selected_runs:
                return delta_selected_runs[slot_key] == run_id
            if _run_rank(run) == max_eligible_rank_by_proc.get(processor):
                return True
            return _load_full_selected_runs().get(slot_key) == run_id

        self._selections = normalized_selections

        updated_pins = {}
        diff_summary = {}

        roots_pin, roots_stats = self._update_entity_roots_incremental(
            prior_pins['entity_roots'],
            source_pins,
            delta_tables['news.entities'],
            delta_tables['news.identity_decisions'],
        )
        updated_pins['entity_roots'] = roots_pin
        diff_summary['entity_roots'] = roots_stats

        mentions_pin, mentions_stats = self._update_selected_mentions_incremental(
            prior_pins['selected_mentions'],
            source_pins,
            delta_tables['news.mentions'],
            reassigned_mention_versions,
            pinned_processors,
            is_winning_run,
        )
        updated_pins['selected_mentions'] = mentions_pin
        diff_summary['selected_mentions'] = mentions_stats

        survivor_pin, survivor_stats = self._update_survivor_items_incremental(
            prior_pins['survivor_items'],
            source_pins,
            delta_tables['news.items'],
            delta_tables['news.versions'],
            delta_tables['news.discoveries'],
            delta_tables['news.story_members'],
            reassigned_cluster_versions,
            pinned_processors,
            is_winning_run,
        )
        updated_pins['survivor_items'] = survivor_pin
        diff_summary['survivor_items'] = survivor_stats

        if source_pins:
            self._source_pins = self._summarize_source_pins(source_pins)
        self.last_bridge_diff = diff_summary
        self._save_views_state()
        return dict(updated_pins)
