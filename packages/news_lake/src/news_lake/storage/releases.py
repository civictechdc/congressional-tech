"""Release publication (I3), pinned reads, and the availability registry (I4).

Publish order is exact: commit candidate tables, validate C7 against those
exact snapshots, stage checkpoints, append the release, then mark it available
and advance the active cursor. The built release record is journaled as soon as
it exists, so a retry replays the same pinned snapshots instead of rebuilding
drifting ones. A failure before the release append leaves the prior release
usable and the cursor untouched; a failure between append and mark_available
leaves the new release unreadable until recovery finishes (I4).

Validation is amortized: snapshots already validated by a successful release
skip per-record shape/hash work, while every cross-record C7 check and the new
release record always run.
"""
from pyiceberg.expressions import EqualTo, In

from news_lake.adapters.urls import redact_userinfo
from news_lake.contract.records import (
    CONTENT_TABLES,
    CONTRACT_VERSION,
    SCHEMA,
    TABLE_KINDS,
    TABLE_MUTATIONS,
)
from news_lake.contract.semantics import check_corpus
from news_lake.storage import mapping

# Validated snapshots of heavy append-only tables project only the id and
# foreign-key columns needed for cross-record C7 checks; article bodies, span
# arrays, and classification values stay on disk unless a newly added mention
# references a validated version.
_PROJECTED_VALIDATED_FIELDS = {
    'news.discoveries': ('id', 'capture_id', 'item_id'),
    'news.versions': ('id', 'item_id', 'capture_id', 'run_id', 'access'),
    'news.mentions': ('id', 'version_id', 'run_id', 'entity_id'),
    'news.classifications': ('id', 'version_id', 'run_id', 'target_entity_id'),
}


class ReleaseError(RuntimeError):
    def __init__(self, rule, detail, release_id=None):
        self.rule = rule
        self.release_id = release_id
        self.detail = detail
        location = f'release {release_id}: ' if release_id is not None else ''
        super().__init__(f'{location}{rule}: {detail}')


def _redact_checkpoints(checkpoints):
    sanitized = []
    for checkpoint in checkpoints:
        entry = dict(checkpoint)
        if isinstance(entry.get('checkpoint_ref'), str):
            entry['checkpoint_ref'] = redact_userinfo(entry['checkpoint_ref'])
        sanitized.append(entry)
    return sanitized


def build_release(lake, release_id, recorded_at, selections, checkpoints):
    """Name the twelve non-release tables with UUIDs; snapshot_id only when the
    table genuinely has content (absent means explicitly empty, never latest)."""
    snapshots = []
    for table_name in CONTENT_TABLES:
        table = lake.table(table_name)
        entry = {'table': table_name, 'table_uuid': lake.table_uuid(table_name, table=table)}
        snapshot = table.current_snapshot()
        if snapshot is not None:
            entry['snapshot_id'] = str(snapshot.snapshot_id)
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


def _allowed_extra_by_kind(lake, tables_by_name=None):
    """Per-kind extras introduced by an evolved table schema (all 13 tables).

    The contract's shape check may accept extra top-level fields only when the
    owning table explicitly defines them; storage passes the table's schema,
    never a hand-written allowlist.
    """
    loaded = tables_by_name or {}
    extras = {}
    for table_name, kind in TABLE_KINDS.items():
        extra = lake.allowed_extra(table_name, table=loaded.get(table_name))
        if extra:
            extras[kind] = extra
    return extras


