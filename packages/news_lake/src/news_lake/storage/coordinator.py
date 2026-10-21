"""Fenced single-writer commit coordinator over the Iceberg tables (I2).

Table routing and mutation mode come from the contract module; storage never
re-derives record rules. Append tables treat a replayed identical row as a
no-op and an id reuse with different values as a hard failure; upsert tables
merge replacements by logical key (id) so earlier evidence survives (C1).

Upserts replace one row in a single Iceberg transaction (delete + append), so
a crash cannot expose the "row absent" state to recovery. ``abandon_cycle`` is
the explicit policy-deletion path for failed publication cycles (I2/I4);
commit() itself never removes records on its own.
"""
import json

from pyiceberg.expressions import In

from news_lake.contract.records import (
    CONTENT_TABLES,
    KIND_ORDER,
    KIND_TABLES,
    SCHEMA,
    TABLE_KINDS,
    TABLE_MUTATIONS,
    validate_shape,
)
from news_lake.context import canonicalize_record_instants, parse_instant
from news_lake.storage import mapping


class CommitError(RuntimeError):
    def __init__(self, rule, detail, record_id=None):
        self.rule = rule
        self.record_id = record_id
        self.detail = detail
        location = f'record {record_id}: ' if record_id is not None else ''
        super().__init__(f'{location}{rule}: {detail}')


def _freeze(item):
    """Hashable marker for union dedup: dicts and lists compare by value."""
    if isinstance(item, dict):
        return tuple(sorted((key, _freeze(value)) for key, value in item.items()))
    if isinstance(item, list):
        return tuple(_freeze(child) for child in item)
    return item


def _union(prior_items, incoming_items):
    """Preserve prior order, append new evidence, dedup by value."""
    result = []
    seen = set()
    for item in prior_items + incoming_items:
        marker = _freeze(item)
        if marker not in seen:
            seen.add(marker)
            result.append(item)
    return result


def _merge_upsert(prior, record):
    """Merge an upsert replacement so earlier evidence survives (C1).

    Upsert tables (outlets/items/entities) replace rows by id; adapters rebuild
    records from the latest poll, so a plain replace would silently drop
    evidence an earlier poll recorded (redirect aliases, a second feed URL,
    added identifiers). List-valued evidence fields always union with dedup.
    ``recorded_at`` keeps the later instant; scalar fields only take the
    incoming value when the incoming poll is at least as recent as the prior
    row, so a late-arriving older poll cannot regress name, content type,
    outlet ownership, or the current version. Fields the older incoming poll
    carries that prior lacks are still added, and first_seen_at keeps the
    chronologically earlier instant. Append tables never reach this path.
    """
    incoming_at = parse_instant(record['recorded_at'])
    prior_at = parse_instant(prior['recorded_at'])
    incoming_wins = incoming_at >= prior_at
    merged = dict(record)
    for key, prior_value in prior.items():
        if key in ('kind', 'id', 'recorded_at'):
            continue
        incoming = merged.get(key)
        if isinstance(prior_value, list):
            merged[key] = _union(prior_value, incoming if isinstance(incoming, list) else [])
            continue
        if not incoming_wins or incoming is None:
            merged[key] = prior_value
    merged['recorded_at'] = record['recorded_at'] if incoming_wins else prior['recorded_at']
    if 'first_seen_at' in merged and 'first_seen_at' in prior:
        merged['first_seen_at'] = min(
            prior['first_seen_at'], merged['first_seen_at'], key=parse_instant
        )
    return merged


class CrashInjection(Exception):
    """Test-only simulated crash at a named commit point."""

    def __init__(self, point):
        self.point = point
        super().__init__(f'simulated crash at {point}')


class Faults:
    """Fault-injection hook: crash_before/crash_after named points.

    Points: journal_write, table_commit:<table> (plus bare table_commit for
    any table), upsert_replace:<table> (delete+append transaction for upsert
    replacements), checkpoint_stage:<connector_key> (plus bare checkpoint_stage),
    release_append, cursor_advance.
    """

    def __init__(self, crash_before=(), crash_after=()):
        self.crash_before = set(crash_before)
        self.crash_after = set(crash_after)
        self.fired = []

    def _hit(self, point, watched):
        return any(point == name or point.startswith(name + ':') for name in watched)

    def before(self, point):
        self.fired.append(('before', point))
        if self._hit(point, self.crash_before):
            raise CrashInjection(point)

    def after(self, point):
        self.fired.append(('after', point))
        if self._hit(point, self.crash_after):
            raise CrashInjection(point)


