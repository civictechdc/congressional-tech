"""D1 receipt facts: expected rows precede the versioned native mapping."""
import gzip
import hashlib
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from docspec_client.client import NativeDatasets

STAMP = '2026-10-20T12:34:56Z'
SHA = 'a' * 64
KEY = 'bodies/sha256/aa/' + SHA + '.gz'


def files(root, rows, key='receipts/documents/2026-10-20/run.jsonl.gz'):
    root.mkdir(parents=True, exist_ok=True)
    path = root / 'receipt.gz'
    with gzip.open(path, 'wt') as out:
        for row in rows:
            out.write(json.dumps(row, separators=(',', ':')) + '\n')
    return [dict(key=key, path=str(path))]


def ingest(root, rows, *, key='receipts/documents/2026-10-20/run.jsonl.gz', **kwargs):
    from congress_api.lake.captures import stage_captures
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    return stage_captures(files(root / 'input', rows, key), engine=engine, work=root / 'stage', **kwargs)


def body(**more):
    return dict(sha256=SHA, body_key=KEY, bytes=123, **more)


def test_bodiless_status_time_and_non_http_capture_status(tmp_path):
    stage = ingest(tmp_path, [
        dict(source_file='old-run', record=dict(url='https://example.org/gone', status_code=404,
            observed_at=STAMP, capture_status=200)),
        dict(record=dict(url='https://example.org/meeting', meetingStatus='200',
            capture_status=200, checked_at=STAMP, started_at=STAMP)),
    ])
    a, b = pq.read_table(stage / 'captures.parquet').to_pylist()
    assert a['http_status'] == a['attempt_status'] == 404
    assert a['retrieved_at'].isoformat() == '2026-10-20T12:34:56+00:00'
    assert a['run_id'] == 'old-run' and a['outcome'] == 'failed'
    assert a['sha256'] is None and a['capture_index'] == 0
    assert b['http_status'] is None and b['retrieved_at'] is None


def test_new_attempts_do_not_borrow_final_success(tmp_path):
    stage = ingest(tmp_path, [dict(run_id='new', mode='fetch', family='documents',
        requested_url='https://example.org/a', url='https://example.org/final',
        retrieved_at=STAMP, http_status=200, outcome='stored',
        prior_attempts=[dict(url='https://example.org/a', retrieved_at=STAMP, http_status=206)],
        captures=[dict(body(), attempt=1, complete=False, stored_suffix=''),
                  dict(body(), attempt=0, complete=True, stored_suffix='.gz')])])
    a, b = pq.read_table(stage / 'captures.parquet').to_pylist()
    assert a['http_status'] == b['http_status'] == 200
    assert (a['attempt_status'], a['complete']) == (206, False)
    assert (b['attempt_status'], b['complete']) == (200, True)
    assert a['stored_suffix'] == '' and a['sha256'] == bytes.fromhex(SHA)
    assert a['mode'] == b['mode'] == 'fetch'
    assert a['original_url'] is None and b['original_url'] is None
    assert 'stored_sha256' not in a


def test_old_capture_and_matching_reference_enrich_storage_only(tmp_path):
    stage = ingest(tmp_path, [dict(record=dict(url='https://example.org/a', http_status=200,
        retrieved_at=STAMP, outcome='saved'), captures=[body(status_code=206, complete=False)],
        file_references=[body(http_status=200, complete=True, stored_bytes=42)])])
    [row] = pq.read_table(stage / 'captures.parquet').to_pylist()
    assert row['stored_bytes'] == 42 and row['stored_suffix'] == '.gz'
    assert row['attempt_status'] == 206 and row['complete'] is False


def test_unmatched_secondary_reference_refuses_with_locator(tmp_path):
    with pytest.raises(ValueError, match='secondary.*receipts/documents.*:1'):
        ingest(tmp_path, [dict(captures=[body()], file_references=[
            dict(sha256='b'*64, body_key='bodies/sha256/bb/'+'b'*64+'.gz')])])