def _pinned_records(lake, release, validated=()):
    """Read the candidate corpus from the exact snapshots the release pins.

    Returns the records, the ids that came from an already validated snapshot
    (or from a prior validated snapshot of an append-only table), and the
    loaded table handles so callers do not reload catalog metadata. Validated
    snapshots of heavy tables project only id/FK columns; empty tables
    (no snapshot_id) contribute nothing and are never cached.
    """
    validated_by_table = {}
    for table_name, snap_id in validated:
        validated_by_table.setdefault(table_name, set()).add(str(snap_id))

    records = []
    validated_ids = set()
    loaded_tables = {}
    projected_versions = {}
    version_snapshot_id = None

    for entry in release['snapshots']:
        if 'snapshot_id' not in entry:
            continue
        table_name = entry['table']
        snap_str = str(entry['snapshot_id'])
        snap_int = int(snap_str)
        kind = TABLE_KINDS[table_name]
        table = lake.table(table_name)
        loaded_tables[table_name] = table

        if (table_name, snap_str) in validated:
            projected = _PROJECTED_VALIDATED_FIELDS.get(table_name)
            scan = (
                table.scan(snapshot_id=snap_int, selected_fields=projected)
                if projected is not None
                else table.scan(snapshot_id=snap_int)
            )
            rows = mapping.from_arrow_table(kind, scan.to_arrow())
            validated_ids.update(record['id'] for record in rows)
            if table_name == 'news.versions':
                version_snapshot_id = snap_int
                for record in rows:
                    projected_versions[record['id']] = record
        else:
            rows = mapping.from_arrow_table(
                kind, table.scan(snapshot_id=snap_int).to_arrow()
            )
            prior_snaps = validated_by_table.get(table_name)
            if prior_snaps and TABLE_MUTATIONS[table_name] == 'append':
                known = {s.snapshot_id for s in table.metadata.snapshots}
                for prior_str in prior_snaps:
                    prior_int = int(prior_str)
                    if prior_int in known:
                        id_col = table.scan(
                            snapshot_id=prior_int, selected_fields=('id',)
                        ).to_arrow()['id'].to_pylist()
                        validated_ids.update(id_col)
        records.extend(rows)

    if projected_versions:
        needed_version_ids = {
            record['version_id']
            for record in records
            if record['kind'] == 'mention'
            and record['id'] not in validated_ids
            and record.get('version_id') in projected_versions
        }
        if needed_version_ids:
            v_table = loaded_tables['news.versions']
            full_rows = mapping.from_arrow_table(
                'version',
                v_table.scan(
                    row_filter=In('id', needed_version_ids),
                    selected_fields=('id', 'title', 'text'),
                    snapshot_id=version_snapshot_id,
                ).to_arrow(),
            )
            for row in full_rows:
                target = projected_versions[row['id']]
                if 'title' in row:
                    target['title'] = row['title']
                if 'text' in row:
                    target['text'] = row['text']

    return records, validated_ids, loaded_tables


def publish_release(coordinator, records, *, release_id, recorded_at, selections=(), checkpoints=()):
    """Run one publication cycle; safe to retry after a crash at any point."""
    control = coordinator.control
    control.require_epoch(coordinator.epoch)
    faults = coordinator.faults
    payload = {
        'records': records,
        'recorded_at': recorded_at,
        'selections': list(selections),
        'checkpoints': _redact_checkpoints(checkpoints),
    }
    faults.before('journal_write')
    stored = control.begin_cycle(release_id, payload, epoch=coordinator.epoch)
    if stored is not None:
        # Retry after an interruption: reuse the journaled intent (including a
        # release record persisted after the build) so ids and snapshots do not
        # drift.
        payload = stored
    faults.after('journal_write')
    state = control.cycle_state(release_id)
    if state == 'done':
        return find_release(coordinator.lake, release_id)
    if state == 'abandoned':
        raise ReleaseError(
            'cycle_abandoned',
            f'cycle {release_id} was abandoned after failed validation; publish under a new release id',
            release_id=release_id,
        )

    if state == 'intent':
        coordinator.commit(payload['records'])  # fires table_commit:<table> points
        control.set_cycle_state(release_id, 'committed', epoch=coordinator.epoch)
        state = 'committed'

    release = payload.get('release')
    if release is None:
        release = build_release(coordinator.lake, release_id, payload['recorded_at'],
                                payload['selections'], payload['checkpoints'])
        payload['release'] = release
        control.update_cycle_payload(release_id, payload, epoch=coordinator.epoch)

    validated = control.validated_snapshots()
    pinned_records, validated_ids, loaded_tables = _pinned_records(
        coordinator.lake, release, validated
    )
    defined_release = set(SCHEMA['$defs']['release'].get('properties', {}))
    has_extra = any(
        set(rec) - set(SCHEMA['$defs'][rec['kind']].get('properties', {}))
        for rec in pinned_records
    ) or bool(set(release) - defined_release)
    allow_extra_by_kind = (
        _allowed_extra_by_kind(coordinator.lake, loaded_tables) if has_extra else None
    )
    check_corpus(
        pinned_records + [release],
        validated_ids=validated_ids,
        allow_extra_by_kind=allow_extra_by_kind,
    )  # I3: publish last; cross-record checks always run
    control.mark_snapshots_validated(
        [(entry['table'], entry['snapshot_id'])
         for entry in release['snapshots'] if 'snapshot_id' in entry],
        epoch=coordinator.epoch,
    )

    if state == 'committed':
        control.set_cycle_state(release_id, 'validated', epoch=coordinator.epoch)
        state = 'validated'
    if state == 'validated':
        faults.before('checkpoint_stage')
        for checkpoint in payload['checkpoints']:
            key = checkpoint['connector_key']
            faults.before(f'checkpoint_stage:{key}')
            control.stage_checkpoint(release_id, checkpoint, epoch=coordinator.epoch)
            faults.after(f'checkpoint_stage:{key}')
        faults.after('checkpoint_stage')
        control.set_cycle_state(release_id, 'checkpoints_staged', epoch=coordinator.epoch)
        state = 'checkpoints_staged'
    if state == 'checkpoints_staged':
        faults.before('release_append')
        coordinator.append_release(release)
        faults.after('release_append')
        control.set_cycle_state(release_id, 'released', epoch=coordinator.epoch)
        state = 'released'
    if state == 'released':
        # Availability is the reader gate, so mark it before moving the cursor:
        # a crash between the two leaves a readable release with an older (safe)
        # cursor, and recovery re-runs both idempotently.
        faults.before('cursor_advance')
        control.mark_available(release_id, epoch=coordinator.epoch)
        control.activate_checkpoints(release_id, epoch=coordinator.epoch)
        faults.after('cursor_advance')
        control.set_cycle_state(release_id, 'done', epoch=coordinator.epoch)
    return release


