"""Mechanical native table fixture; lifecycle qualification uses the real CLI."""
from contextlib import contextmanager
from hashlib import sha256

import pyarrow as pa


class MemoryNative:
    def __init__(self):
        self.tables, self.writes, self.reads = {}, [], []

    def execution_files(self):
        return ()

    def run_table(self, table, *, dataset, operation, definition):
        if dataset in self.tables and not self.tables[dataset].equals(table):
            raise ValueError('Conflicting test native request')
        if dataset not in self.tables:
            self.tables[dataset] = table
            self.writes.append(dataset)
        return dict(verified=True, id=dataset,
                    dataset=dict(dataset=dataset, version=dataset, groups=dict(source=dict(rows=len(table)))))

    @contextmanager
    def source_batches(self, pin, *, schema=None):
        dataset = pin['dataset']['dataset']
        self.reads.append(dataset)
        table = self.tables[dataset]
        if schema is not None:
            table = table.cast(schema)
        yield pa.RecordBatchReader.from_batches(table.schema, table.to_batches(max_chunksize=2))


def memory_raw_storage(store, **kwargs):
    from congress_api.retention.raw_storage import RawStorage
    if not hasattr(store, 'put_index_selector'):
        def put(key, data, *, expected_version):
            old = store.read(key)
            version = sha256(old).hexdigest() if old is not None else None
            if version != expected_version:
                raise RuntimeError('Concurrent raw selection')
            return store.put(key, data, immutable=False)
        store.put_index_selector = put
    return RawStorage(store, MemoryNative(), **kwargs)
