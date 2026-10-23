"""The viewer consumes a pinned bundle, never promotes unchecked annotations."""
from copy import deepcopy
import json

import pyarrow.parquet as pq
import pytest

from congress_api.retention import document_review_viewer as bridge
from congress_api.retention.document_review_receipts import file_digest
from test_document_review_portable import exported


@pytest.mark.parametrize('unsupported', [False, True])
def test_once_loaded_selection_withdrawal_and_exact_evidence(tmp_path, monkeypatch, unsupported):
    args, manifest = exported(tmp_path, unsupported)
    original = bridge.load_portable
    calls = []
    def load(*args):
        calls.append(args)
        return original(*args)
    monkeypatch.setattr(bridge, 'load_portable', load)
    snapshot = bridge.ReviewSnapshot(manifest, file_digest(manifest), args['sources'], args['documents'])
    doc = pq.read_table(args['documents']).to_pylist()[0]
    sources = pq.read_table(args['sources']).to_pylist()
    before = deepcopy((doc, sources))
    result = snapshot.selection(doc, sources)
    assert result['status'] == ('annotation_only_unsupported_forms' if unsupported else 'candidate_applied')
    assert result['selected']['document_kind'] == (['amendment'] if unsupported else ['letter'])
    assert result['review']['body_observation']['source_completeness_observations']
    withdrawn = snapshot.selection(doc, sources, withdrawn=True)
    assert withdrawn['status'] == 'withdrawn'
    assert withdrawn['selected'] == withdrawn['baseline']
    assert snapshot.selection(doc, sources) == result
    data, mime = snapshot.evidence(doc, sources, 'body')
    assert mime == 'application/pdf' and data == (tmp_path/'original/body.pdf').read_bytes()
    with pytest.raises(ValueError, match='format'):
        snapshot.evidence(doc, sources, 'page', 1)  # Deliberately non-PNG fixture bytes.
    with pytest.raises(ValueError, match='does not exist'):
        snapshot.evidence(doc, sources, 'page', 0)
    with pytest.raises(ValueError, match='Unknown'):
        snapshot.evidence(doc, sources, '/etc/passwd')
    with pytest.raises(ValueError, match='no saved text'):
        snapshot.evidence(doc, sources, 'native-text')
    other = dict(doc, document_id='other')
    assert snapshot.selection(other, [dict(sources[0], document_id='other')])['status'] == 'no_review'
    changed = deepcopy(sources); changed[0]['filename'] = 'different.pdf'
    with pytest.raises(ValueError, match='current baseline'):
        snapshot.selection(doc, changed)
    assert (doc, sources) == before
    result['baseline']['document_kind'].append('changed copy')
    assert (doc, sources) == before
    assert len(calls) == 1


@pytest.mark.parametrize('change', ['pair', 'manifest', 'body'])
def test_changes_after_loading_are_refused(tmp_path, change):
    args, manifest = exported(tmp_path)
    snapshot = bridge.ReviewSnapshot(manifest, file_digest(manifest), args['sources'], args['documents'])
    doc = pq.read_table(args['documents']).to_pylist()[0]; sources = pq.read_table(args['sources']).to_pylist()
    if change == 'pair':
        with args['sources'].open('ab') as stream: stream.write(b'changed')
    elif change == 'manifest': manifest.write_text('{}')
    else:
        locator = snapshot.candidates['d']['review']['body_observation']['path']
        digest = json.loads(manifest.read_text())['locators'][locator]
        (manifest.parent/'objects'/digest).write_bytes(b'changed')
    with pytest.raises(ValueError): snapshot.evidence(doc, sources, 'body')


def test_wrong_viewer_baseline_refused_before_admitting_review(tmp_path):
    args, manifest = exported(tmp_path)
    with args['sources'].open('ab') as stream: stream.write(b'other snapshot')
    with pytest.raises(ValueError, match='digest'):
        bridge.ReviewSnapshot(manifest, file_digest(manifest), args['sources'], args['documents'])


