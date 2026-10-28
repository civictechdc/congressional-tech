"""pipeline-data snapshots reach raw as create-only bodies plus one receipt per run."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

from botocore.exceptions import ClientError
import pytest

from congress_api.cli import pipeline_raw as cli
from congress_api.retention import pipeline_raw
from congress_api.retention.r2 import R2Store

WRITER = dict(job='test', commit='c' * 40, lockfile_digest='d' * 64)


class Bucket:
    """R2 create-only PUT and legacy-key HEAD; no body download exists."""

    def __init__(self):
        self.meta = SimpleNamespace(config=SimpleNamespace(retries={}),
                                    events=SimpleNamespace(register_first=lambda *a, **k: None))
        self.objects, self.puts = {}, []

    def head_object(self, **args):
        value = self.objects.get(args['Key'])
        if value is None:
            raise ClientError({'Error': {'Code': '404'}}, 'HeadObject')
        return dict(ContentLength=len(value['Body']), ETag=hashlib.md5(value['Body']).hexdigest())

    def put_object(self, **args):
        body = args['Body'] if isinstance(args['Body'], bytes) else args['Body'].read()
        self.puts.append(args['Key'])
        if args.get('IfNoneMatch') == '*' and args['Key'] in self.objects:
            raise ClientError({'Error': {'Code': 'PreconditionFailed'}}, 'PutObject')
        self.objects[args['Key']] = dict(args, Body=body)
        return {'ETag': '"%s"' % hashlib.md5(body).hexdigest()}


def receipt(bucket, key):
    return [json.loads(line) for line in gzip.decompress(bucket.objects[key]['Body']).splitlines()]


def git_blob(data):
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def checkout(tmp_path, files):
    for name, data in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(data)
    git = ['git', '-C', str(tmp_path), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid']
    subprocess.run([*git, 'init', '-q'], check=True)
    subprocess.run([*git, 'add', '-A'], check=True)
    subprocess.run([*git, 'commit', '-q', '-m', 'snapshot'], check=True)
    return subprocess.run([*git, 'rev-parse', 'HEAD'], check=True, capture_output=True,
                          text=True).stdout.strip()


def batch(tmp_path, snapshots):
    """A rescue batch: blobs/<sha256>, files.jsonl and commits.jsonl."""
    (tmp_path / 'blobs').mkdir()
    files, commits = [], []
    for number, contents in enumerate(snapshots):
        commit = f'{number:040x}'
        commits.append(dict(commit=commit, committed_at=f'2026-10-0{number + 5}T14:05:58Z',
                            pushed_at=f'2026-10-0{number + 5}T14:08:12Z', tree='t' * 40,
                            message='Pipeline data snapshot'))
        for path, data in contents.items():
            sha = hashlib.sha256(data).hexdigest()
            (tmp_path / 'blobs' / sha).write_bytes(data)
            files.append(dict(commit=commit, path=path, git_blob_sha=git_blob(data),
                              size=len(data), sha256=sha))
    for name, rows in (('files.jsonl', files), ('commits.jsonl', commits)):
        (tmp_path / name).write_text(''.join(json.dumps(row) + '\n' for row in rows))
    return tmp_path


def test_checkout_stores_bodies_then_one_receipt_with_model_line_shape(tmp_path):
    record = b'{"meeting": 1}\n' * 50
    commit = checkout(tmp_path, {'congress_meetings.json': record, 'youtube/a.json.gz': b'\x1f\x8bzip',
                                 'committee-explorer/public/x.parquet': b'built'})
    bucket = Bucket()
    summary = pipeline_raw.archive(R2Store(bucket, 'raw'), pipeline_raw.checkout_files(tmp_path),
                                   writer=WRITER, run_id='20261026T000000Z-abc', day='2026-10-26')

    key = 'receipts/pipeline-data/2026-10-26/20261026T000000Z-abc-000001.jsonl.gz'
    assert summary == dict(run_id='20261026T000000Z-abc', files=2, skipped=1, bodies=2,
                           created=2, existing=0, receipts=[key])
    assert bucket.puts[-1] == key and len(bucket.puts) == 3  # bodies first, explorer skipped
    sha = hashlib.sha256(record).hexdigest()
    body = bucket.objects[f'bodies/sha256/{sha[:2]}/{sha}']
    assert body['ContentType'] == 'application/json' and body['ContentEncoding'] == 'gzip'
    assert gzip.decompress(body['Body']) == record and body['IfNoneMatch'] == '*'
    gz = bucket.objects[pipeline_raw.body_key(hashlib.sha256(b'\x1f\x8bzip').hexdigest())]
    assert gz['Body'] == b'\x1f\x8bzip' and 'ContentEncoding' not in gz

    line = next(line for line in receipt(bucket, key) if line['url'].endswith('congress_meetings.json'))
    url = f'{pipeline_raw.REPOSITORY}/raw/{commit}/congress_meetings.json'
    assert line == dict(
        run_id='20261026T000000Z-abc', mode='fetch', family='pipeline-data',
        requested_url=f'{pipeline_raw.REPOSITORY}/raw/pipeline-data/congress_meetings.json', url=url,
        retrieved_at=line['retrieved_at'], http_status=None, provider_status=None, outcome='stored',
        transport='git', response_headers={}, redirects=[], prior_attempts=[],
        source_context={'observations': []}, writer=WRITER,
        captures=[dict(pointer=['content', 'body'], attempt=0, complete=True, context_url=url,
                       member_path=None, entry_index=None, expansion=None, sha256=sha,
                       bytes=len(record), media_type='application/json', sniffed_format=None,
                       sniff_version=None, intact=None, stored_suffix='', fidelity='saved-record',
                       git_blob_sha=git_blob(record),
                       stored_md5=hashlib.md5(body['Body']).hexdigest(),
                       stored_bytes=len(body['Body']))])
    assert line['retrieved_at'].endswith('Z')


def test_existing_body_412_is_success_without_head_or_download(tmp_path):
    checkout(tmp_path, {'gpo-evidence.jsonl.gz': b'\x1f\x8bevidence'})
    bucket = Bucket()
    store = R2Store(bucket, 'raw')
    first = pipeline_raw.archive(store, pipeline_raw.checkout_files(tmp_path), writer=WRITER)
    second = pipeline_raw.archive(store, pipeline_raw.checkout_files(tmp_path), writer=WRITER)

    assert (first['created'], second['created'], second['existing']) == (1, 0, 1)
    [line] = receipt(bucket, second['receipts'][0])
    assert line['outcome'] == 'unchanged' and line['captures'][0]['stored_suffix'] == ''
    assert 'stored_md5' not in line['captures'][0]
    assert first['run_id'] != second['run_id']  # fresh run IDs, so receipts never collide


def test_reused_run_id_fails_on_the_receipt(tmp_path):
    checkout(tmp_path, {'README.md': b'notes'})
    store = R2Store(Bucket(), 'raw')
    pipeline_raw.archive(store, pipeline_raw.checkout_files(tmp_path), writer=WRITER,
                         run_id='run', day='2026-10-26')
    with pytest.raises(RuntimeError, match='reused receipt name'):
        pipeline_raw.archive(store, pipeline_raw.checkout_files(tmp_path), writer=WRITER,
                             run_id='run', day='2026-10-26')


def test_rescue_batch_uploads_each_body_once_and_stays_unmodified(tmp_path):
    shared, changed = b'{"a": 1}', b'{"a": 2}'
    root = batch(tmp_path, [{'youtube/youtube_00.json': shared, 'README.md': b'x'},
                            {'youtube/youtube_00.json': changed, 'README.md': b'x'}])
    before = {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}
    bucket = Bucket()
    summary = pipeline_raw.archive(R2Store(bucket, 'raw'), pipeline_raw.rescue_files(root),
                                   writer=WRITER)

    assert (summary['files'], summary['bodies'], summary['created']) == (4, 3, 3)
    assert len(bucket.puts) == 4  # three bodies, one receipt
    lines = receipt(bucket, summary['receipts'][0])
    assert [line['outcome'] for line in lines] == ['stored', 'stored', 'stored', 'unchanged']
    assert [line['retrieved_at'] for line in lines] == ['2026-10-05T14:05:58Z'] * 2 + ['2026-10-06T14:05:58Z'] * 2
    assert lines[2]['url'].endswith(f'/raw/{1:040x}/youtube/youtube_00.json')
    assert {path: path.read_bytes() for path in root.rglob('*') if path.is_file()} == before


def test_rescue_blob_that_disagrees_with_its_listing_is_refused(tmp_path):
    root = batch(tmp_path, [{'README.md': b'x'}])
    (root / 'blobs' / hashlib.sha256(b'x').hexdigest()).write_bytes(b'y')
    with pytest.raises(ValueError, match='recorded identity'):
        pipeline_raw.archive(R2Store(Bucket(), 'raw'), pipeline_raw.rescue_files(root), writer=WRITER)


def test_dry_run_plans_keys_without_connecting(tmp_path, monkeypatch, capsys):
    root = batch(tmp_path, [{'README.md': b'x', 'committee-explorer/state.json': b'{}'}])

    def refuse(*args, **kwargs):
        raise AssertionError('dry run opened a connection')

    monkeypatch.setattr('congress_shared.storage.connect_r2', refuse)
    cli.main(['--rescue-batch', str(root), '--dry-run'])
    summary = json.loads(capsys.readouterr().out)
    sha = hashlib.sha256(b'x').hexdigest()
    assert summary['body_keys'] == [f'bodies/sha256/{sha[:2]}/{sha}']
    assert (summary['files'], summary['skipped'], summary['missing']) == (1, 1, 0)
    assert summary['receipts'] == ['receipts/pipeline-data/<UTC date>/<run_id>-000001.jsonl.gz']


def test_rescued_import_is_registered_but_weekly_fetch_is_not(tmp_path, capsys):
    """Both move source records, not recoveries; only rescue excludes capture dates."""
    root = batch(tmp_path, [{'README.md': b'x'}])
    cli.main(['--rescue-batch', str(root), '--dry-run'])
    summary = json.loads(capsys.readouterr().out)
    registry = json.loads((cli.ROOT / 'model/registries/import-runs.json').read_text())
    assert summary['import_run'] in registry
    assert summary['import_run']['run_id'] == pipeline_raw.RESCUE_RUN_ID
    assert summary['import_run']['date'] == '2026-10-27'
    [item] = list(pipeline_raw.rescue_files(root))
    line = pipeline_raw.receipt_line(item, run_id=pipeline_raw.RESCUE_RUN_ID, writer=WRITER,
                                     sha256=item.sha256, outcome='unchanged')
    assert line['mode'] == 'fetch' and line['retrieved_at'] == '2026-10-05T14:05:58Z'


def test_receipt_encodes_git_paths_as_url_paths(tmp_path):
    """A git filename cannot inject a query credential or a local path into a receipt."""
    checkout(tmp_path, {'name?api_key=private#part.json': b'{}'})
    bucket = Bucket()
    summary = pipeline_raw.archive(R2Store(bucket, 'raw'), pipeline_raw.checkout_files(tmp_path),
                                   writer=WRITER)
    [line] = receipt(bucket, summary['receipts'][0])
    assert line['url'].endswith('/name%3Fapi_key%3Dprivate%23part.json')
    assert line['requested_url'].endswith('/name%3Fapi_key%3Dprivate%23part.json')
    assert str(tmp_path) not in json.dumps(line)
    assert set(line['writer']) == {'job', 'commit', 'lockfile_digest'}


def test_unsafe_receipt_identity_is_refused_before_storage(tmp_path):
    checkout(tmp_path, {'README.md': b'x'})
    bucket = Bucket()
    with pytest.raises(ValueError, match='writer'):
        pipeline_raw.archive(R2Store(bucket, 'raw'), pipeline_raw.checkout_files(tmp_path),
                             writer=dict(WRITER, authorization='secret'))
    assert bucket.puts == []


def test_weekly_writer_reuses_the_legacy_body_suffix_without_upload(tmp_path):
    data = b'{"meeting": 1}'
    checkout(tmp_path, {'congress_meetings.json': data})
    bucket = Bucket()
    key = pipeline_raw.body_key(hashlib.sha256(data).hexdigest())
    bucket.objects[key + '.gz'] = {'Body': gzip.compress(data, mtime=0)}
    result = pipeline_raw.archive(R2Store(bucket, 'raw'), pipeline_raw.checkout_files(tmp_path),
                                  writer=WRITER)
    assert result['created'] == 0 and bucket.puts == result['receipts']
    [line] = receipt(bucket, result['receipts'][0])
    assert line['captures'][0]['stored_suffix'] == '.gz'
    assert 'stored_md5' not in line['captures'][0]


def test_rescue_cli_rerun_preserves_existing_objects(tmp_path, monkeypatch, capsys):
    """Run the actual CLI twice, optionally using a copied real two-snapshot batch."""
    from datetime import datetime, timezone
    from io import BytesIO
    import os
    import shutil

    application = tmp_path / 'application'
    application.mkdir()
    (application / 'model/registries').mkdir(parents=True)
    (application / 'model/registries/import-runs.json').write_text(json.dumps([
        dict(run_id=pipeline_raw.RESCUE_RUN_ID, date=datetime.now(timezone.utc).date().isoformat())]))
    (application / 'uv.lock').write_text('fixture locked dependencies\n')
    checkout(application, {})
    monkeypatch.setattr(cli, 'ROOT', application)
    root = tmp_path / 'batch'
    if copied := os.environ.get('CXR_RESCUE_COPY'):
        source = Path(copied).resolve()
        assert source.is_relative_to(Path(os.environ['CXR_RELEASE_SCRATCH']).resolve())
        assert len((source / 'commits.jsonl').read_text().splitlines()) == 2
        shutil.copytree(source, root)
    else:
        root.mkdir()
        batch(root, [{'README.md': b'first', 'youtube/a.json': b'{"x":1}'},
                     {'README.md': b'second', 'youtube/a.json': b'{"x":1}'}])
    before = {p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in root.rglob('*') if p.is_file()}
    bucket = Bucket()

    def get_object(**args):
        value = bucket.objects.get(args['Key'])
        if value is None:
            raise ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')
        return dict(Body=BytesIO(value['Body']), ContentLength=len(value['Body']),
                    ETag=hashlib.md5(value['Body']).hexdigest())

    bucket.get_object = get_object
    def connect(**args):
        assert args['bucket'] == 'cx-release-local-fake'
        return bucket
    monkeypatch.setattr('congress_shared.storage.connect_r2', connect)
    command = ['--rescue-batch', str(root), '--bucket', 'cx-release-local-fake']
    cli.main(command)
    first = json.loads(capsys.readouterr().out)
    identities = {key: hashlib.sha256(value['Body']).hexdigest() for key,value in bucket.objects.items()}
    cli.main(command)
    second = json.loads(capsys.readouterr().out)
    assert second['created'] == 0 and second['receipts'] == first['receipts']
    assert identities == {key: hashlib.sha256(value['Body']).hexdigest()
                          for key,value in bucket.objects.items()}
    assert before == {p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in root.rglob('*') if p.is_file()}
    lines = receipt(bucket, first['receipts'][0])
    assert len({line['url'].split('/raw/')[1].split('/')[0] for line in lines}) == 2
    # A different batch at the registered receipt name must fail before any PUT.
    key = first['receipts'][0]
    changed = receipt(bucket, key)
    changed[0]['captures'][0]['sha256'] = '0' * 64
    bucket.objects[key]['Body'] = gzip.compress(b''.join(json.dumps(line).encode() + b'\n'
                                                       for line in changed), mtime=0)
    puts = len(bucket.puts)
    with pytest.raises(ValueError, match='rescue receipt'):
        cli.main(command)
    assert len(bucket.puts) == puts


def test_stale_rescue_date_fails_before_connecting(tmp_path, monkeypatch):
    root = tmp_path / 'application'
    (root / 'model/registries').mkdir(parents=True)
    (root / 'model/registries/import-runs.json').write_text(json.dumps([
        dict(run_id=pipeline_raw.RESCUE_RUN_ID, date='2000-01-01')]))
    monkeypatch.setattr(cli, 'ROOT', root)
    source = tmp_path / 'batch'
    source.mkdir()
    batch(source, [{'README.md': b'x'}])
    def refuse(**args):
        raise AssertionError('stale import connected')
    monkeypatch.setattr('congress_shared.storage.connect_r2', refuse)
    with pytest.raises(ValueError, match='actual UTC import date'):
        cli.main(['--rescue-batch', str(source), '--bucket', 'cx-release-local-fake'])


@pytest.mark.parametrize('accepted_before_failure', [False, True])
def test_rescue_resume_after_a_partitioned_receipt_failure(tmp_path, monkeypatch, accepted_before_failure):
    from io import BytesIO
    root = batch(tmp_path, [{'a.json':b'{"x":1}', 'b.json':b'{"x":2}'},
                            {'a.json':b'{"x":3}', 'b.json':b'{"x":2}'}])
    monkeypatch.setattr(pipeline_raw, 'RECEIPT_LINES', 2)
    bucket = Bucket()
    def get_object(**args):
        value = bucket.objects.get(args['Key'])
        if value is None:
            raise ClientError({'Error':{'Code':'NoSuchKey'}}, 'GetObject')
        return dict(Body=BytesIO(value['Body']), ContentLength=len(value['Body']),
                    ETag=hashlib.md5(value['Body']).hexdigest())
    bucket.get_object = get_object
    put = bucket.put_object
    def interrupted(**args):
        if args['Key'].endswith('-000002.jsonl.gz'):
            if accepted_before_failure:
                put(**args)
            raise OSError('fixture interrupted receipt publication')
        return put(**args)
    bucket.put_object = interrupted
    store = R2Store(bucket, 'cx-release-local-fake')
    options = dict(writer=WRITER, run_id=pipeline_raw.RESCUE_RUN_ID, day='2026-10-27', resume=True)
    with pytest.raises(OSError, match='interrupted'):
        pipeline_raw.archive(store, pipeline_raw.rescue_files(root), **options)
    before = {key:value['Body'] for key,value in bucket.objects.items()}
    assert sum(key.startswith('receipts/') for key in before) == (2 if accepted_before_failure else 1)
    bucket.put_object = put
    result = pipeline_raw.archive(store, pipeline_raw.rescue_files(root), **options)
    assert result['created'] == 0 and len(result['receipts']) == 2
    assert all(bucket.objects[key]['Body'] == body for key,body in before.items())
    assert len([line for key in result['receipts'] for line in receipt(bucket,key)]) == 4
