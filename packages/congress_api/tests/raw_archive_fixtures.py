"""Build small native fixture selections through maintained exact adoption.

Historical reconstruction supplies only local fixture values. Production adoption
uses independently investigated inputs, never this test-only reconstruction.
"""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.raw_adoption import adopt_archive
from congress_api.retention.raw_archive import CAPTURE_SCHEMA, prepare_capture_table, prepare_state_table
from historical_raw_archive import LegacyArchiveSeed


def adopt_fixture_archive(store, storage, *, operation, repair=False, directory=None):
    seed = LegacyArchiveSeed(store, 'historical-fixture', repair=repair)
    captures = seed.captures
    if seed.additions:
        captures = pa.concat_tables([captures, prepare_capture_table(seed.additions)])
    states = prepare_state_table(list(seed.state.values()), schema=storage.state_schema)
    with TemporaryDirectory(prefix='raw-fixture-inputs-') as folder:
        root = Path(folder)
        paths = {name: root / (name + '.parquet') for name in ('captures', 'state')}
        for name, table in (('captures', captures), ('state', states)):
            pq.write_table(table, paths[name], use_compliant_nested_type=False)
        return adopt_archive(storage, paths=paths,
            sha256s={name: sha256(path.read_bytes()).hexdigest() for name, path in paths.items()},
            operation=operation, directory=directory or root / 'readings', filename_version=seed.filename_version)
