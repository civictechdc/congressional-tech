"""D5 owner policy disables managed activation without observing remote state."""
import ast
import inspect
import json

import pytest

ACCOUNT='a'*32
BUCKET='archive-fixture'
POLICY={'compaction':{'state':'disabled','target_size_mb':'128'},
        'snapshot_expiration':{'state':'disabled','max_snapshot_age':'30d','min_snapshots_to_keep':5}}
URL=f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/basin-catalog/{BUCKET}/maintenance-configs'
REPLACEMENT='congress_api.lake.maintenance.rebuild_generation'
REFUSAL='Managed Basin maintenance is disabled by local project policy'


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


def result(policy):
    return dict(success=True,result=dict(credential_status='present',maintenance_config=policy))


def test_plan_reports_only_local_policy_without_contacting_client():
    from congress_api.retention.basin_maintenance import configure
    client=Client()
    plan=configure(ACCOUNT,BUCKET,session=client)
    assert plan==dict(status='disabled_by_local_policy',remote_state='not_observed',
        endpoint=URL,policy=POLICY,replacement=REPLACEMENT)
    assert client.calls==[]


@pytest.mark.parametrize('replies',[
    [Reply(result(POLICY))],
    [Reply(result({'compaction':{'state':'enabled'}}))],
    [Reply(dict(success=False,errors=[dict(message='synthetic-secret')]))],
    [Reply(dict(success=True,result={}),status=403)],
    [RuntimeError('synthetic-secret')],
    [],
])
def test_execute_refuses_every_client_state_before_any_request(replies):
    from congress_api.retention.basin_maintenance import configure,MaintenanceError
    client=Client(*replies)
    with pytest.raises(MaintenanceError,match=REFUSAL) as error:
        configure(ACCOUNT,BUCKET,execute=True,session=client)
    assert client.calls==[] and 'synthetic-secret' not in str(error.value)


def test_execute_requires_no_client_or_client_attribute_access():
    from congress_api.retention.basin_maintenance import configure,MaintenanceError
    class InaccessibleClient:
        def __getattribute__(self,name):raise AssertionError('Client must not be inspected')
    for client in (None,InaccessibleClient()):
        with pytest.raises(MaintenanceError,match=REFUSAL):
            configure(ACCOUNT,BUCKET,execute=True,session=client)


@pytest.mark.parametrize('account,bucket',[('',BUCKET),(ACCOUNT,''),(ACCOUNT,'../wrong'),(None,BUCKET)])
@pytest.mark.parametrize('execute',[False,True])
def test_explicit_account_and_bucket_validation_is_preserved(account,bucket,execute):
    from congress_api.retention.basin_maintenance import configure
    client=Client()
    with pytest.raises(ValueError,match='Explicit Cloudflare account ID and bucket name'):
        configure(account,bucket,execute=execute,session=client)
    assert client.calls==[]


def test_cli_defaults_to_local_policy_without_a_credential(capsys):
    from congress_api.cli.basin_maintenance import main
    assert main(['--account-id',ACCOUNT,'--bucket',BUCKET,'--token-env','NO_SUCH_D5_CREDENTIAL'])==0
    assert json.loads(capsys.readouterr().out)==dict(status='disabled_by_local_policy',
        remote_state='not_observed',endpoint=URL,policy=POLICY,replacement=REPLACEMENT)


def test_cli_execute_refuses_without_reading_token_or_creating_http_client(capsys):
    from congress_api.cli import basin_maintenance
    # This retired CLI needs no environment or transport dependency at all.
    # Check the dependency boundary as well as its observable refusal.
    imports={node.name for node in ast.walk(ast.parse(inspect.getsource(basin_maintenance)))
        if isinstance(node,ast.alias)}
    assert not ({'os','requests'} & imports)
    with pytest.raises(SystemExit) as error:
        basin_maintenance.main(['--account-id',ACCOUNT,'--bucket',BUCKET,
            '--execute','--token-env','NO_SUCH_D5_CREDENTIAL'])
    assert error.value.code==2
    captured=capsys.readouterr()
    assert REFUSAL in captured.err and captured.out==''
