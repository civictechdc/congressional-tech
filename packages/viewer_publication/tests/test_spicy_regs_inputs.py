import hashlib
import io
import json

import pytest

from viewer_publication.spicy_regs_inputs import fetch_pinned

SOURCE='https://spicy.example'
PATH='generations/members/abc/members.parquet'


def _manifest(tmp_path,body,*,path=PATH,source=SOURCE):
    value=dict(version=1,source=source,generations=dict(members='abc'),
        tables=dict(spicy_members=dict(family='members',key='members.parquet',path=path,rows=1,
            sha256=hashlib.sha256(body).hexdigest(),size=len(body))))
    manifest=tmp_path/'spicy-regs.json'
    manifest.write_text(json.dumps(value))
    data=manifest.read_bytes()
    return dict(path=str(manifest),sha256=hashlib.sha256(data).hexdigest(),size=len(data))


def _opener(served,calls):
    def opener(url):
        calls.append(url)
        return io.BytesIO(served)
    return opener


def test_fetches_each_pinned_table_beside_the_manifest(tmp_path):
    calls=[]
    result=fetch_pinned(_manifest(tmp_path,b'parquet'),opener=_opener(b'parquet',calls))
    assert calls==[SOURCE+'/'+PATH]
    assert (tmp_path/PATH).read_bytes()==b'parquet'
    assert result['tables']=={'spicy_members':'fetched'}


def test_present_pinned_bytes_are_not_fetched_again(tmp_path):
    pin=_manifest(tmp_path,b'parquet')
    (tmp_path/PATH).parent.mkdir(parents=True)
    (tmp_path/PATH).write_bytes(b'parquet')
    calls=[]
    assert fetch_pinned(pin,opener=_opener(b'unused',calls))['tables']=={'spicy_members':'present'}
    assert calls==[]


@pytest.mark.parametrize('served',[b'parqueX',b'parquet-and-more',b'parque'])
def test_refuses_bytes_that_differ_from_the_pin_and_keeps_nothing(tmp_path,served):
    pin=_manifest(tmp_path,b'parquet')
    with pytest.raises(ValueError,match='does not match its pin'):
        fetch_pinned(pin,opener=_opener(served,[]))
    assert not (tmp_path/PATH).exists()
    assert not list((tmp_path/'generations').rglob('*.partial'))


def test_replaces_a_present_file_holding_other_bytes(tmp_path):
    pin=_manifest(tmp_path,b'parquet')
    (tmp_path/PATH).parent.mkdir(parents=True)
    (tmp_path/PATH).write_bytes(b'stale')
    assert fetch_pinned(pin,opener=_opener(b'parquet',[]))['tables']=={'spicy_members':'fetched'}
    assert (tmp_path/PATH).read_bytes()==b'parquet'


def test_refuses_a_manifest_that_differs_from_its_pin(tmp_path):
    pin=_manifest(tmp_path,b'parquet')
    calls=[]
    with pytest.raises(ValueError,match='manifest does not match'):
        fetch_pinned(dict(pin,sha256='0'*64),opener=_opener(b'parquet',calls))
    assert calls==[]


@pytest.mark.parametrize('path',['../escape.parquet','/abs/members.parquet'])
def test_refuses_a_table_path_outside_the_manifest(tmp_path,path):
    with pytest.raises(ValueError,match='stay under its manifest'):
        fetch_pinned(_manifest(tmp_path,b'parquet',path=path),opener=_opener(b'parquet',[]))


def test_refuses_a_non_https_source(tmp_path):
    with pytest.raises(ValueError,match='https'):
        fetch_pinned(_manifest(tmp_path,b'parquet',source='http://spicy.example'),opener=_opener(b'parquet',[]))


def test_the_shipped_pin_names_the_shipped_manifest():
    # 2026-11-09: a re-pinned spicy-regs.json shipped without its publish-model.json pin, and the
    # nightly refused at its spicy-regs step. Every test above uses a made-up manifest, so check the real one.
    from pathlib import Path
    jobs=Path(__file__).resolve().parents[3]/'model/jobs'
    pin=json.loads((jobs/'publish-model.json').read_text())['spicy_regs']
    data=(jobs/pin['path']).read_bytes()
    assert (hashlib.sha256(data).hexdigest(),len(data))==(pin['sha256'],pin['size'])
