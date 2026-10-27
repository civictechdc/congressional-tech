"""D5 is one explicit catalog policy, tested without a provider connection."""
from copy import deepcopy
import json

import pytest

ACCOUNT='a'*32
BUCKET='archive-fixture'
POLICY={'compaction':{'state':'enabled','target_size_mb':'128'},
        'snapshot_expiration':{'state':'enabled','max_snapshot_age':'30d','min_snapshots_to_keep':5}}
URL=f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/basin-catalog/{BUCKET}/maintenance-configs'


def result(policy,credential='present'):
    return dict(success=True,result=dict(credential_status=credential,maintenance_config=policy))


class Reply:
    def __init__(self,value,status=200):self.value,self.status_code=value,status
    def json(self):return self.value


class Client:
    def __init__(self,*replies):self.replies=list(replies);self.calls=[]
    def request(self,method,url,**kwargs):
        self.calls.append((method,url,kwargs))
        value=self.replies.pop(0)
        if isinstance(value,Exception):raise value
        return value


def test_plan_uses_exact_policy_and_never_calls_the_client():
    from congress_api.retention.basin_maintenance import configure
    client=Client()
    plan=configure(ACCOUNT,BUCKET,session=client)
    assert plan==dict(status='planned',endpoint=URL,policy=POLICY)
    assert client.calls==[]


def test_matching_current_policy_is_one_metadata_read_and_no_write():
    from congress_api.retention.basin_maintenance import configure
    current=deepcopy(POLICY);current['interval']='1h'
    client=Client(Reply(result(current)))
    assert configure(ACCOUNT,BUCKET,execute=True,session=client)['status']=='unchanged'
    assert [(m,u) for m,u,_ in client.calls]==[('GET',URL)]


def test_changed_policy_writes_once_and_checks_effective_metadata():
    from congress_api.retention.basin_maintenance import configure
    current=deepcopy(POLICY);current['compaction']['state']='disabled'
    client=Client(Reply(result(current)),Reply(dict(success=True,result=POLICY)),Reply(result(POLICY)))
    assert configure(ACCOUNT,BUCKET,execute=True,session=client)==dict(status='updated',endpoint=URL,policy=POLICY)
    assert [m for m,_,_ in client.calls]==['GET','POST','GET']
    assert client.calls[1][2]['json']==POLICY
    assert all(c[1]==URL and c[2]['allow_redirects'] is False and c[2]['timeout']==30 for c in client.calls)


@pytest.mark.parametrize('reply',[Reply(result(POLICY,'absent')),
    Reply(dict(success=False,errors=[dict(message='synthetic-secret')])),Reply(dict(success=True,result={}),status=403)])
def test_absent_service_credential_or_api_failure_refuses_before_write(reply):
    from congress_api.retention.basin_maintenance import configure,MaintenanceError
    client=Client(reply)
    with pytest.raises(MaintenanceError) as error:configure(ACCOUNT,BUCKET,execute=True,session=client)
    assert len(client.calls)==1 and 'synthetic-secret' not in str(error.value)


def test_mismatched_readback_is_not_reported_as_enabled():
    from congress_api.retention.basin_maintenance import configure,MaintenanceError
    disabled=deepcopy(POLICY);disabled['snapshot_expiration']['state']='disabled'
    client=Client(Reply(result(disabled)),Reply(dict(success=True,result=POLICY)),Reply(result(disabled)))
    with pytest.raises(MaintenanceError,match='readback'):
        configure(ACCOUNT,BUCKET,execute=True,session=client)
    assert [m for m,_,_ in client.calls]==['GET','POST','GET']


def test_uncertain_write_is_not_retried_or_disclosed():
    import requests
    from congress_api.retention.basin_maintenance import configure,MaintenanceError
    client=Client(Reply(result({})),requests.ConnectionError('synthetic-secret'))
    with pytest.raises(MaintenanceError) as error:configure(ACCOUNT,BUCKET,execute=True,session=client)
    assert 'synthetic-secret' not in str(error.value)
    assert [m for m,_,_ in client.calls]==['GET','POST']


def test_cli_defaults_to_plan_without_a_credential(capsys):
    from congress_api.cli.basin_maintenance import main
    assert main(['--account-id',ACCOUNT,'--bucket',BUCKET,'--token-env','NO_SUCH_D5_CREDENTIAL'])==0
    assert json.loads(capsys.readouterr().out)==dict(status='planned',endpoint=URL,policy=POLICY)