@pytest.mark.loopback
def test_http_review_evidence_snapshot_errors_and_failed_configuration(tmp_path):
    import pyarrow as pa
    from threading import Thread
    from urllib.error import HTTPError
    from urllib.request import urlopen
    from test_document_filename_viewer import viewer
    from test_document_review_catalog import fixture
    from congress_api.retention.document_review_catalog import write_candidates
    from congress_api.retention.document_review_portable import export_bundle
    args = fixture(tmp_path)
    for path in (args['sources'], args['documents']):
        table = pq.read_table(path).append_column('source_url', pa.array([None], type=pa.string()))
        pq.write_table(table, path)
    write_candidates(**args)
    summary = args['output']/'summary.json'
    export_bundle(summary, file_digest(summary), args['sources'], args['documents'], tmp_path/'portable')
    manifest = tmp_path/'portable/manifest.json'
    catalog = viewer.Catalog(args['sources'], review_manifest=manifest, review_sha256=file_digest(manifest))
    assert catalog.review_error is None
    server = viewer.ThreadingHTTPServer(('127.0.0.1', 0), viewer.handler_for(catalog))
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with urlopen(base+'/api/review/s?catalog=pair') as response:
            assert json.load(response)['selected']['document_kind'] == ['letter']
        with urlopen(base+'/api/review/s?catalog=pair&selection=baseline') as response:
            assert json.load(response)['selected']['document_kind'] == ['amendment']
        with urlopen(base+'/review-evidence/s?catalog=pair&kind=body') as response:
            assert response.headers['Content-Type'] == 'application/pdf'
            assert response.headers['Content-Disposition'] == 'attachment; filename="reviewed-document.pdf"'
            assert response.read() == (tmp_path/'body.pdf').read_bytes()
        from concurrent.futures import ThreadPoolExecutor
        def read_detail(i):
            with urlopen(base+('/api/entry/' if i%2 else '/api/review/')+'s?catalog=pair') as response:
                return json.load(response)
        with ThreadPoolExecutor(max_workers=6) as pool:
            results=list(pool.map(read_detail,range(30)))
        assert all(result.get('status') == 'candidate_applied' or result.get('record',{}).get('source_id') == 's'
                   for result in results)
        for path, code in [('/api/review/s?catalog=old',409),
                           ('/review-evidence/s?catalog=old&kind=body',409),
                           ('/review-evidence/s?catalog=pair&kind=../../etc/passwd',400),
                           ('/api/review/s?selection=invalid',400)]:
            with pytest.raises(HTTPError) as error: urlopen(base+path)
            assert error.value.code == code
        manifest.write_text('{}')
        with pytest.raises(HTTPError) as error: urlopen(base+'/api/review/s?catalog=pair')
        assert error.value.code == 400
        assert 'snapshot changed' in json.load(error.value)['error']
    finally:
        server.shutdown(); server.server_close(); thread.join()
    failed = viewer.Catalog(args['sources'], review_manifest=manifest, review_sha256='0'*64)
    assert failed.info['complete_body_reviews']
    assert failed.entry(0)['document']['document_kind'] == ['amendment']
    with pytest.raises(ValueError, match='digest'): failed.review(0)


def test_text_evidence_preserves_literal_bytes_with_plain_text_type(tmp_path):
    from test_document_review_catalog import fixture
    from congress_api.retention.document_review_catalog import write_candidates
    from congress_api.retention.document_review_portable import export_bundle
    args = fixture(tmp_path)
    text = tmp_path/'native.txt'; text.write_bytes(b'<script>literal source text</script>\n')
    receipt = json.loads(args['receipt'].read_text())
    receipt['records'][0].update(native_text_path=str(text), native_text_sha256=file_digest(text))
    args['receipt'].write_text(json.dumps(receipt)); args['receipt_sha256'] = file_digest(args['receipt'])
    proposals = json.loads(args['proposals'].read_text())
    proposals['records'][0]['evidence']['receipt_sha256'] = args['receipt_sha256']
    args['proposals'].write_text(json.dumps(proposals)); args['proposals_sha256'] = file_digest(args['proposals'])
    write_candidates(**args)
    summary=args['output']/'summary.json'
    export_bundle(summary,file_digest(summary),args['sources'],args['documents'],tmp_path/'portable')
    manifest=tmp_path/'portable/manifest.json'
    snapshot=bridge.ReviewSnapshot(manifest,file_digest(manifest),args['sources'],args['documents'])
    doc=pq.read_table(args['documents']).to_pylist()[0];sources=pq.read_table(args['sources']).to_pylist()
    assert snapshot.evidence(doc,sources,'native-text') == (text.read_bytes(),'text/plain; charset=utf-8')


def test_logical_group_reader_reuses_exact_review_policy_and_evidence(tmp_path):
    args, manifest = exported(tmp_path)
    document = pq.read_table(args['documents']).to_pylist()[0]
    sources = pq.read_table(args['sources']).to_pylist()
    calls=[]
    def group(identity):
        calls.append(identity)
        assert identity == document['document_id']
        return deepcopy(document), deepcopy(sources)
    snapshot=bridge.ReviewSnapshot.from_logical_groups(manifest,file_digest(manifest),group)
    assert calls == [document['document_id']]
    assert snapshot.selection(document,sources)['status']=='candidate_applied'
    assert snapshot.selection(document,sources,withdrawn=True)['status']=='withdrawn'
    assert snapshot.evidence(document,sources,'body')[0]==(tmp_path/'original/body.pdf').read_bytes()
    changed=deepcopy(sources);changed[0]['filename']='different.pdf'
    with pytest.raises(ValueError,match='current baseline'):
        bridge.ReviewSnapshot.from_logical_groups(manifest,file_digest(manifest),lambda _: (document,changed))
    manifest.write_text('{}')
    with pytest.raises(ValueError,match='snapshot changed'):snapshot.check()
