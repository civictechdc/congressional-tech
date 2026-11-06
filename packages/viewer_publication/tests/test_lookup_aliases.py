"""Serialization fallback preserves exact keys, editions and meaningful URL bytes."""
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

import pyarrow.parquet as pq
import pytest

from congress_api.retention.provenance import json_input, run_job
from docspec_client.client import NativeDatasets
from viewer_publication.archive_format import _lookup_steps
from viewer_publication.lookup_aliases import ALIAS_PREFIX

ROOT = Path(__file__).parents[3]


@pytest.fixture
def engine():
    return NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])


def key(value):
    return sha256(value.encode()).digest()[:8]


def test_all_percent_octets_keep_their_value_and_only_change_triplet_case(engine, tmp_path):
    # Each byte has two source spellings and two editions; no percent decoding.
    source = json_input(tmp_path, 'input_urls', [dict(list_row=2*i+j,
        url=f'https://fixture.test/Case/%{i:02x}' if j == 0 else f'https://fixture.test/Case/%{i:02X}')
        for i in range(256) for j in range(2)], list_row='Int32', url='Utf8')
    result = run_job(tmp_path, engine, inputs=[source], steps=_lookup_steps('input_urls'), outputs=[],
        queries=[dict(name='aliases', sql="SELECT encode(lookup_key,'hex') AS key,list_row FROM lookup_alias_keys_full ORDER BY list_row")])
    assert result['aliases'] == [dict(key=key(ALIAS_PREFIX+f'fixture.test/Case/%{i:02X}').hex(),list_row=2*i+j)
        for i in range(256) for j in range(2)]


def control_fixture(tmp_path):
    # Two saved bodies share a serialization alias, while each exact URL owns one.
    urls = [
        'https://fixture.test/Report%2f A.pdf?x=%3b',
        'https://fixture.test/Report%2F%20A.pdf?x=%3B',
        'https://fixture.test/reserved%2Fpart.pdf',
        'https://fixture.test/reserved/part.pdf',
        'https://fixture.test/a/../Dot%20Path.pdf',
        'https://fixture.test/Query%20Path.pdf?value=one+two&x=%26',
        'https://web.archive.org/web/20200101120000id_/https://fixture.test/Report%20A.pdf',
        'https://fixture.test/Report%20A.pdf',
        'https://fixture.test/download/Report%20A&download=1',
        'https://fixture.test/Trailing%20.pdf%20',
        'https://fixture.test/invalid%2g%f%20.pdf',
    ]
    value=dict(documents=[dict(name=str(i), filename=f'{i:02}.pdf',title=f'Edition {i}',body_byte=100+i,
        format='pdf', hidden=i==0, first_captured=f'2020-01-{i+1:02}', source_url=url)
        for i,url in enumerate(urls)],meetings=[])
    path=tmp_path/'fixture.json';path.write_text(json.dumps(value))
    return path,urls


