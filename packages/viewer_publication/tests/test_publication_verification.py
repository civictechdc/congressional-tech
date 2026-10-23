"""Read-only receipts retain independent pending gates and exact document IDs."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import pytest
import pyarrow as pa
import pyarrow.parquet as pq

import viewer_publication.verify as verification


def observed(tmp_path):
    path=tmp_path/'documents.parquet'
    table=pa.table({'document_id':['a'*64], 'document_kind':[['bill']], 'document_family':[['legislation']], 'document_kind_source':[['filename']]}).replace_schema_metadata({b'catalog_id':b'catalog'})
    pq.write_table(table,path);raw=path.read_bytes()
    item=dict(path='documents.parquet',bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),rows=1)
    source={'catalog_id':'catalog','generation':'generation'}
    v=dict(pointer={'catalog_id':'catalog','source_manifest':source},manifest={'info':{'catalog_id':'catalog'},'source_manifest':source,'files':{'documents':item}},manifest_url='https://data.test/release/manifest.json',
        loader={'info':{'reviewed_search':True,'review_sha256':'pin'},'rows':[{'document_id':'a'*64,'baseline':{'document_kind':['other'],'document_family':['other'],'document_kind_source':['old']},'selected':{'document_kind':['letter']}}]},
        pages={'assets':[{'sha256':'asset'}],'runtime_execution':{'state':'passed','method':'fixture worker'}},withdrawn=[{'document_id':'a'*64,'reason':'body_changed'}])
    def read(location,**kwargs):
        assert kwargs['expected']==item and kwargs['limit']==32*1024**2
        return raw
    return source,v,read


def test_complete_verified_table_diff_uses_document_identity_and_preserves_withdrawals(tmp_path):
    source,value,read=observed(tmp_path)
    result=verification.verify(source,value,current_raw=True,read=read,raw_digest='exact',expected_raw_digest='exact')
    assert result['status']=='verified' and result['read_only']
    difference=next(item['detail'] for item in result['checks'] if item['check']=='document_category_readback')
    assert difference['maximum_batch_rows']==256
    assert difference['documents'][0]['document_id']=='a'*64
    assert difference['documents'][0]['different_from_review_baseline'] is True
    assert result['withdrawn_reasons'][0]['reason']=='body_changed'


def test_missing_runtime_or_run_pin_or_live_raw_never_claims_complete(tmp_path):
    source,value,read=observed(tmp_path)
    result=verification.verify(source,value,read=read)
    assert result['status']=='pending'
    assert {'raw_selector_freshness','raw_run_output_binding'} <= {item['check'] for item in result['checks'] if item['state']=='pending'}
    value['pages']['runtime_execution']={'state':'pending','reason':'browser unavailable'}
    result=verification.verify(source,value,current_raw=True,read=read,raw_digest='x',expected_raw_digest='x')
    assert result['status']=='pending'


def test_mismatched_selection_or_run_pin_fails_without_promoting_metadata(tmp_path):
    source,value,read=observed(tmp_path);value['pointer']['catalog_id']='other'
    result=verification.verify(source,value,current_raw=True,read=lambda *a,**kw:pytest.fail('table read after identity mismatch'),raw_digest='wrong',expected_raw_digest='expected')
    assert result['status']=='failed'
    assert any(item['check']=='raw_viewer_identity' and item['state']=='failed' for item in result['checks'])


def test_oversized_table_is_pending_before_download(tmp_path):
    _,value,_=observed(tmp_path);value['manifest']['files']['documents']['bytes']=32*1024**2+1
    result=verification.catalog_differences(value,read=lambda *a,**kw:pytest.fail('oversized table download'))
    assert result['state']=='pending'


def test_control_read_hash_and_length_are_complete_and_bounded(tmp_path):
    path=tmp_path/'control';path.write_bytes(b'complete')
    expected={'bytes':8,'sha256':hashlib.sha256(b'complete').hexdigest()}
    assert verification.control(path,limit=8,expected=expected)==b'complete'
    with pytest.raises(ValueError,match='byte budget'):verification.control(path,limit=7)
    with pytest.raises(ValueError,match='pinned'):verification.control(path,expected=dict(expected,sha256='wrong'))


def test_live_observation_uses_explicit_checkout_for_node_verifier(tmp_path, monkeypatch):
    checkout = tmp_path / 'checkout'
    descriptor = checkout / 'apps/site/document-review-publication.json'
    expected = {'fixture': 'verified'}
    def run(command, **options):
        assert command[:2] == ['fixture-node', str(checkout / 'apps/site/scripts/verify-live-publication.mjs')]
        assert command[2:8] == ['--viewer-url', 'https://viewer.test/', '--pages-url',
                                'https://pages.test/', '--review-descriptor', str(descriptor)]
        assert command[8] == '--output'
        assert options == {'check': True, 'timeout': 180, 'capture_output': True}
        Path(command[9]).write_text(json.dumps(expected))
    monkeypatch.setattr(verification.subprocess, 'run', run)
    assert verification.live_observation('https://viewer.test/', 'https://pages.test/', descriptor,
                                         root=checkout, node='fixture-node') == expected


@pytest.fixture
def native_observed(tmp_path, monkeypatch):
    from viewer_publication.filename_native import ViewerAssets, publication_basis
    from congress_api.retention.immutable_metadata import encoded
    source, value, _ = observed(tmp_path)
    assets = ViewerAssets(tmp_path / 'public')
    document = assets.put_file(tmp_path / 'documents.parquet', name='documents.parquet')
    document['rows'] = 1
    component = assets.put_node(dict(kind='component-leaf', prefix='', members={
        'a' * 64: dict(document_file=document)}))
    component.update(native_sha256='2' * 64, stats=dict(entries=1, source_rows=1))
    source_root = dict(native_sha256='1' * 64, stats=dict(rows=1))
    selected = dict(counts=dict(source_rows=1, document_rows=1),
                    dependency=dict(source_root=dict(sha256='1' * 64)), components=dict(sha256='2' * 64))
    selection = assets.put_node(selected)
    source = dict(version=2, selection=dict(key='selected.json', bytes=selection['bytes'], sha256=selection['sha256']))
    identity = dict(selected_ref=source['selection'], selector_sha256=hashlib.sha256(encoded(source)).hexdigest())
    manifest = dict(version=6, source_manifest=source, source_identity=identity, source_selection=selection,
        roots=dict(sources=source_root, components=component, browse=dict(rows=1)), requirements={}, files={},
        info=dict(catalog_id='catalog', rows=1, entries=1))
    manifest['proof'] = assets.put_node(dict(version=1, kind='viewer-proof', publication=publication_basis(manifest)))
    value.update(manifest=manifest, observations=[dict(url=value['manifest_url'], sha256='5' * 64)],
        pointer=dict(catalog_id='catalog', source_manifest=source, source_identity=identity,
        recovery=dict(sha256='3' * 64), recovery_inputs=dict(version=2, source_identity=identity, roots=manifest['roots'],
            raw_manifest_sha256=identity['selector_sha256'], viewer_manifest_sha256='5' * 64, accepted=dict(sha256='4' * 64))),
        recovery_identity=dict(source_identity=identity, sha256='3' * 64, accepted_sha256='4' * 64))
    requests = []
    def read(location, **options):
        from urllib.parse import urlsplit
        requests.append(str(location))
        return verification.control(assets.root / urlsplit(str(location)).path.lstrip('/'), **options)
    return source, value, read, requests, assets


def test_native_verification_reads_reviewed_document_partitions_by_exact_identity(native_observed):
    source, value, read, requests, _ = native_observed
    result = verification.verify(source, value, current_raw=True, read=read,
        raw_digest=value['manifest']['source_identity']['selector_sha256'],
        expected_raw_digest=value['manifest']['source_identity']['selector_sha256'])
    assert result['status'] == 'verified'
    differences = next(item['detail'] for item in result['checks'] if item['check'] == 'document_category_readback')
    assert differences['documents'][0]['catalog']['document_kind'] == ['bill']
    assert differences['documents'][0]['different_from_review_baseline'] is True
    assert len([url for url in requests if url.endswith('.parquet')]) == 1
    assert value['withdrawn'] == differences['withdrawn']


def test_native_reused_partition_keeps_its_original_catalog_metadata(native_observed):
    _, value, read, _, assets = native_observed
    from viewer_publication.filename_native import publication_basis
    value['manifest']['info']['catalog_id'] = 'new-catalog'
    value['manifest']['proof'] = assets.put_node(dict(version=1, kind='viewer-proof', publication=publication_basis(value['manifest'])))
    value['pointer']['catalog_id'] = 'new-catalog'
    result = verification.catalog_differences(value, read=read)
    assert result['state'] == 'passed'
    assert result['documents'][0]['document_id'] == 'a' * 64


@pytest.mark.parametrize('damage', ['pointer', 'selector', 'root', 'partition', 'recovery', 'accepted'])
def test_native_mixed_or_stale_identity_never_verifies(native_observed, damage):
    source, value, read, _, assets = native_observed
    if damage == 'pointer':
        value['pointer']['source_identity'] = dict(value['pointer']['source_identity'], selector_sha256='wrong')
    elif damage == 'selector':
        source = dict(source, selection=dict(source['selection'], sha256='0' * 64))
    elif damage == 'root':
        value['manifest']['roots']['components']['native_sha256'] = '0' * 64
    elif damage == 'recovery':
        value['recovery_identity']['source_identity'] = dict(value['recovery_identity']['source_identity'], selector_sha256='wrong')
    elif damage == 'accepted':
        value['recovery_identity']['accepted_sha256'] = 'wrong'
    else:
        file = next(assets.root.rglob('documents.parquet'))
        raw = file.read_bytes()
        file.write_bytes(raw[:10] + bytes([raw[10] ^ 1]) + raw[11:])
    digest = value['manifest']['source_identity']['selector_sha256']
    if damage in {'root', 'partition'}:
        with pytest.raises(ValueError, match='retained selection proof|pinned bytes/hash'):
            verification.verify(source, value, current_raw=True, read=read, raw_digest=digest, expected_raw_digest=digest)
        return
    result = verification.verify(source, value, current_raw=True, read=read, raw_digest=digest, expected_raw_digest=digest)
    assert result['status'] == 'failed'


def test_native_category_readback_keeps_finite_byte_budget(native_observed):
    _, value, read, requests, _ = native_observed
    result = verification.catalog_differences(value, max_bytes=1, read=read)
    assert result['state'] == 'pending'
    assert requests == []
