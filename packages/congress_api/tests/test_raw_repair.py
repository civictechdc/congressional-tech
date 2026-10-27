"""B12 repairs are pinned derived-index changes or verified missing raw creates."""
import gzip
import hashlib
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention.raw_repair import prepare_repair,apply_flat,restore_missing
from congress_api.retention.body_store import BodyStore,LocalAdapter
from congress_api.retention.provenance import file_pin
from docspec_client.client import NativeDatasets


def fixture(tmp_path):
    key='bodies/sha256/aa/'+'a'*64+'.gz'
    rows=[dict(_capture_order=0,body_key=key,receipt_key='r',receipt_line=1,pointer_json='["body"]',
               stored_sha256='0'*64,stored_bytes=10,untouched='preserved')]
    captures=tmp_path/'captures.parquet'
    repairs=tmp_path/'repairs.parquet'
    pq.write_table(pa.Table.from_pylist(rows),captures)
    pq.write_table(pa.Table.from_pylist([dict(key=key,receipt_key='r',receipt_line=1,
        pointer_json='["body"]',stored_sha256='1'*64,stored_bytes=11)]),repairs)
    return captures,repairs,rows


def test_index_correction_preserves_other_fields_and_refuses_stale_input(tmp_path):
    captures,repairs,rows=fixture(tmp_path)
    pin=file_pin(captures)['sha256']
    stage=prepare_repair(captures,repairs,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
                         work=tmp_path/'stage',expected=pin)
    assert pq.read_table(captures).to_pylist()==rows
    corrected=pq.read_table(Path(stage['output'])).to_pylist()
    assert corrected==[dict(rows[0],stored_sha256='1'*64,stored_bytes=11)]
    captures.write_bytes(b'changed selection')
    with pytest.raises(ValueError,match='changed'):
        apply_flat(tmp_path/'stage',captures)


def test_conflicting_repairs_are_not_selected_by_minimum(tmp_path):
    captures,repairs,rows=fixture(tmp_path)
    candidates=pq.read_table(repairs).to_pylist()
    pq.write_table(pa.Table.from_pylist(candidates+[dict(candidates[0],stored_sha256='2'*64)]),repairs)
    with pytest.raises(ValueError,match='Ambiguous'):
        prepare_repair(captures,repairs,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
                       work=tmp_path/'stage',expected=file_pin(captures)['sha256'])
    assert pq.read_table(captures).to_pylist()==rows


def test_restore_requires_exact_stored_source_and_cannot_overwrite(tmp_path):
    original=b'original source'
    stored=gzip.compress(original,mtime=0)
    sha=hashlib.sha256(original).hexdigest()
    key=f'bodies/sha256/{sha[:2]}/{sha}.gz'
    source=tmp_path/'stored.gz'
    source.write_bytes(stored)
    store=BodyStore(LocalAdapter(tmp_path/'raw'))
    result=restore_missing(store,key,source,expected_stored_sha256=hashlib.sha256(stored).hexdigest())
    assert result.outcome=='stored' and (tmp_path/'raw'/key).read_bytes()==stored
    assert restore_missing(store,key,source,expected_stored_sha256=hashlib.sha256(stored).hexdigest()).outcome=='unchanged'
    source.write_bytes(gzip.compress(b'wrong source',mtime=0))
    with pytest.raises(ValueError,match='identity|checksum'):
        restore_missing(store,key,source,expected_stored_sha256=hashlib.sha256(stored).hexdigest())
    assert (tmp_path/'raw'/key).read_bytes()==stored


@pytest.mark.parametrize('count',[1,2])
def test_native_selected_pin_repair_preserves_rows_old_snapshot_and_cas(tmp_path,count):
    from congress_api.retention.raw_storage import RawStorage
    from congress_api.retention.raw_schemas import LEGACY_CAPTURE_SCHEMA
    from congress_api.retention.raw_verifier import selected_captures
    from congress_api.retention.raw_repair import apply_native
    from native_test_helpers import native_test_client
    from testing_fakes import SelectorStore
    job_engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    storage=RawStorage(SelectorStore(),native_test_client(job_engine.binary,tmp_path/'old-native'),
                       max_state_rows=1000,max_capture_rows=1)
    rows=[dict(body_key=f'bodies/sha256/{char*2}/'+char*64+'.gz',sha256=char*64,bytes=100,
        receipt_key='receipts/f/day/run.jsonl.gz',receipt_line=n+1,pointer_json='["body"]',
        stored_sha256='0'*64,stored_bytes=10,context_url=f'https://example.gov/{char}')
        for n,char in enumerate('ab'[:count])]
    source=pa.Table.from_pylist(rows,schema=LEGACY_CAPTURE_SCHEMA)
    old=storage.publish(storage.prepare(storage.snapshot(),operation='seed',captures=source))
    repairs=tmp_path/'repairs.parquet'
    pq.write_table(pa.Table.from_pylist([dict(key=row['body_key'],receipt_key=row['receipt_key'],
        receipt_line=row['receipt_line'],pointer_json=row['pointer_json'],stored_sha256='1'*64,stored_bytes=11)
        for row in rows]),repairs)
    prepare_repair(selected_captures(storage),repairs,engine=job_engine,
                   work=tmp_path/'repair',expected=old.identity)
    repaired=apply_native(tmp_path/'repair',storage)
    now=storage.snapshot()
    assert repaired['after_rows']==old.manifest['captures']['rows']==now.manifest['captures']['rows']==count
    expected=source.to_pylist()
    for row in expected:row.update(stored_sha256='1'*64,stored_bytes=11)
    assert now.captures().to_pylist()==expected
    assert old.captures().equals(source)
    assert now.body_info('a'*64)['stored_sha256']=='1'*64
    with pytest.raises(ValueError,match='changed'):
        apply_native(tmp_path/'repair',storage)


def test_flat_repair_requires_explicit_observation_order(tmp_path):
    captures,repairs,rows=fixture(tmp_path)
    pq.write_table(pq.read_table(captures).drop(['_capture_order']),captures)
    with pytest.raises(ValueError,match='order'):
        prepare_repair(captures,repairs,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
            work=tmp_path/'repair',expected=file_pin(captures)['sha256'])


def test_fixed_binary_digest_type_and_observation_order_are_preserved(tmp_path):
    captures,repairs,rows=fixture(tmp_path)
    rows[0]['stored_sha256']=bytes.fromhex(rows[0]['stored_sha256'])
    schema=pa.schema([pa.field(name,pa.binary(32) if name=='stored_sha256' else kind)
        for name,kind in [('body_key',pa.string()),('receipt_key',pa.string()),('receipt_line',pa.int64()),
                          ('pointer_json',pa.string()),('stored_sha256',pa.binary(32)),('stored_bytes',pa.int64()),
                          ('untouched',pa.string()),('_capture_order',pa.int64())]])
    pq.write_table(pa.Table.from_pylist(rows,schema=schema),captures)
    stage=prepare_repair(captures,repairs,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),
        work=tmp_path/'repair',expected=file_pin(captures)['sha256'])
    corrected=pq.read_table(stage['output'])
    assert corrected.schema.equals(schema,check_metadata=False)
    assert corrected['stored_sha256'].to_pylist()==[bytes.fromhex('1'*64)]
    assert corrected['_capture_order'].to_pylist()==[0]
