"""Current heads come from one read-only native catalog operation."""
import json

import pytest

from congress_api.lake import tables


PIN=dict(metadata_location='file:///fixture/metadata/v1.metadata.json',
    table_uuid='11111111-1111-4111-8111-111111111111',snapshot=None,schema_id=0)
TARGETS={name:dict(namespace=['archive'],name=name)
         for name in ['captures','readings','filename_readings']}


class Native:
    remote=None
    def __init__(self,results=None,error=None):self.results=results;self.error=error;self.jobs=[]
    def run_job(self,path):
        job=json.loads(path.read_text());self.jobs.append(job)
        if self.error:raise self.error
        return dict(table_operations=self.results if self.results is not None else
            [dict(name=name,kind='resolve',exists=True,**PIN) for name in TARGETS])


def test_resolve_batches_three_heads_without_table_or_data_writes(tmp_path):
    engine=Native()
    assert tables.resolve_tables(engine=engine,work=tmp_path/'resolve',
        catalog_root=tmp_path/'catalog',tables=TARGETS)=={name:PIN for name in TARGETS}
    assert len(engine.jobs)==1
    job=engine.jobs[0]
    assert job['inputs']==job['steps']==job['outputs']==[]
    assert job['table_operations']==[dict(kind='resolve',name=name,table=table)
                                     for name,table in TARGETS.items()]
    assert not (tmp_path/'catalog').exists()


def test_resolve_typed_absence_fails_without_inventing_an_empty_table(tmp_path):
    engine=Native([dict(name='readings',kind='resolve',exists=False)])
    with pytest.raises(ValueError,match='readings.*does not exist'):
        tables.resolve_tables(engine=engine,work=tmp_path/'resolve',catalog_root=tmp_path/'catalog',
                              tables={'readings':TARGETS['readings']})
    assert engine.jobs[0]['table_operations'][0]['kind']=='resolve'


@pytest.mark.parametrize('change',[
    {'exists':None},{'exists':'false'},{'metadata_location':None},{'table_uuid':None},
    {'snapshot':True},{'snapshot':-1},{'schema_id':True},{'schema_id':-1},
])
def test_resolve_refuses_incomplete_or_wrongly_typed_head(tmp_path,change):
    row=dict(name='readings',kind='resolve',exists=True,**PIN);row.update(change)
    with pytest.raises(ValueError,match='native table head'):
        tables.resolve_tables(engine=Native([row]),work=tmp_path/'resolve',
            catalog_root=tmp_path/'catalog',tables={'readings':TARGETS['readings']})


def test_resolve_native_failure_propagates_without_create_or_append(tmp_path):
    error=OSError('native catalog unavailable');engine=Native(error=error)
    with pytest.raises(OSError,match='native catalog unavailable'):
        tables.resolve_tables(engine=engine,work=tmp_path/'resolve',
            catalog_root=tmp_path/'catalog',tables=TARGETS)
    assert all(op['kind']=='resolve' for op in engine.jobs[0]['table_operations'])


def test_native_input_keeps_empty_snapshot_pin_without_export(tmp_path):
    assert tables.table_input('existing',PIN)==dict(name='existing',kind='native_table',**PIN)
    assert tables.table_input('captures',tmp_path/'captures.parquet')==dict(
        name='captures',kind='parquet',path=str(tmp_path/'captures.parquet'))
    with pytest.raises(ValueError,match='immutable table pin'):
        tables.table_input('existing',dict(PIN,extra='unbound'))
