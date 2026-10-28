"""A native job can own a fresh nested work directory."""
import json

from congress_api.retention.provenance import run_job


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