def find_release(lake, release_id):
    """Find one release with an Iceberg row filter (never a full-lake scan)."""
    table = lake.table('news.releases')
    snapshot = table.current_snapshot()
    if snapshot is None:
        return None
    rows = mapping.from_arrow_table(
        'release',
        table.scan(row_filter=EqualTo('id', release_id), snapshot_id=snapshot.snapshot_id).to_arrow(),
    )
    return rows[0] if rows else None


def read_release(lake, control, release_id, tables=None):
    """Resolve a release's pinned snapshots; reject unknown, unreadable, or
    altered state.

    ``tables`` optionally restricts the read to a subset of the release's
    tables (default: all twelve). Requested names must be pinned by the
    release.
    """
    record = find_release(lake, release_id)
    if record is None:
        raise ReleaseError('unknown_release', 'no release record with this id', release_id=release_id)
    status = control.availability(release_id)
    if status is None:
        raise ReleaseError(
            'unreleased_release',
            'release record exists but publication never marked it available',
            release_id=release_id,
        )
    if status == 'retired':
        raise ReleaseError('retired_release', 'release is retired in the availability registry', release_id=release_id)
    if status != 'available':
        raise ReleaseError('unreleased_release', f'release status is {status!r}', release_id=release_id)
    if record.get('contract_version') != CONTRACT_VERSION:
        raise ReleaseError(
            'contract_version_mismatch',
            f'release contract_version {record.get("contract_version")!r} does not match reader {CONTRACT_VERSION!r}',
            release_id=release_id,
        )

    entries = record['snapshots']
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

    result = {}
    for entry in entries:
        table_name = entry['table']
        table = lake.table(table_name)
        if str(table.metadata.table_uuid) != entry['table_uuid']:
            raise ReleaseError('table_uuid_mismatch', f'{table_name} UUID differs from the release', release_id=release_id)
        if 'snapshot_id' not in entry:
            result[table_name] = []  # explicitly empty, never latest
            continue
        snapshot_id = int(entry['snapshot_id'])
        known_snapshots = {snapshot.snapshot_id for snapshot in table.metadata.snapshots}
        if snapshot_id not in known_snapshots:
            raise ReleaseError('missing_snapshot', f'{table_name} snapshot {snapshot_id} is gone', release_id=release_id)
        kind = TABLE_KINDS[table_name]
        result[table_name] = mapping.from_arrow_table(kind, table.scan(snapshot_id=snapshot_id).to_arrow())
    return {'release': record, 'tables': result}


def retire_release(control, release_id, epoch=None):
    """Flip the control-plane availability registry; consumers must reject."""
    control.retire(release_id, epoch=epoch)
