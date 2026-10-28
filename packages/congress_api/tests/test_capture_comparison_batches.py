"""Retained batch evidence compares once, with global multiplicity and full old scope."""
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from docspec_client.client import NativeDatasets

from congress_api.lake.capture_comparison import compare_old,RULES


KEY='receipts/documents/2026-10-20/original.gz'
NEW_KEY='receipts/documents/2026-10-28/added.gz'


def batch_fixture(tmp_path,*,old_count=2,new_count=2,extra=False):
    """Two repeated source facts in separate files must match two global occurrences."""
    common=dict(receipt_key=KEY,receipt_line=1,pointer_json='["body"]',context_url='https://fixture.test/a',
        bytes=100,stored_bytes=42,media_type='application/pdf',fidelity='exact-bytes',http_status=200,
        retrieved_at='2026-10-20T00:00:00Z')
    old_rows=[dict(common,sha256='a'*64,reference_kind='capture') for _ in range(old_count)]
    old=tmp_path/'old.parquet';pq.write_table(pa.Table.from_pylist(old_rows),old)
    new_rows=[dict(common,sha256=bytes.fromhex('a'*64),capture_index=index) for index in range(new_count)]
    if extra:new_rows.append(dict(new_rows[0],receipt_key=NEW_KEY,capture_index=0))
    sources=[]
    for index,row in enumerate(new_rows):
        path=tmp_path/f'batch-{index}.parquet';pq.write_table(pa.Table.from_pylist([row]),path);sources.append(path)
    return old,sources


def native():return NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])


def test_two_batch_files_keep_global_repeated_occurrences_and_file_order_does_not_matter(tmp_path):
    old,parts=batch_fixture(tmp_path)
    first=compare_old(parts,old,engine=native(),work=tmp_path/'first')
    second=compare_old(parts[::-1],old,engine=native(),work=tmp_path/'second')
    for report in (first,second):
        assert report['matched']==2 and report['old_rows']==report['new_rows']==2
        assert report['old_only']==report['new_only']==report['unexplained']==0
        assert report['owner_gate'] is False and report['rules']==RULES
    for name in ('old-only','new-only','changed-fields'):
        assert pq.read_table(tmp_path/'first'/f'{name}.parquet').equals(
            pq.read_table(tmp_path/'second'/f'{name}.parquet'))
    job=json.loads((tmp_path/'first/job.json').read_text())
    union=[step for step in job['steps'] if step['name']=='new_input']
    assert len(union)==1 and union[0]['materialize'] is True and 'UNION ALL' in union[0]['sql']
    assert len([item for item in job['inputs'] if item['kind']=='parquet'])==3


def test_scoped_new_evidence_excludes_only_explicit_additions_and_never_filters_old_index(tmp_path):
    old,parts=batch_fixture(tmp_path,extra=True)
    # An old row outside the selected new scope still has to become an owner gate.
    old_rows=pq.read_table(old).to_pylist();old_rows.append(dict(old_rows[0],receipt_key=NEW_KEY))
    pq.write_table(pa.Table.from_pylist(old_rows),old)
    report=compare_old(parts,old,engine=native(),work=tmp_path/'scope',receipt_keys=[KEY])
    assert report['old_rows']==3 and report['new_rows']==2 and report['matched']==2
    assert report['old_only']==1 and report['new_only']==0 and report['owner_gate'] is True
    assert report['scope']==dict(receipt_keys=[KEY],input_new_rows=3,
        excluded_new_receipts=[dict(receipt_key=NEW_KEY,rows=1)])
    [lost]=pq.read_table(tmp_path/'scope/old-only.parquet').to_pylist()
    assert lost['receipt_key']==NEW_KEY


@pytest.mark.parametrize('change',['empty','duplicate','same-path-alias','schema','metadata'])
def test_bad_evidence_sets_refuse_before_creating_comparison_job(tmp_path,change):
    old,parts=batch_fixture(tmp_path)
    if change=='empty':parts=[]
    elif change=='duplicate':parts.append(parts[0])
    elif change=='same-path-alias':parts.append(parts[0].parent/'subdir'/ '..'/parts[0].name)
    else:
        table=pq.read_table(parts[1])
        if change=='schema':table=table.append_column('extra',pa.array(['not-an-equal-schema']))
        else:table=table.replace_schema_metadata({'changed':'metadata'})
        pq.write_table(table,parts[1])
    with pytest.raises(ValueError):compare_old(parts,old,engine=native(),work=tmp_path/'refused')
    assert not (tmp_path/'refused').exists()


@pytest.mark.parametrize('keys',[[],[KEY,KEY],['bodies/not-a-receipt'],['receipts/../escape']])
def test_bad_new_scope_refuses_before_comparison_job(tmp_path,keys):
    old,parts=batch_fixture(tmp_path)
    with pytest.raises(ValueError):
        compare_old(parts,old,engine=native(),work=tmp_path/'refused',receipt_keys=keys)
    assert not (tmp_path/'refused').exists()


def test_read_only_comparison_cli_returns_owner_gate_and_complete_evidence(tmp_path,capsys):
    from congress_api.cli.capture_compare import main
    old,parts=batch_fixture(tmp_path,old_count=3,extra=True)
    inventory=tmp_path/'evidence.json';inventory.write_text(json.dumps([str(path) for path in parts]))
    scope=tmp_path/'original-receipts.json';scope.write_text(json.dumps([KEY]))
    work=tmp_path/'comparison'
    assert main(['--evidence-inventory',str(inventory),'--receipt-keys',str(scope),'--old-index',str(old),
        '--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],'--work',str(work)])==2
    report=json.loads(capsys.readouterr().out)
    assert report['old_rows']==3 and report['new_rows']==2 and report['old_only']==1
    assert report['owner_gate'] is True and report['rules']==RULES
    assert pq.read_metadata(work/'old-only.parquet').num_rows==1
    assert all((work/(name+'.parquet')).exists() for name in ('new-only','changed-fields'))
    assert json.loads((work/'comparison.json').read_text())==report