def test_native_index_through_actual_reader_preserves_editions_and_negative_controls(engine, tmp_path):
    from viewer_publication.archive_fixture import build_fixture_release
    fixture,urls=control_fixture(tmp_path)
    release=tmp_path/'release'
    manifest=build_fixture_release(fixture,output=release,scratch=tmp_path/'job',engine=engine)
    index={}
    for row in pq.read_table(release/'urls.parquet').to_pylist():
        index.setdefault(row['lookup_key'],[]).append(row['list_row'])
    for i,url in enumerate(urls):
        assert index[key('lookup:'+url.removeprefix('https://'))] == [i]
    assert index[key(ALIAS_PREFIX+'fixture.test/Report%2F%20A.pdf?x=%3B')] == [0,1]
    # No document, body, source spelling or public link has been collapsed.
    assert pq.read_table(release/'list.parquet').num_rows == len(urls)
    assert len({row['saved_body'] for row in pq.read_table(release/'detail.parquet').to_pylist()}) == len(urls)
    assert [row['url'] for row in pq.read_table(release/'sources.parquet').to_pylist()] == urls
    cases=[dict(kind='exact',url=url,expected_rows=[i],check_page=True) for i,url in enumerate(urls)]
    cases.append(dict(kind='exact_filtered',url=urls[0],expected_rows=[0],check_page=True,
        query=dict(includeHidden=False),expected_page_rows=[]))
    cases += [dict(kind='alias',url=url,expected_rows=rows,check_page=True) for url,rows in [
        ('https://fixture.test/Report%2f%20A.pdf?x=%3b',[0,1]),
        ('https://fixture.test/reserved%2fpart.pdf',[2]),
        ('https://fixture.test/a/../Dot Path.pdf',[4]),
        ('https://fixture.test/Query Path.pdf?value=one+two&x=%26',[5]),
        ('https://web.archive.org/web/20200101120000id_/https://fixture.test/Report A.pdf',[6]),
        ('https://fixture.test/invalid%2g%f .pdf',[10]),
    ]]
    cases += [dict(kind='negative',url=url,expected_rows=[]) for url in [
        'https://fixture.test/report%2f%20A.pdf?x=%3b',
        'https://fixture.test/Report%2f%20A.pdf?x=%3a',
        'https://fixture.test/Dot Path.pdf',
        'https://fixture.test/Query Path.pdf?value=one%20two&x=%26',
        'https://fixture.test/Query Path.pdf?x=%26&value=one+two',
        'https://fixture.test/Query Path.pdf?value=one+two&x=&',
        'https://web.archive.org/web/20210101120000id_/https://fixture.test/Report A.pdf',
        'https://fixture.test/download/Report%20A?download=1',
        'https://fixture.test/Trailing%20.pdf',
    ]]
    selection=tmp_path/'selection.json';selection.write_text(json.dumps(dict(manifest=manifest,
        files={f['name']:str(release/f['name']) for f in manifest['files']})))
    checks=tmp_path/'cases.json';checks.write_text(json.dumps(cases))
    for command in [
        ['node',str(ROOT/'apps/site/scripts/verify-url-lookups.mjs'),str(selection),str(checks)],
        ['node',str(ROOT/'apps/site/scripts/canary-archive-local.mjs'),'--release',str(release),
            '--lookup-cases',str(checks),'--check-saved','false'],
    ]:
        result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=60)
        assert result.returncode==0,result.stdout+result.stderr


@pytest.mark.parametrize('collision', ['namespace', 'alias_only'])
def test_alias_hash_collision_refuses_publication(engine, tmp_path, monkeypatch, collision):
    from viewer_publication import archive_format
    from viewer_publication.archive_fixture import build_fixture_release
    fixture,urls=control_fixture(tmp_path)
    original=archive_format._hash_key
    # Plant each new kind of collision without creating an exact/exact collision.
    target=key('lookup:'+urls[0].removeprefix('https://')).hex() if collision=='namespace' else 'f0'*8
    def planted(expression, prefix=''):
        normal=original(expression,prefix)
        if prefix!=ALIAS_PREFIX:
            return normal
        forced=archive_format._binary("'"+target+"'",8)
        if collision=='namespace':
            return f"CASE WHEN {expression}='fixture.test/Report%2F%20A.pdf?x=%3B' THEN {forced} ELSE {normal} END"
        return forced
    monkeypatch.setattr(archive_format,'_hash_key',planted)
    with pytest.raises(ValueError,match='Release key invariant failed'):
        build_fixture_release(fixture,output=tmp_path/'release',scratch=tmp_path/'job',engine=engine)
    assert not (tmp_path/'release/manifest.json').exists()
    reports=json.loads((tmp_path/'job/result.json').read_text())['queries']
    invariants=next(query['data'][0] for query in reports if query['name']=='invariants')
    assert invariants['lookup_collisions']==0
    assert (invariants['lookup_alias_collisions']>0)==(collision=='alias_only')
    assert (invariants['lookup_namespace_collisions']>0)==(collision=='namespace')
