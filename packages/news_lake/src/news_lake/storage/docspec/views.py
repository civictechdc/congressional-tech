"""Materialized relational bridges and C9 views in the DocSpec engine."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from congress_shared.custody import write_atomic_bytes
from news_lake.analysis import bridges
from news_lake.analysis.views import _by_kind, _merge_spans
from news_lake.storage.docspec.compaction import _DocSpecDatasetManager
from news_lake.storage.docspec.export import (
    _ensure_release_read as _export_ensure_release_read,
    export_authorized as _export_authorized,
)
from news_lake.storage.docspec.incremental import IncrementalBridgeMixin
from news_lake.storage.docspec.schema import (
    DEFAULT_COMPACT_FILE_THRESHOLD,
    DEFAULT_COMPACT_TARGET_FILE_BYTES,
    DEFAULT_LIFECYCLE_COMPACT_INTERVAL,
    DEFINITION,
    content_digest,
    kind_arrow_schema,
    pin_version,
    sanitize_id,
    table_records,
    version_ref,
)


class DocSpecNewsViews(_DocSpecDatasetManager, IncrementalBridgeMixin):
    """Materialize relational bridges natively and run C9 views on them.

    ``materialize`` admits ``entity_roots``, ``selected_mentions`` and
    ``survivor_items`` (``analysis.bridges``) as datasets and records their
    exact ``ReleasePin``s in ``self.pins``; ``update_bridges`` derives changed
    and removed bridge keys incrementally from pinned source dataset deltas and
    targeted ``read_keys`` lookups without full-corpus scans;
    ``politician_articles`` refreshes a native chained join/aggregate pipeline
    over ``selected_mentions``, ``entity_roots``, and ``survivor_items``;
    ``coverage_daily`` refreshes a native Date32-keyed aggregate over
    ``survivor_items`` with two-stage cross-date syndication.
    """

    SELECTED_MENTIONS_SCHEMA = bridges.SELECTED_MENTIONS_SCHEMA

    def __init__(
        self,
        client: Any,
        workspace_suffix: str = '',
        *,
        pins: Mapping[str, Any] | None = None,
        lifecycle_compact_interval: int = DEFAULT_LIFECYCLE_COMPACT_INTERVAL,
        compact_file_threshold: int = DEFAULT_COMPACT_FILE_THRESHOLD,
        compact_target_file_bytes: int = DEFAULT_COMPACT_TARGET_FILE_BYTES,
    ) -> None:
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
        state = self._load_views_state()
        self.pins: dict[str, Any] = dict(pins) if pins is not None else state['pins']
        self._bridge_versions: dict[str, Any] = state['bridge_versions'] if pins is None else {}
        self._mutation_counts: dict[str, int] = state['mutation_counts'] if pins is None else {}
        self._source_pins: dict[str, Any] = state['source_pins'] if pins is None else {}
        self._selections: list[dict[str, Any]] = state['selections'] if pins is None else []
        self._decisions: dict[str, Any] = state['decisions'] if pins is None else {}
        self._decision_roots: dict[str, Any] = state['decision_roots'] if pins is None else {}
        self._runs: dict[str, Any] = state['runs'] if pins is None else {}
        if pins is not None:
            self._compacted_pins = {}
        self._pending_lifecycle_compactions: set[str] = set()
        self.last_bridge_diff: dict[str, Any] = {}

    # -- _DocSpecDatasetManager hooks ----------------------------------------

    @property
    def _active_pins(self) -> dict[str, Any]:
        return self.pins

    def _resolve_dataset_id(self, dataset: str) -> str:
        return sanitize_id(dataset)

    def _save_dataset_state(self) -> None:
        self._save_views_state()

    # -- State Persistence ---------------------------------------------------

    def _views_state_path(self) -> Path:
        suffix = f'-{self.workspace_suffix}' if self.workspace_suffix else ''
        return self.client.workspace / f'.news_lake_views{suffix}.json'

    def _committed_state_path(self) -> Path:
        suffix = f'-{self.workspace_suffix}' if self.workspace_suffix else ''
        return self.client.workspace / f'.news_lake_committed{suffix}.json'

    def _load_views_state(self) -> dict[str, Any]:
        empty: dict[str, Any] = {
            'pins': {},
            'bridge_versions': {},
            'mutation_counts': {},
            'source_pins': {},
            'selections': [],
            'decisions': {},
            'decision_roots': {},
            'runs': {},
        }
        path = self._views_state_path()
        if not path.is_file():
            self._compacted_pins = {}
            return empty
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                self._compacted_pins = {}
                return empty
            pins = dict(data.get('pins') or {})
            compacted_pins = {}
            raw_compacted = data.get('compacted_pins')
            if isinstance(raw_compacted, dict):
                for ds, entry in raw_compacted.items():
                    if not isinstance(entry, dict) or not isinstance(entry.get('replacement'), dict):
                        continue
                    pin = pins.get(ds)
                    selected_ver = pin_version(pin)
                    if selected_ver and entry.get('version') == selected_ver:
                        compacted_pins[str(ds)] = {
                            'version': selected_ver,
                            'replacement': entry['replacement'],
                        }
            self._compacted_pins = compacted_pins
            return {
                'pins': pins,
                'bridge_versions': dict(data.get('bridge_versions') or {}),
                'mutation_counts': {
                    str(k): int(v)
                    for k, v in (data.get('mutation_counts') or {}).items()
                    if isinstance(v, int) and not isinstance(v, bool)
                },
                'source_pins': dict(data.get('source_pins') or {}),
                'selections': list(data.get('selections') or ()),
                'decisions': dict(data.get('decisions') or {}),
                'decision_roots': dict(data.get('decision_roots') or {}),
                'runs': dict(data.get('runs') or {}),
            }
        except (OSError, ValueError):
            self._compacted_pins = {}
            return empty

    def _save_views_state(self) -> None:
        path = self._views_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        valid_compacted = {}
        for ds, entry in self._compacted_pins.items():
            if not isinstance(entry, dict) or not isinstance(entry.get('replacement'), dict):
                continue
            pin = self.pins.get(ds)
            selected_ver = pin_version(pin)
            if selected_ver is None or entry.get('version') == selected_ver:
                valid_compacted[ds] = entry
        self._compacted_pins = valid_compacted
        write_atomic_bytes(
            path,
            json.dumps(
                {
                    'pins': self.pins,
                    'bridge_versions': self._bridge_versions,
                    'mutation_counts': self._mutation_counts,
                    'source_pins': self._source_pins,
                    'selections': self._selections,
                    'decisions': self._decisions,
                    'decision_roots': self._decision_roots,
                    'runs': self._runs,
                    'compacted_pins': self._compacted_pins,
                },
                ensure_ascii=False,
                separators=(',', ':'),
                allow_nan=False,
                default=str,
            ).encode('utf-8'),
            temp_mode='fixed',
            fsync=False,
        )

    def _record_view_mutation(self, dataset: str, *, is_bridge: bool = False) -> None:
        self._mutation_counts[dataset] = self._mutation_counts.get(dataset, 0) + 1
        interval = self.lifecycle_compact_interval
        if not is_bridge and interval and interval >= 1 and (
            self._mutation_counts[dataset] >= interval
        ):
            self.compact_lifecycle([dataset])

    def _flush_pending_bridge_compactions(self, datasets: Sequence[str]) -> dict[str, Any]:
        interval = self.lifecycle_compact_interval
        if not interval or interval < 1:
            for ds in datasets:
                self._pending_lifecycle_compactions.discard(ds)
            return {}
        due = [ds for ds in datasets if ds in self._pending_lifecycle_compactions]
        for ds in due:
            self._pending_lifecycle_compactions.discard(ds)
        return self.compact_lifecycle(due) if due else {}

    # -- Pinned Dataset Helpers ----------------------------------------------

    def _pin(self, dataset: str) -> dict[str, Any]:
        pin = self.pins.get(dataset)
        if pin is None:
            pin = self.client.latest(dataset)
            self.pins[dataset] = pin
        return pin

    def _bridge_pin_for_refresh(self, dataset: str, view_dataset: str, mode: str) -> dict[str, Any]:
        """Return pinned bridge version; sync from client if updated directly before incremental."""
        pin = self._pin(dataset)
        if mode == 'incremental':
            view_pin = self.pins.get(view_dataset)
            if view_pin is not None:
                related = view_pin.get('dataset', {}).get('related') or {}
                consumed_inputs = (related.get('coverage') or {}).get('inputs') or {}
                consumed_ref = consumed_inputs.get(dataset)
                if consumed_ref == version_ref(pin):
                    latest_pin = self.client.try_latest(dataset)
                    if latest_pin is not None and version_ref(latest_pin) != version_ref(pin):
                        self.pins[dataset] = latest_pin
                        return latest_pin
        return pin

    def _base_version(self, dataset: str, mode: str) -> str | None:
        if mode == 'full':
            return None
        pin = self.pins.get(dataset) or self.client.try_latest(dataset)
        if pin is None:
            raise ValueError(f"mode='incremental' requires a previous {dataset} version")
        self.pins[dataset] = pin
        return pin_version(pin)

    # -- View Transform Specs ------------------------------------------------

    def _refresh_join_spec(self, base: str | None, mode: str, mentions_pin: Any = None, roots_pin: Any = None) -> dict[str, Any]:
        if mentions_pin is None:
            mentions_pin = self._bridge_pin_for_refresh(
                'selected_mentions', 'politician_articles', mode
            )
        if roots_pin is None:
            roots_pin = self._bridge_pin_for_refresh(
                'entity_roots', 'politician_articles', mode
            )
        return dict(
            dataset='politician_articles', base=base, definition=DEFINITION, mode=mode,
            operation=self._operation(
                f'pa-{mode}',
                content_digest([base, mode, version_ref(mentions_pin), version_ref(roots_pin)]),
            ),
            transform={
                'kind': 'join',
                'left': version_ref(mentions_pin),
                'right': version_ref(roots_pin),
                'join': {
                    'keys': [{'left': 'entity_id', 'right': 'entity_id'}],
                    'kind': 'inner', 'nulls': 'never',
                    'cardinality': 'many_to_one',
                    'fields': [
                        {'side': 'left', 'field': 'entity_id', 'name': 'entity_id'},
                        {'side': 'left', 'field': 'mention_id', 'name': 'mention_id'},
                        {'side': 'left', 'field': 'version_id', 'name': 'version_id'},
                        {'side': 'left', 'field': 'run_id', 'name': 'run_id'},
                        {'side': 'left', 'field': 'surface', 'name': 'surface'},
                        {'side': 'left', 'field': 'aboutness', 'name': 'aboutness'},
                        {'side': 'left', 'field': 'occurrences', 'name': 'occurrences'},
                        {'side': 'right', 'field': 'person_root_id', 'name': 'person_root_id'},
                        {'side': 'right', 'field': 'entity_type', 'name': 'entity_type'},
                    ],
                },
            },
        )

    def _refresh_politician_mentions_roots_spec(
        self, base: str | None, mode: str, mentions_pin: Any = None, roots_pin: Any = None,
    ) -> dict[str, Any]:
        if mentions_pin is None:
            mentions_pin = self._bridge_pin_for_refresh(
                'selected_mentions', 'politician_mentions_roots', mode
            )
        if roots_pin is None:
            roots_pin = self._bridge_pin_for_refresh(
                'entity_roots', 'politician_mentions_roots', mode
            )
        return dict(
            dataset='politician_mentions_roots', base=base, definition=DEFINITION, mode=mode,
            operation=self._operation(
                f'pmr-{mode}',
                content_digest([base, mode, version_ref(mentions_pin), version_ref(roots_pin)]),
            ),
            transform={
                'kind': 'join',
                'left': version_ref(mentions_pin),
                'right': version_ref(roots_pin),
                'join': {
                    'keys': [{'left': 'entity_id', 'right': 'entity_id'}],
                    'kind': 'inner', 'nulls': 'never',
                    'cardinality': 'many_to_one',
                    'filter': {
                        'kind': 'eq',
                        'field': 'entity_type',
                        'value': 'person',
                    },
                    'fields': [
                        {'side': 'left', 'field': 'entity_id', 'name': 'entity_id'},
                        {'side': 'left', 'field': 'mention_id', 'name': 'mention_id'},
                        {'side': 'left', 'field': 'version_id', 'name': 'version_id'},
                        {'side': 'left', 'field': 'run_id', 'name': 'run_id'},
                        {'side': 'left', 'field': 'surface', 'name': 'surface'},
                        {'side': 'left', 'field': 'aboutness', 'name': 'aboutness'},
                        {'side': 'left', 'field': 'occurrences', 'name': 'occurrences'},
                        {'side': 'right', 'field': 'person_root_id', 'name': 'person_root_id'},
                        {'side': 'right', 'field': 'entity_type', 'name': 'entity_type'},
                    ],
                },
            },
        )

    def _refresh_politician_mention_items_spec(
        self, base: str | None, mode: str, mentions_roots_pin: Any, survivor_pin: Any = None,
    ) -> dict[str, Any]:
        if survivor_pin is None:
            survivor_pin = self._bridge_pin_for_refresh(
                'survivor_items', 'politician_articles', mode
            )
        return dict(
            dataset='politician_articles', base=base, definition=DEFINITION, mode=mode,
            operation=self._operation(
                f'pmi-{mode}',
                content_digest([base, mode, version_ref(mentions_roots_pin), version_ref(survivor_pin)]),
            ),
            transform={
                'kind': 'join',
                'left': version_ref(mentions_roots_pin),
                'right': version_ref(survivor_pin),
                'join': {
                    'keys': [{'left': 'version_id', 'right': 'current_version_id'}],
                    'kind': 'inner', 'nulls': 'never',
                    'cardinality': 'many_to_one',
                    'fields': [
                        {'side': 'left', 'field': 'mention_id', 'name': 'mention_id'},
                        {'side': 'left', 'field': 'version_id', 'name': 'version_id'},
                        {'side': 'left', 'field': 'run_id', 'name': 'run_id'},
                        {'side': 'left', 'field': 'entity_id', 'name': 'entity_id'},
                        {'side': 'left', 'field': 'surface', 'name': 'surface'},
                        {'side': 'left', 'field': 'aboutness', 'name': 'aboutness'},
                        {'side': 'left', 'field': 'occurrences', 'name': 'occurrences'},
                        {'side': 'left', 'field': 'person_root_id', 'name': 'person_root_id'},
                        {'side': 'right', 'field': 'item_id', 'name': 'item_id'},
                    ],
                },
            },
        )

    def _refresh_politician_articles_groups_spec(
        self, base: str | None, mode: str, mention_items_pin: Any,
    ) -> dict[str, Any]:
        return dict(
            dataset='politician_articles_groups', base=base, definition=DEFINITION, mode=mode,
            operation=self._operation(
                f'pag-{mode}',
                content_digest([base, mode, version_ref(mention_items_pin)]),
            ),
            transform={
                'kind': 'aggregate',
                'input': version_ref(mention_items_pin),
                'grouping': {
                    'keys': ['person_root_id', 'item_id'],
                    'aggregates': [
                        {
                            'name': 'version_id',
                            'function': {
                                'kind': 'first_value_by',
                                'field': 'version_id',
                                'order_by': ['mention_id'],
                            },
                        },
                        {'name': 'entity_ids', 'function': {'kind': 'collect_set', 'field': 'entity_id'}},
                        {'name': 'run_ids', 'function': {'kind': 'collect_set', 'field': 'run_id'}},
                        {'name': 'aboutness', 'function': {'kind': 'collect_set', 'field': 'aboutness'}},
                        {'name': 'surfaces', 'function': {'kind': 'collect_set', 'field': 'surface'}},
                    ],
                },
            },
        )

    def refresh_politician_articles_chained(
        self, records_or_release_read: Any, mode: str = 'full', selections: Any = None,
    ) -> list[dict[str, Any]]:
        """Refresh ``politician_articles`` via 3-stage Join -> Join -> Aggregate (ss-65bz)."""
        _, release_id = self._extract_release_meta(records_or_release_read, selections)
        source_pins = self._resolve_source_pins(records_or_release_read)
        versions_pin = source_pins.get('news.versions')

        mentions_pin = self._bridge_pin_for_refresh(
            'selected_mentions', 'politician_mentions_roots', mode
        )
        roots_pin = self._bridge_pin_for_refresh(
            'entity_roots', 'politician_mentions_roots', mode
        )
        survivor_pin = self._bridge_pin_for_refresh(
            'survivor_items', 'politician_articles', mode
        )

        base_mr = self._base_version('politician_mentions_roots', mode)
        mr_spec = self._refresh_politician_mentions_roots_spec(
            base_mr, mode, mentions_pin=mentions_pin, roots_pin=roots_pin
        )
        mr_pin = self.client.refresh(mr_spec)
        self.pins['politician_mentions_roots'] = mr_pin

        base_mi = self._base_version('politician_articles', mode)
        mi_spec = self._refresh_politician_mention_items_spec(
            base_mi, mode, mr_pin, survivor_pin=survivor_pin
        )
        mi_pin = self.client.refresh(mi_spec)
        self.pins['politician_mention_items'] = mi_pin
        self.pins['politician_articles'] = mi_pin

        base_pag = self._base_version('politician_articles_groups', mode)
        pag_spec = self._refresh_politician_articles_groups_spec(base_pag, mode, mi_pin)
        pag_pin = self.client.refresh(pag_spec)
        self.pins['politician_articles_groups'] = pag_pin

        self._flush_pending_bridge_compactions(
            ('selected_mentions', 'entity_roots', 'survivor_items')
        )
        self._record_view_mutation('politician_mentions_roots')
        self._record_view_mutation('politician_articles')
        self._record_view_mutation('politician_articles_groups')
        self._save_views_state()

        group_cols = [
            'person_root_id', 'item_id', 'version_id',
            'entity_ids', 'run_ids', 'aboutness', 'surfaces',
        ]
        grouped_rows = list(self.client.iter_records(pag_pin, columns=group_cols))
        if not grouped_rows:
            return []

        occ_cols = ['person_root_id', 'item_id', 'surface', 'occurrences']
        spans_by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in self.client.iter_records(mi_pin, columns=occ_cols):
            key = (row['person_root_id'], row['item_id'])
            spans = spans_by_key.setdefault(key, [])
            for span in (row.get('occurrences') or ()):
                spans.append({
                    'field': span['field'],
                    'surface': row['surface'],
                    'start': span['start'],
                    'end': span['end'],
                })

        grouped_version_ids = sorted({row['version_id'] for row in grouped_rows})
        if versions_pin is not None:
            ver_rows = table_records(
                self.client.read_keys(
                    versions_pin,
                    'id',
                    grouped_version_ids,
                    columns=['id', 'title', 'text'],
                    schema=kind_arrow_schema('version'),
                )
            )
            versions = {row['id']: row for row in ver_rows}
        else:
            records, _, _ = self._unwrap(records_or_release_read)
            versions = _by_kind(records, 'version')

        result = []
        for row in grouped_rows:
            key = (row['person_root_id'], row['item_id'])
            version = versions.get(row['version_id'])
            result.append({
                'release_id': release_id,
                'person_root_id': row['person_root_id'],
                'entity_ids': list(row.get('entity_ids') or ()),
                'item_id': row['item_id'],
                'version_id': row['version_id'],
                'run_ids': list(row.get('run_ids') or ()),
                'aboutness': list(row.get('aboutness') or ()),
                'surfaces': list(row.get('surfaces') or ()),
                'spans': _merge_spans(spans_by_key.get(key, ()), version=version),
            })
        return sorted(result, key=lambda r: (r['person_root_id'], r['item_id']))

    def politician_articles(
        self,
        records_or_release_read: Any,
        mode: str = 'full',
        selections: Any = None,
        *,
        chained: bool = True,
    ) -> list[dict[str, Any]]:
        """The ``politician_articles`` view through native join transforms."""
        if chained:
            return self.refresh_politician_articles_chained(
                records_or_release_read, mode=mode, selections=selections
            )
        _, release_id = self._extract_release_meta(records_or_release_read, selections)
        source_pins = self._resolve_source_pins(records_or_release_read)
        versions_pin = source_pins.get('news.versions')
        base = self._base_version('politician_articles', mode)
        mentions_pin = self._bridge_pin_for_refresh(
            'selected_mentions', 'politician_articles', mode
        )
        roots_pin = self._bridge_pin_for_refresh(
            'entity_roots', 'politician_articles', mode
        )
        survivor_pin = self._pin('survivor_items')
        spec = self._refresh_join_spec(base, mode, mentions_pin=mentions_pin, roots_pin=roots_pin)
        pin = self.client.refresh(spec)
        self.pins['politician_articles'] = pin
        self._flush_pending_bridge_compactions(('selected_mentions', 'entity_roots'))
        self._record_view_mutation('politician_articles')
        self._save_views_state()
        join_cols = [
            'entity_id', 'mention_id', 'version_id', 'run_id',
            'surface', 'aboutness', 'occurrences', 'person_root_id', 'entity_type',
        ]
        joined = list(self.client.iter_records(pin, columns=join_cols))
        return self._assemble_politician_articles(
            records_or_release_read,
            release_id,
            joined,
            survivor_pin=survivor_pin,
            versions_pin=versions_pin,
        )

    def _assemble_politician_articles(
        self, records_or_release_read: Any, release_id: str | None, joined: Sequence[Mapping[str, Any]],
        *, survivor_pin: Any = None, versions_pin: Any = None,
    ) -> list[dict[str, Any]]:
        if survivor_pin is None:
            survivor_pin = self._pin('survivor_items')
        needed_versions = sorted({
            row['version_id']
            for row in joined
            if row.get('entity_type') == 'person' and isinstance(row.get('version_id'), str)
        })
        if needed_versions:
            survivor_rows = table_records(
                self.client.read_keys(
                    survivor_pin,
                    'current_version_id',
                    needed_versions,
                    columns=['current_version_id', 'item_id'],
                    schema=bridges.SURVIVOR_ITEMS_SCHEMA,
                )
            )
        else:
            survivor_rows = []
        item_of_version = {
            row['current_version_id']: row['item_id']
            for row in survivor_rows if 'current_version_id' in row
        }
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for row in joined:
            if row.get('entity_type') != 'person':
                continue
            version_id = row['version_id']
            item_id = item_of_version.get(version_id)
            if item_id is None:
                continue
            key = (row['person_root_id'], item_id)
            entry = grouped.setdefault(key, {
                'release_id': release_id,
                'person_root_id': key[0],
                'entity_ids': set(), 'item_id': item_id, 'version_id': version_id,
                'run_ids': set(), 'aboutness': set(), 'surfaces': set(), '_spans': [],
            })
            entry['entity_ids'].add(row['entity_id'])
            entry['run_ids'].add(row['run_id'])
            entry['aboutness'].add(row['aboutness'])
            entry['surfaces'].add(row['surface'])
            entry['_spans'].extend(
                {
                    'field': span['field'], 'surface': row['surface'],
                    'start': span['start'], 'end': span['end'],
                }
                for span in (row.get('occurrences') or ())
            )
        grouped_version_ids = sorted({entry['version_id'] for entry in grouped.values()})
        if not grouped_version_ids:
            versions = {}
        elif versions_pin is not None:
            ver_rows = table_records(
                self.client.read_keys(
                    versions_pin,
                    'id',
                    grouped_version_ids,
                    columns=['id', 'title', 'text'],
                    schema=kind_arrow_schema('version'),
                )
            )
            versions = {row['id']: row for row in ver_rows}
        else:
            records, _, _ = self._unwrap(records_or_release_read)
            versions = _by_kind(records, 'version')
        result = []
        for entry in grouped.values():
            version = versions.get(entry['version_id'])
            result.append({
                'release_id': entry['release_id'],
                'person_root_id': entry['person_root_id'],
                'entity_ids': sorted(entry['entity_ids']),
                'item_id': entry['item_id'],
                'version_id': entry['version_id'],
                'run_ids': sorted(entry['run_ids']),
                'aboutness': sorted(entry['aboutness']),
                'surfaces': sorted(entry['surfaces']),
                'spans': _merge_spans(entry['_spans'], version=version),
            })
        return sorted(result, key=lambda row: (row['person_root_id'], row['item_id']))

    # -- Coverage Daily View -------------------------------------------------

    def _refresh_text_group_counts_spec(self, base: str | None, mode: str, survivor_pin: Any = None) -> dict[str, Any]:
        if survivor_pin is None:
            survivor_pin = self._bridge_pin_for_refresh(
                'survivor_items', 'text_group_counts', mode
            )
        return dict(
            dataset='text_group_counts', base=base, definition=DEFINITION, mode=mode,
            operation=self._operation(
                f'tgc-{mode}',
                content_digest([base, mode, version_ref(survivor_pin)]),
            ),
            transform={
                'kind': 'aggregate',
                'input': version_ref(survivor_pin),
                'grouping': {
                    'keys': ['text_group_id'],
                    'filter': {
                        'kind': 'and',
                        'exprs': [
                            {'kind': 'is_not_null', 'field': 'text_group_id'},
                            {'kind': 'gt', 'field': 'item_count', 'value': 1},
                        ],
                    },
                    'aggregates': [
                        {'name': 'item_count', 'function': {'kind': 'count_distinct', 'field': 'item_id'}},
                    ],
                },
            },
        )

    def _refresh_survivor_items_syndicated_spec(
        self, base: str | None, mode: str, survivor_pin: Any, counts_pin: Any,
    ) -> dict[str, Any]:
        return dict(
            dataset='survivor_items_syndicated', base=base, definition=DEFINITION, mode=mode,
            operation=self._operation(
                f'sis-{mode}',
                content_digest([base, mode, version_ref(survivor_pin), version_ref(counts_pin)]),
            ),
            transform={
                'kind': 'join',
                'left': version_ref(survivor_pin),
                'right': version_ref(counts_pin),
                'join': {
                    'keys': [{'left': 'text_group_id', 'right': 'text_group_id'}],
                    'kind': 'left', 'nulls': 'never',
                    'cardinality': 'many_to_one',
                    'fields': [
                        {'side': 'left', 'field': 'item_id', 'name': 'item_id'},
                        {'side': 'left', 'field': 'outlet_id', 'name': 'outlet_id'},
                        {'side': 'left', 'field': 'current_version_id', 'name': 'current_version_id'},
                        {'side': 'left', 'field': 'effective_pub_date', 'name': 'effective_pub_date'},
                        {'side': 'left', 'field': 'story_id', 'name': 'story_id'},
                        {'side': 'left', 'field': 'text_group_id', 'name': 'text_group_id'},
                        {'side': 'right', 'field': 'text_group_id', 'name': 'identical_text_group_id'},
                    ],
                },
            },
        )

    def _refresh_aggregate_spec(self, base: str | None, mode: str, survivor_pin: Any = None) -> dict[str, Any]:
        if survivor_pin is None:
            survivor_pin = self._bridge_pin_for_refresh(
                'survivor_items', 'coverage_daily', mode
            )
        return dict(
            dataset='coverage_daily', base=base, definition=DEFINITION, mode=mode,
            operation=self._operation(
                f'cov-{mode}',
                content_digest([base, mode, version_ref(survivor_pin)]),
            ),
            transform={
                'kind': 'aggregate',
                'input': version_ref(survivor_pin),
                'grouping': {
                    'keys': ['effective_pub_date'],
                    'aggregates': [
                        {'name': 'rows', 'function': {'kind': 'count_rows'}},
                        {'name': 'items', 'function': {'kind': 'count_distinct', 'field': 'item_id'}},
                        {'name': 'outlets', 'function': {'kind': 'count_distinct', 'field': 'outlet_id'}},
                        {'name': 'stories', 'function': {'kind': 'count_distinct', 'field': 'story_id'}},
                        {
                            'name': 'identical_text_group_ids',
                            'function': {'kind': 'collect_set', 'field': 'identical_text_group_id'},
                        },
                    ],
                },
            },
        )

    def refresh_coverage_daily_two_stage(
        self, records_or_release_read: Any, mode: str = 'full', selections: Any = None,
    ) -> list[dict[str, Any]]:
        """Refresh ``coverage_daily`` via 2-stage native cross-date syndication (ss-65bz)."""
        _, release_id = self._extract_release_meta(records_or_release_read, selections)
        survivor_pin = self._bridge_pin_for_refresh(
            'survivor_items', 'text_group_counts', mode
        )
        base_tgc = self._base_version('text_group_counts', mode)
        tgc_spec = self._refresh_text_group_counts_spec(base_tgc, mode, survivor_pin=survivor_pin)
        tgc_pin = self.client.refresh(tgc_spec)
        self.pins['text_group_counts'] = tgc_pin

        base_sis = self._base_version('survivor_items_syndicated', mode)
        sis_spec = self._refresh_survivor_items_syndicated_spec(
            base_sis, mode, survivor_pin, tgc_pin
        )
        sis_pin = self.client.refresh(sis_spec)
        self.pins['survivor_items_syndicated'] = sis_pin

        base_cov = self._base_version('coverage_daily', mode)
        cov_spec = self._refresh_aggregate_spec(base_cov, mode, survivor_pin=sis_pin)
        cov_pin = self.client.refresh(cov_spec)
        self.pins['coverage_daily'] = cov_pin

        self._flush_pending_bridge_compactions(('survivor_items',))
        self._record_view_mutation('text_group_counts')
        self._record_view_mutation('survivor_items_syndicated')
        self._record_view_mutation('coverage_daily')
        self._save_views_state()

        cov_cols = [
            'effective_pub_date', 'items', 'outlets', 'stories', 'identical_text_group_ids',
        ]
        aggregate = list(self.client.iter_records(cov_pin, columns=cov_cols))
        return self._assemble_coverage_daily(release_id, aggregate)

    def coverage_daily(
        self,
        records_or_release_read: Any,
        mode: str = 'full',
        selections: Any = None,
        *,
        two_stage_syndication: bool = True,
    ) -> list[dict[str, Any]]:
        """The ``coverage_daily`` view through native aggregate transforms."""
        if two_stage_syndication:
            return self.refresh_coverage_daily_two_stage(
                records_or_release_read, mode=mode, selections=selections
            )
        _, release_id = self._extract_release_meta(records_or_release_read, selections)
        base = self._base_version('coverage_daily', mode)
        survivor_pin = self._bridge_pin_for_refresh(
            'survivor_items', 'coverage_daily', mode
        )
        spec = self._refresh_aggregate_spec(base, mode, survivor_pin=survivor_pin)
        pin = self.client.refresh(spec)
        self.pins['coverage_daily'] = pin
        self._flush_pending_bridge_compactions(('survivor_items',))
        self._record_view_mutation('coverage_daily')
        self._save_views_state()
        cov_cols = [
            'effective_pub_date', 'items', 'outlets', 'stories', 'identical_text_group_ids',
        ]
        aggregate = list(self.client.iter_records(pin, columns=cov_cols))
        return self._assemble_coverage_daily(release_id, aggregate)

    def _assemble_coverage_daily(self, release_id: str | None, aggregate: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        ordered = sorted(
            aggregate,
            key=lambda row: (
                row.get('effective_pub_date') is None,
                row['effective_pub_date'].isoformat()
                if row.get('effective_pub_date') is not None else '',
            ),
        )
        for row in ordered:
            day = row.get('effective_pub_date')
            bucket_date = day.isoformat() if day is not None else None
            rows.append({
                'release_id': release_id,
                'date': bucket_date,
                'undated': bucket_date is None,
                'items': row['items'],
                'outlets': row['outlets'],
                'stories': row['stories'],
                'identical_text_group_ids': list(row.get('identical_text_group_ids') or ()),
            })
        return rows

    # -- Export Delegation ---------------------------------------------------

    @staticmethod
    def _ensure_release_read(records_or_release_read: Any) -> dict[str, Any]:
        return _export_ensure_release_read(records_or_release_read)

    def export_authorized(
        self,
        records_or_release_read: Any,
        destination_dir: str | Path | None = None,
        *,
        as_of: Any = None,
        now: Any = None,
        authorized: bool = False,
        channel: str = 'public',
        dataset_pins: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Apply C5 rights and capture-expiry rules, then run native Parquet exports."""
        return _export_authorized(
            self,
            records_or_release_read,
            destination_dir=destination_dir,
            as_of=as_of,
            now=now,
            authorized=authorized,
            channel=channel,
            dataset_pins=dataset_pins,
        )
