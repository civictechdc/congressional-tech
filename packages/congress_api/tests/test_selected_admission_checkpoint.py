"""Private selected metadata survives native failures without admitting partial work."""
from contextlib import contextmanager
import fcntl
from hashlib import sha256
import json

import pyarrow as pa
import pytest

from congress_api.retention.catalog_batches import SelectedCatalogTable, iterator_prepared_components
from congress_api.retention.immutable_metadata import encoded
from test_catalog_coalesced_batches import Native, Store, SCHEMA, prepare


def selected(tmp_path, count=130, native=None):
    native = native or Native()
    store = Store(tmp_path / 'store')
    refs = list(iterator_prepared_components(store, prepare(store, native, count)))
    identity = dict(selected_ref=dict(sha256=sha256(encoded(refs)).hexdigest()))
    table = SelectedCatalogTable(SCHEMA, lambda: iter(refs), store=store, native=native,
        label='filenames', rows=count, max_ordered_bytes=1 << 20, selection_identity=identity)
    return table, refs, native


def read(table, directory=None):
    return pa.Table.from_batches(list(table.iter_batches(include_order=True, admission_directory=directory)))


@pytest.mark.parametrize('failure', ['opening', 'truncation'])
def test_completed_admission_survives_native_failure_and_retry_keeps_exact_rows(tmp_path, monkeypatch, failure):
    class Interrupted(Native):
        interrupt = False
        @contextmanager
        def source_batches(self, *args, **kwargs):
            with super().source_batches(*args, **kwargs) as reader:
                if not self.interrupt:
                    yield reader
                    return
                self.interrupt = False
                if failure == 'opening':
                    raise OSError('transient native read')
                def truncated():
                    yield reader.read_next_batch().slice(0, 1)
                    raise OSError('truncated native stream')
                with pa.RecordBatchReader.from_batches(reader.schema, truncated()) as partial:
                    yield partial
    native = Interrupted()
    table, refs, _ = selected(tmp_path, native=native)
    expected = read(table)
    folder = tmp_path / 'owned.recovery-admission'
    native.interrupt = True
    with pytest.raises((OSError, pa.ArrowException), match='transient|truncated'):
        read(table, folder)
    receipt = json.loads((folder / 'complete.json').read_bytes())
    assert receipt['status'] == 'complete'
    assert receipt['file']['sha256'] == sha256((folder / 'admission.sqlite').read_bytes()).hexdigest()
    assert not list(folder.glob('.building-*'))
    # A fresh table/reader process boundary needs no member enumeration or proof reads.
    fresh = SelectedCatalogTable(SCHEMA, lambda: pytest.fail('admission enumerated again'),
        store=table.store, native=native, label='filenames', rows=130, max_ordered_bytes=1 << 20,
        selection_identity=table._selection_identity)
    monkeypatch.setattr(fresh, '_admit', lambda db: pytest.fail('admission rebuilt'))
    actual = read(fresh, folder)
    assert actual.equals(expected, check_metadata=True)
    assert actual['_catalog_order'].to_pylist() == list(range(130))


def test_partial_admission_is_not_marked_complete_and_orphan_database_is_rebuilt(tmp_path):
    table, refs, native = selected(tmp_path, count=2)
    folder = tmp_path / 'admission'
    def interrupted():
        yield refs[0]
        raise OSError('metadata interrupted')
    table.component_refs = interrupted
    with pytest.raises(OSError, match='metadata interrupted'):
        read(table, folder)
    assert not (folder / 'complete.json').exists() and not native.reads
    assert not list(folder.glob('.building-*'))
    (folder / 'admission.sqlite').write_bytes(b'unfinished or untrusted database')
    table.component_refs = lambda: iter(refs)
    assert len(read(table, folder)) == 2
    assert json.loads((folder / 'complete.json').read_bytes())['status'] == 'complete'


@pytest.mark.parametrize('change', ['source', 'schema', 'rows', 'policy', 'boolean_version', 'tamper', 'truncated', 'missing'])
def test_checkpoint_refuses_changed_binding_or_file_before_native_reads(tmp_path, monkeypatch, change):
    table, _, native = selected(tmp_path, count=2)
    folder = tmp_path / 'admission'
    read(table, folder)
    native.reads.clear()
    database, receipt = folder / 'admission.sqlite', folder / 'complete.json'
    if change == 'source':
        table._selection_identity = dict(selected_ref=dict(sha256='0' * 64))
    elif change == 'schema':
        table.schema_arrow = SCHEMA.with_metadata({b'catalog_id': b'changed'})
    elif change == 'rows':
        table.rows += 1
    elif change in ('policy', 'boolean_version'):
        value = json.loads(receipt.read_bytes())
        if change == 'policy':value['binding']['implementation_sha256'] = '0' * 64
        else:value['version'] = True
        receipt.write_bytes(encoded(value))
    elif change == 'tamper':
        raw = bytearray(database.read_bytes());raw[-1] ^= 1;database.write_bytes(raw)
    elif change == 'truncated':
        database.write_bytes(database.read_bytes()[:-1])
    else:
        database.unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        read(table, folder)
    assert not native.reads


def test_checkpoint_requires_exact_selection_and_excludes_concurrent_owners(tmp_path):
    table, _, native = selected(tmp_path, count=2)
    identity = table._selection_identity
    table._selection_identity = None
    folder = tmp_path / 'admission'
    with pytest.raises(ValueError, match='exact selection'):
        read(table, folder)
    assert not folder.exists()
    table._selection_identity = identity
    read(table, folder)
    native.reads.clear()
    with (folder / '.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='already in use'):
            read(table, folder)
    assert not native.reads


@pytest.mark.parametrize('name', ['directory', 'admission.sqlite', 'complete.json', '.lock'])
def test_checkpoint_refuses_symbolic_links(tmp_path, name):
    table, _, native = selected(tmp_path, count=2)
    folder = tmp_path / 'admission'
    read(table, folder)
    native.reads.clear()
    if name == 'directory':
        link = tmp_path / 'link';link.symlink_to(folder, target_is_directory=True);folder = link
    else:
        path = folder / name;kept = folder / (name + '.original');path.rename(kept);path.symlink_to(kept)
    with pytest.raises(ValueError, match='symlink'):
        read(table, folder)
    assert not native.reads
