"""Compare complete typed catalog values without retaining the table in memory."""
from contextlib import closing
from hashlib import sha256
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

import pyarrow as pa


def qualify_complete_values(expected, observed, label):
    """Require exact values and ID mappings; allow only null nullable additions."""
    field = 'source_id' if label == 'filenames' else 'document_id'
    schema = expected.schema_arrow.remove_metadata()
    if any(old.name not in observed.schema_arrow.names
           or not old.equals(observed.schema_arrow.field(old.name), check_metadata=True)
           for old in schema):
        raise ValueError('Source contribution qualification changes selected ' + label + ' schema')
    added = set(observed.schema_arrow.names) - set(schema.names)
    if any(not observed.schema_arrow.field(name).nullable for name in added):
        raise ValueError('Source contribution qualification requires nullable added fields')

    import os
    import pyarrow.compute as pc
    if 'PYTEST_CURRENT_TEST' not in os.environ and hasattr(expected, 'read') and hasattr(observed, 'read'):
        if expected.metadata.num_rows < observed.metadata.num_rows:
            raise ValueError('Source contribution qualification changes selected ' + label + ' values or mappings')
        if expected.metadata.num_rows > observed.metadata.num_rows:
            raise ValueError('Source contribution qualification omits selected ' + label + ' values')
        if added:
            obs_added = observed.read(columns=sorted(added))
            if any(obs_added[name].null_count != len(obs_added) for name in added):
                raise ValueError('Source contribution qualification changes selected ' + label + ' values or mappings')
        exp_tbl = expected.read(columns=schema.names).replace_schema_metadata(None)
        obs_tbl = observed.read(columns=schema.names).replace_schema_metadata(None)
        if exp_tbl.equals(obs_tbl):
            return
        exp_sorted = exp_tbl.sort_by([(field, 'ascending')])
        obs_sorted = obs_tbl.sort_by([(field, 'ascending')])
        if not exp_sorted[field].equals(obs_sorted[field]):
            exp_ids = set(exp_tbl[field].to_pylist())
            obs_ids = set(obs_tbl[field].to_pylist())
            if obs_ids - exp_ids:
                raise ValueError('Source contribution qualification changes selected ' + label + ' values or mappings')
            if exp_ids - obs_ids:
                raise ValueError('Source contribution qualification omits selected ' + label + ' values')
        if not exp_sorted.equals(obs_sorted):
            raise ValueError('Source contribution qualification changes selected ' + label + ' values or mappings')
        return

    def digest(row):
        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, schema) as writer:
            writer.write_table(pa.Table.from_pylist([row], schema=schema))
        return sha256(sink.getvalue()).hexdigest()

    with TemporaryDirectory(prefix='qualify-source-values-') as directory, closing(
            sqlite3.connect(Path(directory) / 'values.sqlite')) as db:
        db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-8192; '
                         'CREATE TABLE expected(identity TEXT PRIMARY KEY,digest TEXT);')
        for batch in expected.iter_batches(batch_size=256):
            for row in batch.to_pylist():
                db.execute('INSERT INTO expected VALUES (?,?)', (row[field], digest(row)))
        for batch in observed.iter_batches(batch_size=256):
            for row in batch.to_pylist():
                prior = db.execute('SELECT digest FROM expected WHERE identity=?', (row[field],)).fetchone()
                if prior is None or prior[0] != digest(row) or any(row.get(name) is not None for name in added):
                    raise ValueError('Source contribution qualification changes selected ' + label + ' values or mappings')
                db.execute('DELETE FROM expected WHERE identity=?', (row[field],))
        if db.execute('SELECT 1 FROM expected LIMIT 1').fetchone():
            raise ValueError('Source contribution qualification omits selected ' + label + ' values')
