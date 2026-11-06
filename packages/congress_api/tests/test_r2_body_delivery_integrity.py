"""Scoped provider planning and exact ordinary-GET archive delivery proof."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import gzip,json

import pytest

from congress_api.retention.r2_edge_rules import (body_integrity_configuration,load_edge_config,plan_body_integrity_rule)
from viewer_publication.apply_r2_edge_rules import verify_body_delivery

FIXTURE=Path(__file__).parent/'fixtures/r2-edge-configuration-provider.json'
ZONE='d'*32


def observed():return json.loads(FIXTURE.read_bytes())


def apply_single_operation(snapshot,operation):
    """A provider-shaped test oracle: only one per-rule endpoint may change."""
    result=deepcopy(snapshot);rules=result['data']['result']['rules']
    assert operation['method'] in ('POST','PATCH')
    assert '/rules/' in operation['path'] or operation['path'].endswith('/rules')
    value=deepcopy(operation['body']);after=value.pop('position',{}).get('after')
    if operation['method']=='PATCH':
        key=operation['path'].rsplit('/',1)[1]
        matches=[r for r in rules if r['id']==key];assert len(matches)==1
        target=matches[0];rules.remove(target);target.update(value)
    else:
        assert operation['method']=='POST'
        target=dict(value,id='e'*32)
    index=next(i for i,r in enumerate(rules) if r['id']==after)+1 if after else len(rules)
    rules.insert(index,target)
    return result


def test_provider_append_preserves_every_unrelated_rule_and_order():
    before=observed();plan=plan_body_integrity_rule(before,ZONE)
    assert len(plan['operations'])==1
    operation=plan['operations'][0]
    assert operation['method']=='POST' and operation['path']==f'/zones/{ZONE}/rulesets/'+('a'*32)+'/rules'
    assert operation['body']['position']=={'after':'c'*32}
    after=apply_single_operation(before,operation)
    assert after['data']['result']['rules'][:-1]==before['data']['result']['rules']
    assert plan['preserve_unrelated_rule_ids']==['b'*32,'c'*32]
    assert plan_body_integrity_rule(after,ZONE)['operations']==[]


def test_patch_changes_only_verified_owned_id_and_moves_it_after_unrelated_rules():
    before=observed();desired=body_integrity_configuration()['rule']
    existing=dict(desired,id='e'*32,enabled=False)
    before['data']['result']['rules'].insert(1,existing)
    plan=plan_body_integrity_rule(before,ZONE);operation=plan['operations'][0]
    assert operation['method']=='PATCH' and operation['path'].endswith('/rules/'+('e'*32))
    after=apply_single_operation(before,operation)['data']['result']['rules']
    assert [r for r in after if r['id']!='e'*32]==observed()['data']['result']['rules']
    assert after[-1]['id']=='e'*32 and after[-1]['enabled'] is True
    assert after[-1]['action_parameters']=={'email_obfuscation':False}


@pytest.mark.parametrize('status',[403,404,500])
def test_unknown_provider_state_is_never_treated_as_empty(status):
    value=observed();value['status']=status
    with pytest.raises(ValueError,match='unknown state'):plan_body_integrity_rule(value,ZONE)


def test_wrong_phase_duplicates_and_other_owned_settings_refuse():
    wrong=observed();wrong['data']['result']['phase']='http_response_headers_transform'
    with pytest.raises(ValueError,match='entrypoint'):plan_body_integrity_rule(wrong,ZONE)
    duplicate=observed();duplicate['data']['result']['rules'][1]['ref']=duplicate['data']['result']['rules'][0]['ref']
    with pytest.raises(ValueError,match='duplicate'):plan_body_integrity_rule(duplicate,ZONE)
    extra=observed();extra['data']['result']['rules'].append(dict(body_integrity_configuration()['rule'],id='e'*32,
        action_parameters=dict(email_obfuscation=False,bic=False)))
    with pytest.raises(ValueError,match='other settings'):plan_body_integrity_rule(extra,ZONE)


@pytest.mark.parametrize('change',[
    lambda r:r.update(expression='starts_with(http.request.uri.path, "/bodies/sha256/")'),
    lambda r:r.update(expression='(http.host eq "congressional-data.spicygov.ai") and starts_with(http.request.uri.path, "/")'),
    lambda r:r.update(enabled=False),
    lambda r:r.update(action_parameters={'email_obfuscation':0}),
    lambda r:r.update(action_parameters={'email_obfuscation':False,'rocket_loader':False}),
])
def test_declaration_rejects_broad_scope_and_extra_settings(change):
    config=load_edge_config();change(config['configuration_rules'][0]['rule'])
    with pytest.raises(ValueError,match='exact host/body prefix'):body_integrity_configuration(config)


class Response(BytesIO):
    def __init__(self,data,url,headers=None,status=200):
        super().__init__(data);self.url=url;self.headers=headers or {};self.status=status
    def geturl(self):return self.url


def probe_config(payload,maximum=65536):
    config=load_edge_config();digest=sha256(payload).hexdigest()
    config['configuration_rules'][0]['integrity_probe']=dict(path=f'/bodies/sha256/{digest[:2]}/{digest}',
        decoded_sha256=digest,decoded_bytes=len(payload),max_bytes=maximum)
    return config


def opener(payload,requests,*,status=200):
    def read(request,timeout):
        requests.append(request)
        compressed=request.get_header('Accept-encoding')=='gzip'
        return Response(gzip.compress(payload,mtime=0) if compressed else payload,request.full_url,
            {'Content-Encoding':'gzip'} if compressed else {},status)
    return read


def test_plain_and_transport_gzip_verify_the_same_original_bytes_without_workarounds():
    original=b'<html><a href="mailto:?subject=Hearing">Share</a></html>'
    requests=[];value=verify_body_delivery(config=probe_config(original),http_open=opener(original,requests))
    assert value['status']=='verified' and len(requests)==4
    assert {check['decoded_sha256'] for check in value['checks']}=={sha256(original).hexdigest()}
    assert all(req.get_method()=='GET' and not req.has_header('Range') and not req.has_header('Cache-control') for req in requests)
    assert {req.get_header('Accept-encoding') for req in requests}=={'gzip','identity'}


def test_email_rewrite_or_partial_response_fails_even_when_it_remains_readable_html():
    original=b'<html><a href="mailto:?subject=Hearing">Share</a></html>'
    changed=original.replace(b'mailto:?subject=Hearing',b'/cdn-cgi/l/email-protection#abcdef')+b'<script src="email-decode.min.js"></script>'
    value=verify_body_delivery(config=probe_config(original),repeats=1,http_open=opener(changed,[]))
    assert value['status']=='failed' and all(not c['passed'] for c in value['checks'])
    assert all(c['decoded_sha256']==sha256(changed).hexdigest() for c in value['checks'])
    partial=verify_body_delivery(config=probe_config(original),repeats=1,http_open=opener(original,[],status=206))
    assert partial['status']=='failed' and all('ordinary 200' in c['reason'] for c in partial['checks'])


def test_gzip_expansion_and_redirect_identity_are_bounded():
    expected=b'original'
    def bomb(request,timeout):return Response(gzip.compress(b'x'*4096,mtime=0),request.full_url,{'Content-Encoding':'gzip'})
    result=verify_body_delivery(config=probe_config(expected,1024),repeats=1,http_open=bomb)
    assert result['status']=='failed' and all('decoded limit' in c['reason'] for c in result['checks'])
    def redirected(request,timeout):return Response(expected,'https://another.example/body')
    assert verify_body_delivery(config=probe_config(expected),repeats=1,http_open=redirected)['status']=='failed'


def test_description_is_not_authority_to_patch_another_rule():
    value=observed()
    value['data']['result']['rules'].append(dict(body_integrity_configuration()['rule'],id='e'*32,
        ref='another_owner',expression='http.host eq "another.spicygov.ai"'))
    with pytest.raises(ValueError,match='manual ownership review'):
        plan_body_integrity_rule(value,ZONE)


def test_existing_probe_evidence_is_preserved_before_any_network_read(tmp_path,monkeypatch):
    import viewer_publication.apply_r2_edge_rules as command
    output=tmp_path/'before.json';output.write_bytes(b'prior failed observation')
    def unexpected(**kwargs):raise AssertionError('Existing evidence must refuse before a fresh read')
    monkeypatch.setattr(command,'verify_body_delivery',unexpected)
    with pytest.raises(ValueError,match='Preserve existing integrity evidence'):
        command.main(['verify-body','--out',str(output)])
    assert output.read_bytes()==b'prior failed observation'


def test_corrupt_deflate_is_retained_as_failed_cli_evidence(tmp_path,monkeypatch):
    import viewer_publication.apply_r2_edge_rules as command
    original_verify=command.verify_body_delivery
    wire=bytes.fromhex('1f8b0800000000000203ffffffffff0000000000000000')
    def corrupt(request,timeout):
        return Response(wire,request.full_url,{'Content-Encoding':'gzip'})
    monkeypatch.setattr(command,'verify_body_delivery',lambda **kwargs:original_verify(
        config=probe_config(b'original archived HTML'),repeats=1,http_open=corrupt))
    output=tmp_path/'corrupt-delivery.json'
    assert command.main(['verify-body','--out',str(output)])==1
    result=json.loads(output.read_text())
    assert result['status']=='failed' and len(result['checks'])==2
    assert all(not check['passed'] and 'invalid block type' in check['reason'] for check in result['checks'])
