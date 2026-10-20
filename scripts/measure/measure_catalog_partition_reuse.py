#!/usr/bin/env python3
"""Measure the current publication boundary with one correction and an unchanged table.

This offline diagnostic writes only a new caller-selected directory. --require-reuse
is the ct-v5kb red acceptance case; ordinary diagnostic mode preserves its result
without making an unsupported runtime migration.
"""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

from congress_api.retention.catalog_cache import LocalStore
from congress_api.retention import catalog_publication as publication


class MeasuredStore(LocalStore):
    def __init__(self, root):
        super().__init__(root)
        self.operations = []

    def read(self, key):
        result = super().read(key)
        self.operations.append(dict(action='metadata_read', key=key, bytes=len(result or b'')))
        return result

    def read_derived_file(self, key, path, *, expected=None):
        result = super().read_derived_file(key, path, expected=expected)
        self.operations.append(dict(action='payload_read', key=key, bytes=result['bytes'] if result else 0))
        return result

    def put_derived_file(self, key, path, *, expected):
        result = super().put_derived_file(key, path, expected=expected)
        self.operations.append(dict(action='payload_write', key=key, bytes=result['bytes']))
        return result

    def put(self, key, data, **options):
        result = super().put(key, data, **options)
        self.operations.append(dict(action='metadata_write', key=key, bytes=len(data)))
        return result


def fixture(root, count, *, corrected=False):
    root.mkdir(parents=True)
    schema = pa.schema([
        ('source_id', pa.string()), ('document_id', pa.string()), ('review', pa.string()),
        ('aliases', pa.list_(pa.string())),
        ('provenance', pa.list_(pa.struct([('url', pa.string()), ('values', pa.list_(pa.string()))]))),
    ], metadata={b'catalog_id': b'fixed-fixture-identity'})
    rows = [dict(source_id=f'source-{i}', document_id=f'document-{i}',
                 review=None if i % 2 else '', aliases=None if i % 2 else [],
                 provenance=[dict(url='https://example.gov/caf\u00e9', values=['same', 'same', '']),
                             dict(url=None, values=None)]) for i in range(count)]
    filenames = deepcopy(rows)
    if corrected:
        filenames[0]['review'] = 'corrected'
    paths = root / 'document-filenames.parquet', root / 'documents.parquet'
    for path, records in zip(paths, (filenames, rows), strict=True):
        pq.write_table(pa.Table.from_pylist(records, schema=schema), path, row_group_size=2)
    return paths


def measure(output, *, rows=8):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    store = MeasuredStore(output / 'archive')
    first, changed = fixture(output / 'first', rows), fixture(output / 'changed', rows, corrected=True)
    assert first[1].read_bytes() == changed[1].read_bytes(), 'Unchanged document fixture differs'
    with publication.read_catalog(store) as previous:
        publication.publish_catalog(store, *first, previous=previous)
    store.operations.clear()
    with publication.read_catalog(store) as previous:
        before_manifest = deepcopy(previous.manifest)
        hashes = []
        original_identity = publication.file_identity
        def track(path):
            result = original_identity(path)
            hashes.append(dict(path=str(path), bytes=result['bytes']))
            return result
        with patch.object(publication, 'file_identity', track):
            publication.publish_catalog(store, *changed, previous=previous)
    operations = list(store.operations)
    with publication.read_catalog(store) as selected:
        after_manifest = deepcopy(selected.manifest)
        parity = all(pq.read_table(getattr(selected, label + '_path')).equals(pq.read_table(path),
                     check_metadata=True) for label, path in zip(('filenames', 'documents'), changed, strict=True))
    old_preserved = all(sha256((store.root / item['key']).read_bytes()).hexdigest() == item['sha256']
                        for item in before_manifest['files'].values())
    reused = [label for label in ('filenames', 'documents')
              if before_manifest['files'][label]['key'] == after_manifest['files'][label]['key']]
    failures = []
    if not parity:
        failures.append('Selected catalog changed the expected nested schema or ordered values')
    if not old_preserved:
        failures.append('Publication changed or removed a previously selected immutable payload')
    if 'documents' not in reused:
        failures.append('Unchanged documents table was uploaded under a new immutable key')
    if any(item['action'] == 'payload_read' and item['bytes'] for item in operations):
        failures.append('Update preparation copied and hashed previous selected payloads')
    if any(Path(item['path']) == changed[1] for item in hashes):
        failures.append('Update publication rehashed unchanged documents input')
    totals = {action: dict(calls=sum(item['action'] == action for item in operations),
                           bytes=sum(item['bytes'] for item in operations if item['action'] == action))
              for action in ('metadata_read', 'metadata_write', 'payload_read', 'payload_write')}
    result = dict(rows_per_table=rows, correction_rows=1, tables=2, nested_ordered_parity=parity,
                  old_selected_payloads_preserved=old_preserved, reused_tables=reused,
                  reused_payload_bytes=sum(after_manifest['files'][label]['bytes'] for label in reused),
                  publication_input_hashes=hashes, totals=totals, operations=operations,
                  before_manifest=before_manifest, after_manifest=after_manifest,
                  requirement_failures=failures, source_acquisition=False, production_writes=False,
                  measurement_scope='LocalStore calls and publication.file_identity calls; excludes validator reads, '
                                    'footer reads, copy-internal hashing and OS I/O; synthetic fixtures only')
    (output / 'summary.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--rows', type=int, default=8)
    parser.add_argument('--require-reuse', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.rows <= 10000:
        parser.error('--rows must be 1 through 10000')
    result = measure(args.output, rows=args.rows)
    print(json.dumps({key: result[key] for key in ('totals', 'requirement_failures', 'nested_ordered_parity')}))
    if args.require_reuse and result['requirement_failures']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