class Coordinator:
    def __init__(self, lake, control, writer_id='news-lake-writer', faults=None):
        self.lake = lake
        self.control = control
        self.faults = faults if faults is not None else Faults()
        self.writer_id = writer_id
        self.epoch = control.claim(writer_id)

    # -- batch preparation -------------------------------------------------

    def _prepare(self, records):
        batch = {}
        allowed_by_kind = {}
        for record in records:
            kind = record.get('kind') if isinstance(record, dict) else None
            if kind in KIND_TABLES and kind != 'release':
                defined = set(SCHEMA['$defs'][kind].get('properties', {}))
                if set(record) - defined:
                    if kind not in allowed_by_kind:
                        allowed_by_kind[kind] = self._allowed_extra(KIND_TABLES[kind])
                    validate_shape(record, allowed_extra=allowed_by_kind[kind])
                else:
                    validate_shape(record)
            else:
                validate_shape(record)
            record = canonicalize_record_instants(record)
            kind = record['kind']
            if kind == 'release':
                raise CommitError(
                    'release_in_batch', 'release records are appended by publish_release, not commit',
                    record_id=record['id'],
                )
            slot = batch.setdefault(kind, {})
            prior = slot.get(record['id'])
            if prior is not None and prior != record:
                raise CommitError(
                    'batch_id_collision', 'id appears twice in the batch with different values', record_id=record['id']
                )
            slot[record['id']] = record
        return batch

    def _existing(self, table_name, ids=None, table=None):
        if ids is not None:
            id_set = set(ids)
            if not id_set:
                return {}
            table = table if table is not None else self.lake.table(table_name)
            snapshot = table.current_snapshot()
            if snapshot is None:
                return {}
            rows = mapping.from_arrow_table(
                TABLE_KINDS[table_name],
                table.scan(row_filter=In('id', id_set), snapshot_id=snapshot.snapshot_id).to_arrow(),
            )
            return {record['id']: record for record in rows}
        return {record['id']: record for record in self.lake.read_all(table_name)}

    def _allowed_extra(self, table_name, table=None):
        """Top-level columns the table schema adds beyond the JSON record.

        Schema evolution may add optional columns to an Iceberg table; those
        are legal merged-record fields even though the record contract does not
        know them. Storage never invents its own field rules.
        """
        return self.lake.allowed_extra(table_name, table=table)

    # -- commit -------------------------------------------------------------

    def commit(self, records):
        """Commit a batch of non-release records; idempotent under replay."""
        self.control.require_epoch(self.epoch)
        batch = self._prepare(records)
        for kind in KIND_ORDER:
            if kind == 'release':
                continue
            incoming = batch.get(kind)
            if incoming:
                self._commit_table(kind, list(incoming.values()))

    def _commit_table(self, kind, records):
        table_name = KIND_TABLES[kind]
        self.control.require_epoch(self.epoch)
        table = self.lake.table(table_name)
        existing = self._existing(table_name, ids=(record['id'] for record in records), table=table)
        allowed_extra = self._allowed_extra(table_name, table=table)
        fresh, replaces = [], []
        for record in records:
            prior = existing.get(record['id'])
            if prior is not None and prior == record:
                continue  # replayed identical record: no-op in both modes
            if prior is not None and TABLE_MUTATIONS[table_name] == 'append':
                raise CommitError(
                    'append_collision',
                    f'id {record["id"]} already exists with different values on append-only {table_name}',
                    record_id=record['id'],
                )
            if prior is not None:
                record = _merge_upsert(prior, record)
                validate_shape(record, allowed_extra=allowed_extra)
                if record == prior:
                    continue
            (replaces if prior is not None else fresh).append(record)
        if not fresh and not replaces:
            return
        arrow_schema = self.lake.arrow_schema(table_name, table=table)
        self.faults.before(f'table_commit:{table_name}')
        if replaces:
            # Upsert: delete+append in ONE Iceberg transaction, so recovery never
            # observes the row-absent intermediate state. The fresh rows ride in
            # the same commit when a batch mixes inserts and replacements.
            self.control.require_epoch(self.epoch)
            self.faults.before(f'upsert_replace:{table_name}')
            with self.lake.fenced_commit(self.control, self.epoch):
                with table.transaction() as tx:
                    tx.delete(In('id', {record['id'] for record in replaces}))
                    tx.append(mapping.to_arrow_table(
                        kind, fresh + replaces, arrow_schema
                    ))
            self.faults.after(f'upsert_replace:{table_name}')
        else:
            self.control.require_epoch(self.epoch)
            with self.lake.fenced_commit(self.control, self.epoch):
                table.append(mapping.to_arrow_table(
                    kind, fresh, arrow_schema
                ))
        self.faults.after(f'table_commit:{table_name}')

    def _latest_available_release(self):
        from news_lake.storage.releases import find_release

        release_id = self.control.latest_available_release()
        return find_release(self.lake, release_id) if release_id is not None else None

    def abandon_cycle(self, cycle_id):
        """Policy rollback of one failed publication cycle (the remediation
        seam for I3's commit-first order).

        When a candidate cycle's records fail C7 validation, the bad rows
        remain in the tables and would block every future release, which
        re-validates the full pinned corpus. Abandoning restores each content
        table to the exact row set pinned by the latest available release (or
        empty if no release has been published yet), removes newly added rows
        (including pre-committed PageDrain rows) and restores pre-cycle rows
        for any upsert IDs the failed cycle touched. Tables whose current
        snapshot already equals the baseline are skipped. Staged checkpoints
        for the cycle are discarded, and a cycle whose release record was
        already appended is left for recover() rather than silently orphaned.
        Idempotent: re-running is a no-op. A released or finished cycle cannot
        be abandoned.
        """
        if hasattr(self.lake, 'abandon_cycle'):
            return self.lake.abandon_cycle(
                self.control,
                cycle_id,
                epoch=self.epoch,
                faults=self.faults,
            )
        self.control.require_epoch(self.epoch)
        row = self.control.cycle(cycle_id)
        if row is None:
            raise CommitError('unknown_cycle', f'no journal entry for cycle {cycle_id}')
        if row['state'] == 'abandoned':
            return  # idempotent no-op
        if row['state'] in ('released', 'done'):
            raise CommitError('cycle_released', f'cycle {cycle_id} is {row["state"]} and cannot be abandoned')
        from news_lake.storage.releases import find_release

        if find_release(self.lake, cycle_id) is not None:
            raise CommitError(
                'cycle_release_appended',
                f'cycle {cycle_id} already appended its release record; run recover() instead',
            )

        baseline_release = self._latest_available_release()
        if baseline_release is None:
            if self.lake.table('news.releases').current_snapshot() is not None:
                raise CommitError(
                    'no_available_baseline',
                    'release records exist but none is available; refusing to wipe the warehouse to empty',
                )
            pinned_by_table = {}
        else:
            pinned_by_table = {
                entry['table']: entry.get('snapshot_id')
                for entry in baseline_release['snapshots']
            }

        self.control.discard_staged_checkpoints(cycle_id, epoch=self.epoch)

        for table_name in CONTENT_TABLES:
            self.control.require_epoch(self.epoch)
            kind = TABLE_KINDS[table_name]
            table = self.lake.table(table_name)
            current_snapshot = table.current_snapshot()
            current_snapshot_id = current_snapshot.snapshot_id if current_snapshot is not None else None
            pinned = pinned_by_table.get(table_name)
            pinned_snapshot_id = int(pinned) if pinned is not None else None
            if current_snapshot_id == pinned_snapshot_id:
                continue  # untouched by the failed cycle
            if pinned_snapshot_id is not None:
                baseline_rows = mapping.from_arrow_table(
                    kind, table.scan(snapshot_id=pinned_snapshot_id).to_arrow()
                )
                baseline = {r['id']: r for r in baseline_rows}
            else:
                baseline = {}
            current = self._existing(table_name)
            to_delete = {rid for rid, rec in current.items() if baseline.get(rid) != rec}
            to_restore = [rec for rid, rec in baseline.items() if current.get(rid) != rec]
            if not to_delete and not to_restore:
                continue
            self.control.require_epoch(self.epoch)
            with self.lake.fenced_commit(self.control, self.epoch):
                with table.transaction() as tx:
                    if to_delete:
                        tx.delete(In('id', to_delete))
                    if to_restore:
                        tx.append(mapping.to_arrow_table(
                            kind, to_restore, self.lake.arrow_schema(table_name, table=table)
                        ))
        self.control.set_cycle_state(cycle_id, 'abandoned', epoch=self.epoch)

    def append_release(self, record):
        """Append one release record with append-mode dedup (I3 last step)."""
        self.control.require_epoch(self.epoch)
        table_name = 'news.releases'
        table = self.lake.table(table_name)
        allowed_extra = self._allowed_extra(table_name, table=table)
        validate_shape(record, allowed_extra=allowed_extra)
        record = canonicalize_record_instants(record)
        existing = self._existing(table_name, ids=(record['id'],), table=table)
        prior = existing.get(record['id'])
        if prior == record:
            return
        if prior is not None:
            raise CommitError('append_collision', f'release {record["id"]} exists with different values', record_id=record['id'])
        self.control.require_epoch(self.epoch)
        with self.lake.fenced_commit(self.control, self.epoch):
            table.append(mapping.to_arrow_table('release', [record], self.lake.arrow_schema(table_name, table=table)))

    # -- recovery -------------------------------------------------------------

    def recover(self, publisher=None):
        """Converge every journaled-but-incomplete cycle; idempotent."""
        if publisher is None:
            from news_lake.storage.releases import publish_release as publisher
        completed = []
        for row in self.control.open_cycles():
            payload = json.loads(row['payload'])
            publisher(
                self,
                payload['records'],
                release_id=row['cycle_id'],
                recorded_at=payload['recorded_at'],
                selections=payload['selections'],
                checkpoints=payload['checkpoints'],
            )
            completed.append(row['cycle_id'])
        return completed
