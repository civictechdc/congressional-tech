"""One native source registration composes narrowing, mapping and refusals."""
import json
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets
from congress_api.retention.provenance import file_pin
from test_receipt_metadata import counter_fixture
from capture_qualification_helpers import write_qualified_parquet,created_qualifications


def engine():
    return NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])


def test_counter_and_direct_have_equal_rows_and_pinned_inputs(tmp_path):
    from congress_api.lake.captures import stage_captures
    counter,files=counter_fixture(tmp_path)
    native=engine()
    direct=stage_captures(files,engine=native,work=tmp_path/'direct')
    fused=stage_captures([dict(key=row['key']) for row in files],engine=native,
        work=tmp_path/'fused',validated_counter=counter,source_qualifications=created_qualifications(counter))
    for name in ('capture-evidence.parquet','captures.parquet'):
        expected=pq.read_table(direct/name)
        assert pq.read_table(direct/name).equals(expected)
        assert pq.read_table(fused/name).equals(expected)
    job=json.loads((fused/'job.json').read_text())
    assert [item for item in job['inputs'] if item['kind']=='parquet']==[
        dict(name='source',kind='parquet',path=str(counter))]
    assert [output['name'] for output in job['outputs']]==['capture-evidence']
    assert not (fused/'receipt-metadata').exists()
    assert (fused/'captures.parquet').read_bytes()==(direct/'captures.parquet').read_bytes()
    names=[item['name'] for item in job['inputs']+job['steps']]
    assert len(names)==len(set(names))
    alive={item['name'] for item in job['inputs']}
    for step in job['steps']:
        alive.add(step['name'])
        alive.difference_update(step.get('release_after',[]))
    assert alive=={'capture_facts','capture_violations','source_counts'}
    steps={step['name']:step for step in job['steps']}
    assert steps['capture_facts']['materialize'] and steps['capture_violations']['materialize']
    assert steps['scalar_rows']['materialize']
    assert not steps['lines'].get('materialize',False)
    public_job=json.loads((fused/'export/job.json').read_text())
    assert public_job['inputs'][0]['path']==str(fused/'capture-evidence.parquet')
    manifest=json.loads((fused/'ingested-receipts.json').read_text())
    assert manifest['version']==2 and 'metadata' not in manifest
    assert manifest['input']['kind']=='validated-counter'
    [source_pin]=manifest['input']['sources']
    assert {name:source_pin[name] for name in ('path','sha256','size')}==dict(path=str(counter),**file_pin(counter))
    assert source_pin['qualification']['kind']=='reused_qualification'
    authority=next(iter(created_qualifications(counter).values()))
    assert source_pin['qualification']['path']==authority
    assert {name:source_pin['qualification'][name] for name in ('sha256','size')}==file_pin(authority)
    assert manifest['input']['producer']['sha256']
    assert manifest['input']['job']==file_pin(fused/'job.json')
    assert manifest['engine']['binary_sha256']==native.binary_sha256
    assert manifest['receipt_keys']==[row['key'] for row in files]


def test_fused_counter_refuses_absent_selected_key_before_public_output(tmp_path):
    from congress_api.lake.captures import stage_captures
    counter,_=counter_fixture(tmp_path)
    work=tmp_path/'refused'
    with pytest.raises(ValueError,match='selected receipt not present'):
        stage_captures([dict(key='receipts/documents/2026-10-20/missing.gz')],engine=engine(),
                       work=work,validated_counter=counter,source_qualifications=created_qualifications(counter))
    assert not (work/'captures.parquet').exists()
    assert not (work/'ingested-receipts.json').exists()


def test_fused_counter_refuses_unknown_vocabulary_before_public_output(tmp_path):
    from congress_api.lake.captures import stage_captures
    counter,files=counter_fixture(tmp_path)
    table=pq.read_table(counter)
    rows=table.to_pylist()
    for row in rows:
        source=json.loads(row['__raw_line']);source['outcome']='unreviewed-vocabulary'
        row['__raw_line']=json.dumps(source)
    write_qualified_parquet(pa.Table.from_pylist(rows,schema=table.schema),counter)
    work=tmp_path/'refused'
    with pytest.raises(ValueError,match='unknown outcome'):
        stage_captures([dict(key=row['key']) for row in files],engine=engine(),
                       work=work,validated_counter=counter,source_qualifications=created_qualifications(counter))
    assert not (work/'captures.parquet').exists()
    assert not (work/'ingested-receipts.json').exists()


def test_cli_validated_counter_fuses_without_intermediate_metadata_stage(tmp_path,capsys):
    from congress_api.cli.captures_ingest import main
    counter,files=counter_fixture(tmp_path)
    inventory=tmp_path/'inventory.json'
    inventory.write_text(json.dumps([dict(key=row['key']) for row in files]))
    work=tmp_path/'stage'
    qualifications=tmp_path/'source-qualifications.json'
    qualifications.write_text(json.dumps(created_qualifications(counter)))
    assert main(['--receipt-inventory',str(inventory),'--validated-counter',str(counter),
        '--source-qualifications',str(qualifications),
        '--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],'--work',str(work)])==0
    assert json.loads(capsys.readouterr().out)['applied'] is False
    assert pq.read_metadata(work/'captures.parquet').num_rows==6
    assert not (tmp_path/'stage-metadata').exists()
