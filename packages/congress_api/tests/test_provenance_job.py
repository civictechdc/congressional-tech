"""A native job can own a fresh nested work directory, and keeps what the engine said beside its spec."""
import json
import os

import pytest

from congress_api.retention.provenance import field, run_job


def test_native_job_creates_a_fresh_work_root_before_writing_its_spec(tmp_path):
    root=tmp_path/'fresh'/'nested'
    class Engine:
        def run_job(self,path):
            assert path==root/'job.json' and path.is_file()
            spec=json.loads(path.read_text())
            assert spec['scratch']==str(root/'native')
            assert spec['queries']==[dict(name='one',sql='SELECT 1 AS n')]
            return dict(queries=[dict(name='one',data=[dict(n=1)])])
    result=run_job(root,Engine(),inputs=[],steps=[],outputs=[],queries=[dict(name='one',sql='SELECT 1 AS n')])
    assert result==dict(one=[dict(n=1)])
    assert json.loads((root/'result.json').read_text())['queries'][0]['data']==[dict(n=1)]
    assert sorted(p.name for p in root.iterdir())==['job.json','result.json']  # a one-argument engine is asked for no log


STEPS=[dict(name='one',sql='SELECT 1 AS x')]


def native():
    from docspec_client.client import NativeDatasets
    return NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])


def test_a_passing_job_leaves_its_step_events_beside_its_spec(tmp_path):
    from docspec_client.models import metric_events
    assert run_job(tmp_path/'job',native(),inputs=[],steps=STEPS,outputs=[],queries=[dict(name='q',sql='SELECT x FROM one')])==dict(q=[dict(x=1)])
    events=list(metric_events(tmp_path/'job/engine.log'))
    assert [(e['event'],e.get('name')) for e in events if e['event']=='step']==[('step','one'),('step','query:q')]
    assert sorted(p.name for p in (tmp_path/'job').iterdir() if p.is_file())==['engine.log','job.json','result.json']


def test_a_failing_job_says_what_failed_first_and_keeps_the_whole_stream(tmp_path):
    """The failed nightly 20261110T111252Z in small: a JSON-lines source that cannot be opened, after work that logged metrics."""
    from docspec_client.models import DocSpecFailure
    absent=dict(name='absent',kind='json_lines',files=[dict(key='absent',path=str(tmp_path/'absent.jsonl.gz'))],
        schema=dict(fields=[field('x','Int64')],metadata={}))
    with pytest.raises(DocSpecFailure,match='source open failed') as raised:
        run_job(tmp_path/'job',native(),inputs=[absent],steps=STEPS,outputs=[],
            queries=[dict(name='before',sql='SELECT x FROM one'),dict(name='q',sql='SELECT count(*) AS n FROM absent')])
    error=raised.value
    assert str(error).splitlines()[0]=='query: Execution error: absent line 1: source open failed'
    assert '[docspec-metric]' not in str(error) and 'Caused by:' in str(error)
    assert error.stderr.startswith('[docspec-metric] ') and error.stderr==(tmp_path/'job/engine.log').read_text()
    assert error.code=='query' and error.completed['queries'][0]['name']=='before'