def test_legacy_recovery_without_mode_and_imported_at(tmp_path):
    stage = ingest(tmp_path, [dict(source_file='recovery-20261015', record=dict(
        url='https://archive.org/copy', retrieved_at=STAMP,
        source_associations=[dict(original_url='https://example.org/dead', basis='accepted_copy')]),
        file_references=[body()])])
    [row] = pq.read_table(stage / 'captures.parquet').to_pylist()
    assert row['mode'] == 'retained_import'
    assert row['original_url'] == 'https://example.org/dead'
    assert row['match_basis'] == 'accepted_copy'
    assert row['imported_at'].isoformat() == '2026-10-20T00:00:00+00:00'


@pytest.mark.parametrize('value', ['invented-success', 'False'])
def test_unknown_outcome_refuses_before_output(tmp_path, value):
    with pytest.raises(ValueError, match='unknown.*outcome'):
        ingest(tmp_path, [dict(record=dict(outcome=value))])
    assert not (tmp_path / 'stage/captures.parquet').exists()


def test_cap_and_line_fetch_times_and_64mib_completeness(tmp_path):
    stage = ingest(tmp_path, [dict(record=dict(url='https://example.org/a',
        captured_at=STAMP, http_status=200), captures=[dict(body(), bytes=64<<20,
        parent_retrieved_at='2026-10-19T00:00:00Z'), body(capture_date='2026-10-18')])])
    a, b = pq.read_table(stage / 'captures.parquet').to_pylist()
    assert a['complete'] is False and b['complete'] is True
    assert a['retrieved_at'].isoformat() == '2026-10-19T00:00:00+00:00'
    assert b['retrieved_at'].isoformat() == '2026-10-18T00:00:00+00:00'


def test_rebuild_and_incremental_missing_receipt_equivalence(tmp_path):
    from congress_api.lake.captures import stage_captures
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    one = files(tmp_path/'one', [dict(record=dict(url='https://example.org/one'))])
    two = files(tmp_path/'two', [dict(record=dict(url='https://example.org/two'))],
                key='receipts/documents/undated/two.jsonl.gz')
    first = stage_captures(one, engine=engine, work=tmp_path/'first')
    delta = stage_captures(one+two, engine=engine, work=tmp_path/'delta',
                           existing=first/'captures.parquet')
    rebuilt = stage_captures(two+one, engine=engine, work=tmp_path/'rebuilt')
    rows = pa.concat_tables([pq.read_table(first/'captures.parquet'),
                             pq.read_table(delta/'captures.parquet')]).sort_by('receipt_key')
    assert rows.equals(pq.read_table(rebuilt/'captures.parquet').sort_by('receipt_key'))
    assert pq.read_metadata(delta/'captures.parquet').num_rows == 1
    assert json.loads((delta/'ingested-receipts.json').read_text())['receipt_keys']==[two[0]['key']]


def test_ingested_receipt_is_never_reopened_by_stage(tmp_path):
    from congress_api.lake.captures import stage_captures
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    key='receipts/documents/2026-10-19/already.jsonl.gz'
    prior=tmp_path/'existing.parquet'
    pq.write_table(pa.table({'receipt_key':[key]}),prior)
    pending=files(tmp_path/'pending',[dict(record=dict(url='https://example.org/new'))])
    stage=stage_captures([dict(key=key,path='/unopened/absent-receipt.gz'),*pending],
        engine=engine,work=tmp_path/'stage',existing=prior)
    assert pq.read_table(stage/'captures.parquet')['receipt_key'].to_pylist()==[pending[0]['key']]


def test_staging_refuses_metadata_with_a_different_producer(tmp_path):
    from congress_api.lake.receipt_metadata import compact
    from congress_api.lake.captures import stage_captures
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    source=files(tmp_path/'raw',[dict(record=dict(url='https://example.org/a'))])
    metadata=compact(files=source,engine=engine,work=tmp_path/'metadata')
    manifest=metadata.parent/'metadata.json'
    descriptor=json.loads(manifest.read_text())
    descriptor['producer']['sha256']='0'*64
    manifest.write_text(json.dumps(descriptor))
    with pytest.raises(ValueError,match='producer'):
        stage_captures([dict(key=source[0]['key'])],engine=engine,work=tmp_path/'stage',counter=metadata)
    assert not (tmp_path/'stage/ingested-receipts.json').exists()


