"""A dead worker cannot finalize itself; the next worker must not clobber a new run."""
import importlib.util
from io import BytesIO
import json
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

spec = importlib.util.spec_from_file_location('finalizer', Path(__file__).parents[1] / 'scripts/finalize-raw-source.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class Client:
    def __init__(self, state):
        self.state, self.writes = state, []
    def get_object(self, **kwargs):
        return {'Body': BytesIO(json.dumps(self.state).encode()), 'ETag': 'original'}
    def put_object(self, **kwargs):
        self.writes.append(kwargs)

@pytest.mark.parametrize('conclusion,status', [('failure', 'failed'), ('cancelled', 'cancelled'), ('success', 'completed')])
def test_finalize_preserves_last_counts_and_records_actual_job_result(conclusion, status):
    client = Client(dict(status='running', github_run_id='1', github_run_attempt='2',
                        stage='associate_source_metadata', completed=457000, heartbeat_expires_at='old'))
    assert module.finalize(client, 'bucket', '1', '2', conclusion) == status
    write, = client.writes
    assert write['IfMatch'] == 'original'
    result = json.loads(write['Body'])
    assert result['completed'] == 457000 and result['stage'] == 'associate_source_metadata'
    assert result['github_job_result'] == conclusion and result['heartbeat_expires_at'] is None

@pytest.mark.parametrize('run,attempt', [('2', '1'), ('1', '3')])
def test_finalizer_never_overwrites_new_run_or_rerun(run, attempt):
    client = Client(dict(status='running', github_run_id=run, github_run_attempt=attempt))
    assert module.finalize(client, 'bucket', '1', '2', 'failure') == 'different-run'
    assert client.writes == []

def test_concurrent_heartbeat_rejects_stale_finalizer():
    client = Client(dict(status='running', github_run_id='1', github_run_attempt='2'))
    def changed(**kwargs):
        raise ClientError({'Error': {'Code': 'PreconditionFailed'}}, 'PutObject')
    client.put_object = changed
    assert module.finalize(client, 'bucket', '1', '2', 'failure') == 'superseded'

def test_published_catalog_stays_completed_if_later_workflow_cleanup_fails():
    client = Client(dict(status='completed', github_run_id='1', github_run_attempt='2'))
    assert module.finalize(client, 'bucket', '1', '2', 'failure') == 'completed'
    assert json.loads(client.writes[0]['Body'])['github_job_result'] == 'failure'
