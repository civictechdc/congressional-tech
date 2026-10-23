"""Transactional control store (sqlite): writer fence, durable intent journal,
staged checkpoints, the active cursor, and the release availability registry.

Operational state lives here; evidence lives in Iceberg (I2-I4). The journal
row is written before any commit so crash retries reuse the same record ids.

Every mutator runs inside ``_write_tx``: ``BEGIN IMMEDIATE`` serializes writers,
and an optional fencing epoch is checked *inside* the transaction so a writer
that lost its lease cannot slip a state change in after the pre-check.
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from news_lake.context import parse_instant
from news_lake.contract.records import KIND_ORDER, KIND_TABLES

CYCLE_STATES = ('intent', 'committed', 'validated', 'checkpoints_staged', 'released', 'done', 'abandoned')

_SCHEMA = '''
CREATE TABLE IF NOT EXISTS writer_fence (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    epoch INTEGER NOT NULL,
    writer_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS journal (
    cycle_id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staged_checkpoints (
    cycle_id TEXT NOT NULL,
    connector_key TEXT NOT NULL,
    checkpoint_ref TEXT NOT NULL,
    completed_until TEXT,
    staged_at TEXT NOT NULL,
    PRIMARY KEY (cycle_id, connector_key)
);
CREATE TABLE IF NOT EXISTS active_checkpoints (
    connector_key TEXT PRIMARY KEY,
    checkpoint_ref TEXT NOT NULL,
    completed_until TEXT,
    release_id TEXT NOT NULL,
    advanced_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS release_availability (
    release_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS release_sequence (
    release_id TEXT PRIMARY KEY,
    sequence INTEGER NOT NULL UNIQUE,
    published_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS validated_snapshots (
    table_name TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    validated_at TEXT NOT NULL,
    PRIMARY KEY (table_name, snapshot_id)
);
'''


class ControlError(RuntimeError):
    pass


class FencedError(ControlError):
    """A stale writer attempted to mutate the control store."""


def _now():
    return datetime.now(timezone.utc).isoformat()


class ControlStore:
    def __init__(self, path):
        self.path = str(path)
        # Manual transaction control so _write_tx can issue BEGIN IMMEDIATE
        # itself; the sqlite3 module must not start implicit transactions.
        self.connection = sqlite3.connect(self.path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(_SCHEMA)

    @contextmanager
    def _write_tx(self, epoch=None):
        """One serialized write transaction, fenced inside the BEGIN.

        A writer whose lease was stolen waits for BEGIN IMMEDIATE, then sees the
        new epoch and aborts before making any change. Never nest these.
        """
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            if epoch is not None:
                row = self.connection.execute(
                    'SELECT epoch FROM writer_fence WHERE id = 1'
                ).fetchone()
                current = row['epoch'] if row else 0
                if current != epoch:
                    raise FencedError(f'writer epoch {epoch} is fenced by epoch {current}')
            yield self.connection
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    # -- writer fence ----------------------------------------------------

    def claim(self, writer_id):
        """Take or renew the single-writer lease; bumps the fencing epoch."""
        with self._write_tx():
            self.connection.execute(
                'INSERT INTO writer_fence (id, epoch, writer_id, updated_at) VALUES (1, 1, ?, ?) '
                'ON CONFLICT(id) DO UPDATE SET epoch = epoch + 1, writer_id = excluded.writer_id, '
                'updated_at = excluded.updated_at',
                (writer_id, _now()),
            )
        return self.epoch()

    def epoch(self):
        row = self.connection.execute('SELECT epoch FROM writer_fence WHERE id = 1').fetchone()
        return row['epoch'] if row else 0

    def require_epoch(self, epoch):
        if self.epoch() != epoch:
            raise FencedError(f'writer epoch {epoch} is fenced by epoch {self.epoch()}')

    # -- durable intent journal -------------------------------------------

    def begin_cycle(self, cycle_id, payload, epoch=None):
        """Write the intent once; later calls return the stored payload."""
        with self._write_tx(epoch):
            cursor = self.connection.execute(
                'INSERT INTO journal (cycle_id, state, payload, updated_at) VALUES (?, ?, ?, ?) '
                'ON CONFLICT(cycle_id) DO NOTHING',
                (cycle_id, 'intent', json.dumps(payload, sort_keys=True), _now()),
            )
            inserted = bool(cursor.rowcount)
        if inserted:
            return None
        return json.loads(self.cycle(cycle_id)['payload'])

    def cycle(self, cycle_id):
        return self.connection.execute('SELECT * FROM journal WHERE cycle_id = ?', (cycle_id,)).fetchone()

    def cycle_state(self, cycle_id):
        row = self.cycle(cycle_id)
        return row['state'] if row else None

    def update_cycle_payload(self, cycle_id, payload, epoch=None):
        """Persist a built release record (and inputs) for crash retries."""
        with self._write_tx(epoch):
            self.connection.execute(
                'UPDATE journal SET payload = ?, updated_at = ? WHERE cycle_id = ?',
                (json.dumps(payload, sort_keys=True), _now(), cycle_id),
            )

    def open_cycles(self):
        """Journaled cycles needing recovery; abandoned cycles are terminal."""
        return self.connection.execute(
            "SELECT * FROM journal WHERE state != 'done' AND state != 'abandoned' ORDER BY updated_at"
        ).fetchall()

    def set_cycle_state(self, cycle_id, state, epoch=None):
        if state not in CYCLE_STATES:
            raise ControlError(f'unknown cycle state {state!r}')
        with self._write_tx(epoch):
            self.connection.execute(
                'UPDATE journal SET state = ?, updated_at = ? WHERE cycle_id = ?', (state, _now(), cycle_id)
            )

    # -- checkpoints: staged after record commits, activated on publication --

    def stage_checkpoint(self, cycle_id, checkpoint, epoch=None):
        with self._write_tx(epoch):
            self.connection.execute(
                'INSERT INTO staged_checkpoints (cycle_id, connector_key, checkpoint_ref, completed_until, staged_at) '
                'VALUES (?, ?, ?, ?, ?) ON CONFLICT(cycle_id, connector_key) DO UPDATE SET '
                'checkpoint_ref = excluded.checkpoint_ref, completed_until = excluded.completed_until, '
                'staged_at = excluded.staged_at',
                (cycle_id, checkpoint['connector_key'], checkpoint['checkpoint_ref'],
                 checkpoint.get('completed_until'), _now()),
            )

    def activate_checkpoints(self, cycle_id, epoch=None):
        """Advance the active cursor; only called after release publication.

        Monotonic: an older backfill (or an untimed page after a timed one)
        records its own checkpoint in the release but never moves the active
        cursor backwards.
        """
        with self._write_tx(epoch):
            staged = self.connection.execute(
                'SELECT * FROM staged_checkpoints WHERE cycle_id = ?', (cycle_id,)
            ).fetchall()
            existing = {
                row['connector_key']: row
                for row in self.connection.execute('SELECT * FROM active_checkpoints').fetchall()
            }
            for row in staged:
                prior = existing.get(row['connector_key'])
                incoming_until = row['completed_until']
                if prior is not None:
                    existing_until = prior['completed_until']
                    if existing_until is not None:
                        if incoming_until is None:
                            continue  # never replace a timed checkpoint with an untimed one
                        if parse_instant(incoming_until) <= parse_instant(existing_until):
                            continue  # equal or older: no regression, no ref rewrite
                self.connection.execute(
                    'INSERT INTO active_checkpoints (connector_key, checkpoint_ref, completed_until, release_id, advanced_at) '
                    'VALUES (?, ?, ?, ?, ?) ON CONFLICT(connector_key) DO UPDATE SET '
                    'checkpoint_ref = excluded.checkpoint_ref, completed_until = excluded.completed_until, '
                    'release_id = excluded.release_id, advanced_at = excluded.advanced_at',
                    (row['connector_key'], row['checkpoint_ref'], incoming_until, cycle_id, _now()),
                )

    def active_cursor(self):
        rows = self.connection.execute('SELECT * FROM active_checkpoints ORDER BY connector_key').fetchall()
        return {
            row['connector_key']: {
                'checkpoint_ref': row['checkpoint_ref'],
                'completed_until': row['completed_until'],
                'release_id': row['release_id'],
            }
            for row in rows
        }

    def discard_staged_checkpoints(self, cycle_id, epoch=None):
        """Drop one cycle's staged checkpoint rows (abandon_cycle cleanup)."""
        with self._write_tx(epoch):
            self.connection.execute('DELETE FROM staged_checkpoints WHERE cycle_id = ?', (cycle_id,))

    # -- release availability registry (I4) ---------------------------------

    def mark_available(self, release_id, epoch=None):
        """Publish a release and pin its publication sequence.

        The sequence is assigned once; re-marking an already-sequenced release
        (recovery) preserves its original position.
        """
        with self._write_tx(epoch):
            self.connection.execute(
                'INSERT INTO release_sequence (release_id, sequence, published_at) '
                'VALUES (?, (SELECT COALESCE(MAX(sequence), 0) + 1 FROM release_sequence), ?) '
                'ON CONFLICT(release_id) DO NOTHING',
                (release_id, _now()),
            )
            self.connection.execute(
                'INSERT INTO release_availability (release_id, status, updated_at) VALUES (?, ?, ?) '
                'ON CONFLICT(release_id) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at',
                (release_id, 'available', _now()),
            )

    def retire(self, release_id, epoch=None):
        with self._write_tx(epoch):
            self.connection.execute(
                'INSERT INTO release_availability (release_id, status, updated_at) VALUES (?, ?, ?) '
                'ON CONFLICT(release_id) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at',
                (release_id, 'retired', _now()),
            )

    def availability(self, release_id):
        row = self.connection.execute(
            'SELECT status FROM release_availability WHERE release_id = ?', (release_id,)
        ).fetchone()
        return row['status'] if row else None

    def latest_available_release(self):
        """The available release with the highest publication sequence."""
        row = self.connection.execute(
            'SELECT sequence.release_id FROM release_sequence AS sequence '
            'JOIN release_availability AS availability ON availability.release_id = sequence.release_id '
            "WHERE availability.status = 'available' "
            'ORDER BY sequence.sequence DESC LIMIT 1'
        ).fetchone()
        return row['release_id'] if row else None

    # -- validated snapshot cache (validation cost amortization) -------------

    def validated_snapshots(self):
        """(table_name, snapshot_id) pairs already validated by a release."""
        rows = self.connection.execute('SELECT table_name, snapshot_id FROM validated_snapshots').fetchall()
        return {(row['table_name'], row['snapshot_id']) for row in rows}

    def mark_snapshots_validated(self, pairs, epoch=None):
        with self._write_tx(epoch):
            for table_name, snapshot_id in pairs:
                self.connection.execute(
                    'INSERT INTO validated_snapshots (table_name, snapshot_id, validated_at) VALUES (?, ?, ?) '
                    'ON CONFLICT(table_name, snapshot_id) DO NOTHING',
                    (table_name, str(snapshot_id), _now()),
                )


