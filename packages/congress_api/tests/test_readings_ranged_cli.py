"""The ranged owner command plans custody without credentials or raw effects."""
import json
import os

import pytest

from congress_api.retention.r2 import R2Store
from test_readings_ranged import Client
from test_readings_ranged_plan import inputs


def test_cli_ranged_plan_reports_physical_custody_without_get_or_cache(tmp_path,capsys):
    from congress_api.cli.readings import main
    values,stored,_=inputs(tmp_path);values.pop('engine')
    values={k:str(v) if hasattr(v,'as_posix') else v for k,v in values.items()}
    work=tmp_path/'plan';values.update(work=str(work),parser=None,
        apply=dict(catalog_root=str(tmp_path/'catalog'),table=dict(namespace=['archive'],name='readings')))
    spec=tmp_path/'spec.json';spec.write_text(json.dumps(values))
    client=Client(stored,'gzip');store=R2Store(client,'bucket',cache_dir=work/'raw-pages')
    assert main(['--spec',str(spec),'--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],
        '--mode','backfill','--plan','--batch-size','32','--raw-bucket','bucket'],
        read_current=lambda **_:None,body_store=store)==0
    report=json.loads(capsys.readouterr().out)
    assert report['raw_custody']['missing_pins']==0 and report['work_items']==1
    assert not client.reads and not (work/'raw-pages').exists() and not (work/'parsed').exists()


@pytest.mark.parametrize('extra',[
    ['--raw-get-workers','0'],['--raw-get-workers','65'],['--raw-cache-bytes','0'],
    ['--raw-cache-bytes',str((10<<30)+1)],
])
def test_cli_invalid_ranged_bounds_refuse_before_spec_or_configuration(tmp_path,extra):
    from congress_api.cli.readings import main
    with pytest.raises(SystemExit) as error:
        main(['--spec',str(tmp_path/'absent.json'),'--engine-config','/unopened/runtime.json',
            '--mode','backfill','--plan','--batch-size','32','--raw-bucket','bucket',*extra])
    assert error.value.code==2 and not (tmp_path/'work').exists()


def test_cli_plan_accepts_exact_listing_without_creating_a_client(tmp_path,capsys):
    from congress_api.cli.readings import main
    from test_readings_listed_etag import listing
    values,stored,key=inputs(tmp_path,missing='md5');values.pop('engine')
    values={k:str(v) if hasattr(v,'as_posix') else v for k,v in values.items()}
    values.update(work=str(tmp_path/'work'),parser=None,
        apply=dict(catalog_root=str(tmp_path/'catalog'),table=dict(namespace=['archive'],name='readings')))
    spec=tmp_path/'spec.json';spec.write_text(json.dumps(values))
    path=listing(tmp_path,key,stored,etag='"opaque"')
    assert main(['--spec',str(spec),'--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],
        '--mode','backfill','--plan','--batch-size','32','--raw-bucket','bucket',
        '--body-listing',str(path)],read_current=lambda **_:None)==0
    report=json.loads(capsys.readouterr().out)
    assert report['raw_custody']['listing_etag']==1 and report['raw_custody']['missing_pins']==0
    assert not (tmp_path/'work/raw-pages').exists()
