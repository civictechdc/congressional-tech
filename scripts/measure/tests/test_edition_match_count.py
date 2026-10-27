"""S2 counts distinct candidate bodies through native joins, retaining unknowns."""
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets

ROOT = Path(__file__).parents[3]
spec = importlib.util.spec_from_file_location('edition_match_count', ROOT / 'scripts/measure/edition_match_count.py')
measurement = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measurement)
FIXTURE = json.loads((ROOT / 'model/fixtures/s2-edition-count.json').read_text())


def inputs(tmp_path, *, complete=False, missing_refs=False):
    directory = tmp_path / 'inputs'; directory.mkdir()
    schema = {
        'rendition_members': pa.schema([(key, pa.string()) for key in ['group_kind','group_id','body_key']]),
        'edition_bodies': pa.schema([('body_key',pa.string())]),
        'fingerprint_candidates': pa.schema([('body_key',pa.string())]),
        'fingerprints': pa.schema([('body_key',pa.string()),('fingerprint',pa.string())]),
    }
    descriptor = dict(version=1,relation_basis='canonical_model',source_sql_sha256='a'*64,profile_sha256='b'*64,
        snapshots={'captures':'fixture-snapshot'},coverage={'same_stem':'complete','publisher':'complete'},relations={})
    for name in schema:
        rows = [dict(row) for row in FIXTURE[name]]
        if name == 'fingerprints':
            if complete:
                for row in rows:
                    if row['body_key']==FIXTURE['complete_variant']['body_key']:
                        row['fingerprint']=FIXTURE['complete_variant']['fingerprint']
            if missing_refs:
                refs={row['body_key'] for row in FIXTURE['edition_bodies'][:2]}
                rows=[row for row in rows if row['body_key'] not in refs]
        path=directory/(name+'.parquet')
        pq.write_table(pa.Table.from_pylist(rows,schema=schema[name]),path)
        descriptor['relations'][name]=dict(path=path.name,sha256=sha256(path.read_bytes()).hexdigest())
    path=directory/'relations.json';path.write_text(json.dumps(descriptor))
    return path


def test_native_count_preserves_unknowns_and_deduplicates_bodies(tmp_path):
    path=inputs(tmp_path)
    result=measurement.measure(path,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),work=tmp_path/'work')
    for key,value in FIXTURE['expected'].items():
        if key!='matching_bodies':assert result[key]==value
    examples=pq.read_table(tmp_path/'work/matching-examples.parquet').to_pylist()
    assert {row['body_key'] for row in examples}==set(FIXTURE['expected']['matching_bodies'])
    assert result['decision_ready'] is False
    assert result['source']['source_sql_sha256']=='a'*64


def test_complete_fingerprints_and_coverage_qualify_the_actual_count(tmp_path):
    path=inputs(tmp_path,complete=True)
    result=measurement.measure(path,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),work=tmp_path/'work')
    assert result['matching_candidates']==3 and result['unknown_candidates']==0
    assert result['status']=='complete' and result['decision_ready'] is True
    descriptor=json.loads(path.read_text());descriptor['coverage']['publisher']='pending';path.write_text(json.dumps(descriptor))
    partial=measurement.measure(path,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),work=tmp_path/'partial')
    assert partial['matching_candidates']==3 and partial['status']=='incomplete'
    assert partial['decision_ready'] is False


def test_missing_reference_fingerprints_are_unknown_not_zero(tmp_path):
    path=inputs(tmp_path,missing_refs=True)
    result=measurement.measure(path,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),work=tmp_path/'work')
    assert result['matching_candidates']==1 and result['unknown_candidates']==3
    assert result['status']=='incomplete'


def test_missing_or_changed_relations_and_historical_proxy_refuse(tmp_path):
    path=inputs(tmp_path)
    value=json.loads(path.read_text())
    relation=path.parent/value['relations']['edition_bodies']['path']
    relation.write_bytes(relation.read_bytes()+b'changed')
    with pytest.raises(ValueError,match='digest'):
        measurement.measure(path,engine=None,work=tmp_path/'work')
    relation.unlink()
    with pytest.raises(ValueError,match='missing'):
        measurement.measure(path,engine=None,work=tmp_path/'work')
    value['relation_basis']='historical_proxy';path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='canonical'):
        measurement.measure(path,engine=None,work=tmp_path/'work')
    assert not (tmp_path/'work').exists()


def test_conflicting_fingerprints_refuse_a_qualified_count(tmp_path):
    path=inputs(tmp_path)
    descriptor=json.loads(path.read_text())
    relation=path.parent/descriptor['relations']['fingerprints']['path']
    table=pq.read_table(relation)
    conflict=pa.Table.from_pylist([dict(body_key=FIXTURE['expected']['matching_bodies'][0],fingerprint='d'*64)],schema=table.schema)
    pq.write_table(pa.concat_tables([table,conflict]),relation)
    descriptor['relations']['fingerprints']['sha256']=sha256(relation.read_bytes()).hexdigest();path.write_text(json.dumps(descriptor))
    with pytest.raises(ValueError,match='invariant'):
        measurement.measure(path,engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),work=tmp_path/'work')
    assert not (tmp_path/'work/measurement.json').exists()
