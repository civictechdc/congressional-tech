"""Every capture staging path runs at bounded batch rows, with unchanged bytes (ct-uupp)."""
import ast
import json
import os
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from docspec_client.client import NativeDatasets

from congress_api.lake import capture_staging

ROOT=Path(__file__).resolve().parents[3]


def engine(tmp_path,batch_rows):
    source=Path(os.environ['DOCSPEC_JOB_CONFIG']).resolve();config=json.loads(source.read_text())
    limits=json.loads((source.parent/config['limits']).read_text());limits['batch_rows']=batch_rows
    tmp_path.mkdir(parents=True,exist_ok=True);path=tmp_path/'limits.json';path.write_text(json.dumps(limits))
    config.update(binary=str((source.parent/config['binary']).resolve()),limits=str(path),
        workspace=str(tmp_path/'workspace'))
    path=tmp_path/'runtime.json';path.write_text(json.dumps(config))
    return NativeDatasets.from_config(path)


def test_only_the_bounded_entry_point_calls_the_mapping_stage():
    """A new caller of captures.stage_captures would stage at its runtime's batch rows."""
    allowed={ROOT/'packages/congress_api/src/congress_api/lake/captures.py',
             ROOT/'packages/congress_api/src/congress_api/lake/capture_staging.py'}
    direct=[]
    for path in sorted([*ROOT.glob('packages/*/src/**/*.py'),*ROOT.glob('packages/*/tests/**/*.py'),*ROOT.glob('scripts/**/*.py')]):
        if path in allowed:continue
        for node in ast.walk(ast.parse(path.read_text(),str(path))):
            if (isinstance(node,ast.ImportFrom) and node.module=='congress_api.lake.captures'
                    and any(name.name in ('stage_captures','*') for name in node.names)) or (
                    isinstance(node,ast.Attribute) and node.attr=='stage_captures'
                    and isinstance(node.value,ast.Name) and node.value.id=='captures'):
                direct.append(f'{path.relative_to(ROOT)}:{node.lineno}')
    assert direct==[]


@pytest.mark.parametrize('configured,staged',[(8192,capture_staging.STAGE_BATCH_ROWS),(512,512)])
def test_staging_engine_keeps_the_pinned_runtime_and_bounds_batch_rows(tmp_path,configured,staged):
    native=engine(tmp_path,configured);native._remote_secrets={'DOCSPEC_FIXTURE':'kept'}
    bounded=capture_staging.bounded_engine(native,tmp_path/'derived')
    assert json.loads(bounded.limits.read_text())==dict(json.loads(native.limits.read_text()),batch_rows=staged)
    assert (bounded is native)==(configured<=capture_staging.STAGE_BATCH_ROWS)
    for name in ('binary','workspace','remote','timeout','source_revision','platform','build_features','binary_sha256'):
        assert getattr(bounded,name)==getattr(native,name)
    assert bounded._remote_secrets==native._remote_secrets
    bounded.verify_runtime()


def test_staged_bytes_do_not_depend_on_batch_rows(tmp_path):
    """The bound changes memory only: a 2-row and an 8192-row runtime stage identical files."""
    from test_captures_ingest import body,files as receipt_files
    rows=[]
    for index in range(12):
        rows+=[dict(run_id='rows',record=dict(url=f'https://example.org/a{index}',http_status=200),captures=[body()]),
            dict(run_id='rows',record=[dict(url=f'https://example.org/b{index}-{item}',status_code=404)
                for item in range(3)],captures=[]),
            dict(run_id='rows',record=dict(url=f'https://example.org/c{index}',http_status=503),captures=[body()])]
    source=receipt_files(tmp_path/'input',rows,'receipts/documents/2026-10-28/batch-rows.jsonl.gz')
    staged=[]
    for batch_rows in (2,8192):
        stage=capture_staging.stage_captures(source,engine=engine(tmp_path/str(batch_rows),batch_rows),
            work=tmp_path/str(batch_rows)/'stage')
        staged.append([(stage/name).read_bytes() for name in ('capture-evidence.parquet','captures.parquet')])
    assert staged[0]==staged[1]
    assert pq.read_table(tmp_path/'2/stage/captures.parquet').num_rows==12*5
    assert json.loads((tmp_path/'8192/stage-limits/limits.json').read_text())['batch_rows']==capture_staging.STAGE_BATCH_ROWS
    assert not (tmp_path/'2/stage-limits').exists()
