"""Historical assembly proofs use the same local budgets as assembly backfill."""
import json
import os
from pathlib import Path

import pytest
from docspec_client.client import NativeDatasets

from congress_api.lake import capture_backfill as backfill


ASSEMBLY='receipts/house/meeting-xml/undated/assemble-20260930.jsonl.gz'
ORDINARY='receipts/documents/2026-10-28/download-fixture.jsonl.gz'


@pytest.mark.parametrize('keys,local,name,memory,physical',[
    ([ORDINARY],True,'standard',14,16),
    ([ORDINARY,ASSEMBLY],True,'assembly',20,24),
    ([ASSEMBLY,ORDINARY],True,'assembly',20,24),
    ([ORDINARY,ASSEMBLY],False,'standard',14,16),
])
def test_receipt_profile_is_local_and_assembly_membership_drives_both_limits(keys,local,name,memory,physical):
    profile=backfill.receipt_profile([dict(key=key) for key in keys],local=local)
    assert profile==dict(name=name,memory_bytes=memory<<30,physical_limit=physical<<30)


def runtime(tmp_path,memory):
    source=Path(os.environ['DOCSPEC_JOB_CONFIG']).resolve()
    config=json.loads(source.read_text())
    limits=json.loads((source.parent/config['limits']).read_text());limits['memory_bytes']=memory<<30
    path=tmp_path/'limits.json';path.write_text(json.dumps(limits))
    config.update(binary=str((source.parent/config['binary']).resolve()),
        limits=str(path),workspace=str(tmp_path/'workspace'))
    path=tmp_path/'runtime.json';path.write_text(json.dumps(config))
    return NativeDatasets.from_config(path),path


@pytest.mark.parametrize('assembly,memory,allowed',[(True,20,True),(False,20,False),(True,21,False)])
def test_twenty_gib_native_admission_requires_local_assembly_and_keeps_its_ceiling(tmp_path,assembly,memory,allowed):
    engine,config=runtime(tmp_path,memory);files=[dict(key=ASSEMBLY if assembly else ORDINARY)]
    if allowed:
        value=backfill.runtime_identity(engine,config,files=files)
        assert value['source_revision']==engine.source_revision
    else:
        with pytest.raises(ValueError,match='budget'):backfill.runtime_identity(engine,config,files=files)
    assert not (tmp_path/'catalog').exists()


@pytest.mark.parametrize('memory,physical',[(10,16),(20,24)])
def test_local_assembly_proof_propagates_its_selected_runtime_to_every_nested_monitor(tmp_path,memory,physical):
    from test_captures_ingest import files as make_receipts
    from congress_api.lake.capture_backfill_proof import prove_equivalence
    files=[];counts=[]
    for index,key in enumerate([ORDINARY,ASSEMBLY]):
        files+=make_receipts(tmp_path/str(index),[dict(run_id='profile-fixture',mode='fetch',outcome='failed',
            family='documents',http_status=404,url=f'https://fixture.test/{index}',record={})],key)
        counts.append(dict(key=key,source_rows=1,expected_captures=1,uncompressed_bytes=200,
            list_items=1,max_line_bytes=200,max_line_items=1))
    engine,config=runtime(tmp_path,memory)
    result=prove_equivalence(files,counts,engine=engine,engine_config=config,work=tmp_path/'proof',
        table=dict(namespace=['assembly_profile_fixture'],name='captures'),catalog_root=tmp_path/'catalog',
        location=tmp_path/'table',byte_target=1000,item_target=1,required_keys=[ASSEMBLY])
    assert result['status']=='equivalent'
    assert result['comparison']['left_rows']==result['comparison']['right_rows']==2
    assert result['comparison']['left_only']==result['comparison']['right_only']==0
    for generation in result['generations'].values():
        assert generation['acceptance_measurement']['physical_limit']==physical<<30
        assert all(batch['measurement']['physical_limit']==physical<<30 for batch in generation['batches'])
