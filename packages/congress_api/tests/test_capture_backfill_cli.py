"""Batch commands share the incremental writer and expose unfinished qualification."""
import json
import os

import pytest

from congress_api.cli.captures_ingest import main
from test_capture_backfill_execution import inputs


def arguments(tmp_path):
    files,counts=inputs(tmp_path/'raw')
    inventory=tmp_path/'inventory.json';inventory.write_text(json.dumps(files))
    costs=tmp_path/'counts.json';costs.write_text(json.dumps(counts))
    return ['--backfill','--source-counts',str(costs),'--receipt-inventory',str(inventory),
        '--engine-config',os.environ['DOCSPEC_JOB_CONFIG'],'--work',str(tmp_path/'work'),
        '--batch-bytes','1000','--batch-items','1']


def test_batch_plan_reads_only_metadata_and_does_not_create_catalog(tmp_path,capsys):
    args=arguments(tmp_path)
    # Planning needs source costs, not source payload or qualification files.
    from pathlib import Path
    for path in (tmp_path/'raw').rglob('*'):
        if path.is_file():path.unlink()
    assert main(args)==0
    value=json.loads(capsys.readouterr().out)
    assert value['status']=='planned' and value['qualified_for_downstream'] is False
    assert len(value['plan']['batches'])==2
    assert not (tmp_path/'work').exists()


def test_public_batch_cli_applies_two_native_commits_and_reports_guard_only(tmp_path,capsys):
    args=arguments(tmp_path)+['--apply','--table','archive.captures_generation',
        '--catalog-root',str(tmp_path/'catalog'),'--table-location',str(tmp_path/'data'),
        '--create-table','--create-namespace']
    assert main(args)==0
    report=json.loads(capsys.readouterr().out)
    assert report['status']=='public_guard_passed' and report['guard']['rows']==2
    assert report['qualified_for_downstream'] is False
    assert len(report['batches'])==2
    assert all(row['outcome']['applied'] for row in report['batches'])
    assert report['engine']['config']['sha256']


@pytest.mark.parametrize('extra',[
    ['--backfill'],['--source-counts','missing.json'],
    ['--backfill','--source-counts','missing.json','--existing','old.parquet'],
    ['--backfill','--source-counts','missing.json','--old-index','old.parquet'],
    ['--backfill','--source-counts','missing.json','--prove-equivalence','--apply','--table','a.b'],
    ['--backfill','--source-counts','missing.json','--prove-equivalence'],
    ['--backfill','--source-counts','missing.json','--batch-items','0'],
])
def test_invalid_batch_modes_refuse_before_source_or_runtime_reads(tmp_path,extra):
    with pytest.raises(SystemExit) as error:
        main(['--receipt-inventory',str(tmp_path/'unopened.json'),'--engine-config',
            str(tmp_path/'unopened-runtime.json'),'--work',str(tmp_path/'work'),*extra])
    assert error.value.code==2 and not (tmp_path/'work').exists()
