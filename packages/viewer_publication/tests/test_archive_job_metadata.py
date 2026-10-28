"""Native metadata queries retain evidence without becoming zero-count guards."""
import json
import os
from pathlib import Path

from docspec_client.client import NativeDatasets


def test_metadata_rows_do_not_change_release_bytes_or_weaken_guards(tmp_path):
    from viewer_publication.archive_release import build_fixture_release
    from viewer_publication.archive_format import _execute
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    fixture=Path(__file__).parents[3]/'model/fixtures/hand-release.json'
    original=build_fixture_release(fixture,output=tmp_path/'original',scratch=tmp_path/'first',engine=engine)
    job=json.loads((tmp_path/'first/job.json').read_text())
    prefix=job['steps'][:next(i for i,s in enumerate(job['steps']) if s['name']=='ordered')]
    scratch=tmp_path/'second';scratch.mkdir()
    result=_execute(job['inputs'],prefix,output=tmp_path/'repeated',scratch=scratch,engine=engine,
        origin=original['origin'],metadata_queries=[dict(name='input_receipts',sql="SELECT 'receipts/fixture.jsonl.gz' AS receipt_key")])
    assert result==original
    reports={q['name']:q['data'] for q in json.loads((scratch/'result.json').read_text())['queries']}
    assert reports['input_receipts']==[dict(receipt_key='receipts/fixture.jsonl.gz')]
    assert reports['invariants'] and all(type(v) is int and v==0 for v in reports['invariants'][0].values())
    for file in original['files']:
        assert (tmp_path/'original'/file['name']).read_bytes()==(tmp_path/'repeated'/file['name']).read_bytes()
