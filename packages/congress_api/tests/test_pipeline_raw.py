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
    """A local object store with R2's create-only PUT; it has no HEAD or GET."""

    def __init__(self):
        self.meta = SimpleNamespace(config=SimpleNamespace(retries={}),
                                    events=SimpleNamespace(register_first=lambda *a, **k: None))
        self.objects, self.puts = {}, []

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