def test_inline_record_sha_canonical_json_required(tmp_path):
    record = dict(z=2, meeting=dict(z=['é', dict(b=2, a=1)], a='value'))
    stage = ingest(tmp_path, [dict(record=record)],
                   key='receipts/congress/meetings/2026-10-20/run.jsonl.gz')
    [row] = pq.read_table(stage/'captures.parquet').to_pylist()
    compact = json.dumps(record['meeting'], ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode()
    assert row['record_sha'] == hashlib.sha256(compact).digest()


def test_headers_items_retry_deadline_and_not_modified(tmp_path):
    stage = ingest(tmp_path, [
        dict(record=dict(url='https://example.org/a', http_status=304, retrieved_at=STAMP)),
        dict(record=dict(url='https://example.org/b', http_status=200, retrieved_at=STAMP,
            response_header_items=[dict(name='Retry-After', value='120'),
                                   dict(name='Content-Disposition', value='attachment; filename=x.pdf')]),
            captures=[body()]),
    ])
    a, b = pq.read_table(stage/'captures.parquet').to_pylist()
    assert a['outcome'] == 'unchanged'
    assert b['outcome'] == 'retry_later'
    assert b['retry_after'].isoformat() == '2026-10-20T12:36:56+00:00'
    assert b['h_content_disposition'] == 'attachment; filename=x.pdf'


def test_list_record_pointer_selects_its_own_response(tmp_path):
    stage = ingest(tmp_path, [dict(record=[dict(url='https://example.org/a', status_code=206),
        dict(url='https://example.org/b', status_code=200)], captures=[
            body(pointer=[0, 'content', 'body']), body(pointer=['1', 'content', 'body'])])])
    a, b = pq.read_table(stage/'captures.parquet').to_pylist()
    assert (a['url'], a['attempt_status']) == ('https://example.org/a', 206)
    assert (b['url'], b['attempt_status']) == ('https://example.org/b', 200)


def test_list_bodiless_conflicting_facts_refuse(tmp_path):
    with pytest.raises(ValueError, match='list.*facts'):
        ingest(tmp_path, [dict(record=[dict(url='https://example.org/a'),
                                        dict(url='https://example.org/b')])])


def test_secondary_storage_conflicts_and_unknown_mode_refuse(tmp_path):
    with pytest.raises(ValueError, match='storage conflict'):
        ingest(tmp_path/'conflict', [dict(captures=[body()], file_references=[
            body(stored_bytes=12), body(stored_bytes=13)])])
    with pytest.raises(ValueError, match='unknown mode'):
        ingest(tmp_path/'mode', [dict(record=dict(mode='invented'))])


def test_exact_arrow_schema_and_unchanged_source_receipt(tmp_path):
    source = dict(record=dict(http_status=200, retrieved_at=STAMP), captures=[body()])
    stage = ingest(tmp_path, [source])
    schema = pq.read_schema(stage/'captures.parquet')
    assert schema.field('sha256').type == pa.binary(32)
    assert schema.field('stored_md5').type == pa.binary(16)
    assert schema.field('receipt_line').type == pa.int32()
    assert schema.field('retrieved_at').type == pa.timestamp('us', 'UTC')
    with gzip.open(tmp_path/'input/receipt.gz', 'rt') as inp:
        assert json.loads(inp.read()) == source


def test_verified_counter_projection_keeps_raw_metadata_missing_from_typed_fields(tmp_path):
    from congress_api.lake.captures import compact_counter, stage_captures
    engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    record=dict(url='https://example.org/a',http_status=200,retrieved_at=STAMP,
        prior_attempts=[dict(http_status=206)],response_header_items=[
            dict(name='Content-Disposition',value='attachment; filename=retained.pdf')])
    source=dict(source_file='run',record=record,captures=[body(pointer=['content','body'],
        status_code=206,complete=False),body(pointer=['prior_attempts',0,'content','body'],complete=False)])
    receipt_key='receipts/documents/2026-10-20/run.jsonl.gz'
    captures_type=pa.list_(pa.struct([('body_key',pa.string()),('sha256',pa.string()),('bytes',pa.int64())]))
    schema=pa.schema([('source_file',pa.string()),
        ('record',pa.struct([('url',pa.string()),('http_status',pa.int64()),('retrieved_at',pa.string())])),
        ('captures',captures_type),('file_references',captures_type),
        ('__receipt_key',pa.string()),('__receipt_line',pa.int64()),
        ('__receipt_family',pa.string()),('__raw_line',pa.string()),('__type_conflicts',pa.list_(pa.string()))])
    counter=tmp_path/'counter.parquet'
    pq.write_table(pa.Table.from_pylist([dict(source, __receipt_key=receipt_key,__receipt_line=1,
        __receipt_family='documents',__raw_line=json.dumps(source),__type_conflicts=[])],schema=schema),counter)
    metadata=compact_counter(counter,engine=engine,work=tmp_path/'compact')
    actual=stage_captures([dict(key=receipt_key)],engine=engine,work=tmp_path/'counter-stage',counter=metadata)
    expected=ingest(tmp_path/'direct',[source])
    a=pq.read_table(actual/'capture-evidence.parquet')
    b=pq.read_table(expected/'capture-evidence.parquet')
    assert a.equals(b),([{k:(x[k],y[k]) for k in x if x[k]!=y[k]}
        for x,y in zip(a.to_pylist(),b.to_pylist())],[(x,y) for x,y in zip(a.schema,b.schema) if x!=y])


def test_old_prior_attempt_without_attempt_number_keeps_own_response(tmp_path):
    stage=ingest(tmp_path,[dict(record=dict(http_status=200,retrieved_at=STAMP,
        outcome='saved',prior_attempts=[dict(http_status=206)]),captures=[
            dict(body(),bytes=64<<20,pointer=['prior_attempts',0,'content','body']),
            body(pointer=['content','body'])])])
    a,b=pq.read_table(stage/'captures.parquet').to_pylist()
    assert (a['attempt_status'],a['complete'])==(206,False)
    assert (b['attempt_status'],b['complete'])==(200,True)


@pytest.mark.parametrize('which,expected',[
    ('final','size_limit'),('prior','stored'),('member','stored'),
    ('near-cap','stored'),('specific-outcome','request_failed'),('specific-error','stored')])
def test_confirmed_legacy_cutoff_is_a_line_outcome_only_for_its_final_response(tmp_path,which,expected):
    record=dict(url='https://example.org/a',http_status=200,retrieved_at=STAMP,
                outcome='request_failed' if which=='specific-outcome' else 'saved')
    if which=='specific-error':record['error_type']='timeout'
    cap=dict(body(),bytes=(62<<20 if which=='near-cap' else 64<<20),complete=False)
    if which=='prior':
        cap.update(pointer=['prior_attempts',0,'content','body'])
        record['prior_attempts']=[dict(http_status=200)]
    if which=='member':cap.update(pointer=['archive_members',0,'body'],member_path='member.pdf')
    captures=[cap]
    if which in {'prior','member'}:captures.append(body(complete=True,pointer=['content','body']))
    stage=ingest(tmp_path,[dict(record=record,captures=captures)])
    assert {r['outcome'] for r in pq.read_table(stage/'captures.parquet').to_pylist()}=={expected}


def test_new_failed_outcome_is_not_reinterpreted_as_stored(tmp_path):
    stage=ingest(tmp_path,[dict(run_id='new',mode='fetch',family='documents',
        requested_url='https://example.org/a',url='https://example.org/a',retrieved_at=STAMP,
        http_status=200,outcome='failed',captures=[body(complete=True)])])
    assert pq.read_table(stage/'captures.parquet')['outcome'].to_pylist()==['failed']


def test_payload_is_removed_before_capture_fanout(tmp_path):
    marker='body-payload-must-stay-in-raw-'
    stage=ingest(tmp_path,[dict(source_file='fanout',record=dict(url='https://example.org/a',
        http_status=200,content=dict(body=marker*20000)),captures=[body() for _ in range(100)])])
    [row]=pq.read_table(stage/'receipt-metadata/receipt-metadata.parquet').to_pylist()
    assert marker not in row['line'] and marker not in row['record_json']
    assert len(row['record_json'].encode())<32768
    assert pq.read_metadata(stage/'captures.parquet').num_rows==100


def test_prior_attempt_keeps_status_code_and_recorded_completeness(tmp_path):
    stage=ingest(tmp_path,[dict(record=dict(http_status=200,complete=True,
        prior_attempts=[dict(status_code=206,complete=False)]),captures=[
            body(pointer=['prior_attempts',0,'content','body']),
            body(pointer=['content','body'])])])
    prior,final=pq.read_table(stage/'captures.parquet').to_pylist()
    assert (prior['attempt_status'],prior['complete'])==(206,False)
    assert (final['attempt_status'],final['complete'])==(200,True)


@pytest.mark.parametrize('captured_member',[False,True])
def test_archive_expansion_requires_a_captured_member(tmp_path,captured_member):
    captures=[body(pointer=['content','body'])]
    if captured_member:
        captures.append(body(pointer=['archive_members',0,'body'],member_path='inside.pdf'))
    stage=ingest(tmp_path,[dict(record=dict(archive_members=[dict(error='unreadable')]),
                               captures=captures)])
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert rows[0]['expansion']==('expanded' if captured_member else None)
    if captured_member:assert rows[1]['expansion'] is None


def test_sparse_bodiless_record_list_never_silently_loses_later_facts(tmp_path):
    # A single line cannot choose the first sparse element and discard the
    # only recorded HTTP status/time. Refusal keeps the receipt pending.
    with pytest.raises(ValueError,match='list.*facts'):
        ingest(tmp_path,[dict(record=[dict(url='https://example.org/a'),
            dict(url='https://example.org/a',status_code=404,observed_at=STAMP)])])


def test_http_date_retry_after_preserves_publisher_deadline(tmp_path):
    stage=ingest(tmp_path,[dict(record=dict(http_status=503,retrieved_at=STAMP,
        response_headers={'retry-after':'Wed, 21 Oct 2026 07:28:00 GMT'}))])
    [row]=pq.read_table(stage/'captures.parquet').to_pylist()
    assert row['retry_after'].isoformat()=='2026-10-21T07:28:00+00:00'


@pytest.mark.parametrize('same_url',[True,False])
def test_owner_decided_direct_official_package_is_a_fetch_only_for_same_source(tmp_path,same_url):
    original='https://example.org/package.zip'
    actual=original if same_url else 'https://archive.org/copy.zip'
    stage=ingest(tmp_path,[dict(mode='retained_import',record=dict(url=actual,
        requested_url=actual,retrieved_at=STAMP,http_status=200,outcome='saved',
        source_associations=[dict(original_url=original,basis='direct_official_package')]),
        captures=[body(complete=True)])])
    [row]=pq.read_table(stage/'captures.parquet').to_pylist()
    assert row['mode']==('fetch' if same_url else 'retained_import')
    assert row['original_url']==(None if same_url else original)
    assert row['retrieved_at'].isoformat()=='2026-10-20T12:34:56+00:00'


@pytest.mark.parametrize('headers',[
    {'response_header_items':[{'name':'Retry-After','value':'120'},
                              {'name':'Content-Disposition','value':'attachment; filename=top.pdf'}]},
    {'headers':{'Retry-After':'120','Content-Disposition':'attachment; filename=top.pdf'}},
    {'response_headers':{'Retry-After':'120','Content-Disposition':'attachment; filename=top.pdf'}},
])
def test_top_level_header_shapes_preserve_deadline_and_download_name(tmp_path,headers):
    stage=ingest(tmp_path,[dict(http_status=503,retrieved_at=STAMP,**headers)])
    [row]=pq.read_table(stage/'captures.parquet').to_pylist()
    assert row['retry_after'].isoformat()=='2026-10-20T12:36:56+00:00'
    assert row['h_content_disposition']=='attachment; filename=top.pdf'
