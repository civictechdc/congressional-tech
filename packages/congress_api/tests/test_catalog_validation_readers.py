"""Catalog reference validation owns every acquired Parquet reader."""
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention import document_index as index
from test_catalog_publication import pair


@pytest.mark.parametrize('failure', ['success', 'second_open', 'schema', 'counts', 'references', 'duplicate'])
def test_reference_validation_closes_readers_on_every_exit(tmp_path, monkeypatch, failure):
    paths = pair(tmp_path / 'pair')
    if failure == 'schema':
        table = pq.read_table(paths[1]).replace_schema_metadata({b'catalog_id': b'other'})
        pq.write_table(table, paths[1])
    elif failure == 'references':
        table = pq.read_table(paths[1]).set_column(0, 'source_id', pa.array(['missing']))
        pq.write_table(table, paths[1])
    elif failure == 'duplicate':
        table = pq.read_table(paths[0])
        pq.write_table(pa.concat_tables([table, table]), paths[0])
    original, readers = pq.ParquetFile, []
    def acquire(path):
        if failure == 'second_open' and readers:
            raise OSError('injected second reader open')
        reader = original(path)
        readers.append(reader)
        return reader
    monkeypatch.setattr(index.pq, 'ParquetFile', acquire)
    if failure == 'success':
        index.validate_document_indexes(*paths, source_rows=1, document_rows=1)
    else:
        message = 'second reader open' if failure == 'second_open' else (
            'catalog_id' if failure == 'schema' else 'references')
        with pytest.raises(OSError if failure == 'second_open' else ValueError, match=message):
            index.validate_document_indexes(*paths, source_rows=2 if failure == 'counts' else None)
    assert len(readers) == (1 if failure == 'second_open' else 2)
    assert all(reader.closed for reader in readers)


def test_reader_cleanup_error_keeps_primary_catalog_refusal(tmp_path, monkeypatch):
    paths = pair(tmp_path / 'pair')
    original, readers = pq.ParquetFile, []
    class BrokenClose:
        def __init__(self, path):
            self.reader = original(path)
            readers.append(self.reader)
        def __getattr__(self, name): return getattr(self.reader, name)
        def __enter__(self): return self
        def __exit__(self, *args):
            self.reader.close()
            raise OSError('injected reader close')
    monkeypatch.setattr(index.pq, 'ParquetFile', BrokenClose)
    with pytest.raises(ValueError, match='references') as caught:
        index.validate_document_indexes(*paths, source_rows=2)
    assert len(readers) == 2 and all(reader.closed for reader in readers)
    assert any('injected reader close' in note for note in caught.value.__notes__)
