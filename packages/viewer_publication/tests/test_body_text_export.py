"""The body_text export: one row per saved body, bounded text, and its create-only publication.

The export runs on the native engine (DataFusion, the engine that runs it in production); DuckDB
then reads the written Parquet as an independent check, so the bound and the row rule are
judged by a second SQL engine's JSON writer rather than by the export's own arithmetic.
"""
from hashlib import md5, sha256
import json
import os

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake import body_text, readings
from docspec_client.client import NativeDatasets
from viewer_publication import body_text_export as export

VERSIONS = body_text.current_versions()
LONG = 'Mr. CHAIRMAN. ' + 'The "witness" said \\ yes.\x01\n' * 40  # quotes, a backslash and controls
TEXTS = dict(short='Opening statement.', long=LONG, unicode='Café ✓ 𝄞 testimony.', old='old version only',
             unsaved='not shown by the release', warc='From an envelope.')


def digest(name):
    return sha256(name.encode()).digest()


def stage(tmp_path):
    rows = []
    for name, text in TEXTS.items():
        parser = 'warc' if name == 'warc' else 'pdf_text'
        version = 'retired-version' if name == 'old' else VERSIONS[parser]
        rows.append(dict(body_sha=digest(name), parser=parser, parser_version=version, text=text,
                         page_offsets=[0, 10] if name == 'long' else [0], ocr_pages=[2] if name == 'short' else [],
                         text_sha256=sha256(text.encode()).digest(), macos_build=None))
    # The same body under a retired version too: the export must keep only the declared one.
    rows.append(dict(rows[0], parser_version='retired-version', text='stale'))
    path = tmp_path / 'body-text.parquet'
    pq.write_table(pa.Table.from_pylist(rows, schema=body_text._text_schema()), path)
    detail = tmp_path / 'detail.parquet'
    saved = [digest(n) for n in ('short', 'long', 'unicode', 'old', 'warc')] + [digest('short'), None]
    pq.write_table(pa.table({'saved_body': pa.array(saved, pa.binary(32)),
                             'filename': [f'doc-{i}.pdf' for i in range(len(saved))]}), detail)
    return path, detail


def run(tmp_path, bound):
    path, detail = stage(tmp_path)
    definition = dict(export.load_definition(), max_text_json_bytes=bound)
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    pointer = export.export(engine=engine, work=tmp_path / 'export', body_text=path, detail=detail,
                            definition=definition, versions=VERSIONS, release_id='r' * 64)
    return pointer, tmp_path / 'export/export.parquet'


def json_len(column):
    return f'strlen(to_json({column})::VARCHAR)'


def test_one_row_per_saved_body_at_the_declared_version_ordered_with_small_groups(tmp_path):
    pointer, output = run(tmp_path, 1 << 20)
    names = {digest(n): n for n in TEXTS}
    table = pq.read_table(output)
    assert table.column_names == export.COLUMNS
    rows = table.to_pylist()
    assert [names[r['saved_body']] for r in rows] == sorted(['short', 'long', 'unicode', 'warc'], key=digest)
    assert {names[r['saved_body']]: r['text'] for r in rows} == {n: TEXTS[n] for n in ('short', 'long', 'unicode', 'warc')}
    metadata = pq.ParquetFile(output).metadata
    assert metadata.num_row_groups == 1 and metadata.row_group(0).num_rows == 4
    assert pointer['rows'] == 4 and pointer['bytes'] == output.stat().st_size
    assert pointer['sha256'] == sha256(output.read_bytes()).hexdigest()
    assert pointer['key'] == 'derived/body_text/' + pointer['sha256'] + '.parquet'
    coverage = pointer['coverage']
    assert (coverage['saved_bodies'], coverage['ocr_pages'], coverage['truncated'], coverage['warc_unwrapped']) == (5, 1, 0, 1)
    assert coverage['bodies_with_text'] == {'pdf_text': 3, 'warc': 1}
    assert json.loads((tmp_path / 'export/current.json').read_text()) == pointer
    tail = output.read_bytes()
    size = int.from_bytes(tail[-8:-4], 'little') + 8
    assert pointer['footer_sha256'] == sha256(tail[-size:]).hexdigest()


def test_export_json_length_agrees_with_duckdb_and_truncation_fits_the_bound(tmp_path):
    bound = 400
    pointer, output = run(tmp_path, bound)
    exported = [TEXTS[n] for n in ('short', 'long', 'unicode', 'warc')]
    widest_lake = max(duckdb.sql("SELECT strlen(to_json(?::VARCHAR)::VARCHAR)", params=[t]).fetchone()[0]
                      for t in exported)
    assert pointer['coverage']['max_json_bytes'] == widest_lake > bound  # the SQL's count is DuckDB's
    by_parser = pointer['coverage']
    assert by_parser['truncated'] == 1
    checked = duckdb.sql(f"""SELECT count(*) AS n, count(DISTINCT saved_body) AS bodies,
        max({json_len('text')}) AS widest, bool_and(lower(hex(text_sha256))=sha256(text)) AS hashes
        FROM read_parquet('{output}')""").fetchone()
    assert checked[0] == checked[1] == 4 and checked[2] <= bound and checked[3]
    cut = {r['saved_body']: r['text'] for r in pq.read_table(output).to_pylist()}[digest('long')]
    assert LONG.startswith(cut) and len(cut) < len(LONG)
    assert len(cut) > (bound - 2) // 6  # the proportional cut kept more than the worst-case floor


@pytest.mark.parametrize('bound', [64, 97])
def test_tight_bounds_fall_back_to_the_guaranteed_prefix(tmp_path, bound):
    _, output = run(tmp_path, bound)
    widest = duckdb.sql(f"SELECT max({json_len('text')}) FROM read_parquet('{output}')").fetchone()[0]
    assert widest <= bound


class Bucket:
    """An in-memory S3 subset: conditional completion and pointer PUTs, paged listing, deletes.

    Each write stamps the object with the next tick of a counter, as LastModified."""
    def __init__(self, page_size=1000):
        self.objects, self.uploads, self.calls, self.page_size, self.clock = {}, {}, [], page_size, 0

    def _store(self, key, body, etag):
        self.clock += 1
        self.objects[key] = dict(body=body, etag=etag, modified=self.clock)

    def create_multipart_upload(self, Bucket, Key, ContentType, CacheControl):
        self.calls.append(('create', Key, ContentType))
        self.uploads['u1'] = []
        return dict(UploadId='u1')

    def upload_part(self, Bucket, Key, UploadId, PartNumber, Body, ContentLength, ContentMD5):
        self.uploads[UploadId].append(Body)
        return dict(ETag='"' + md5(Body).hexdigest() + '"')

    def complete_multipart_upload(self, Bucket, Key, UploadId, MultipartUpload, IfNoneMatch):
        self.calls.append(('complete', Key, IfNoneMatch))
        parts = self.uploads.pop(UploadId)
        etag = md5(b''.join(md5(p).digest() for p in parts)).hexdigest() + '-' + str(len(parts))
        if Key in self.objects:
            error = RuntimeError('precondition')
            error.response = {'ResponseMetadata': {'HTTPStatusCode': 412}}
            raise error
        self._store(Key, b''.join(parts), etag)
        return dict(ETag='"' + etag + '"')

    def abort_multipart_upload(self, Bucket, Key, UploadId):
        self.calls.append(('abort', Key))

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            error = RuntimeError('not found')
            error.response = {'Error': {'Code': '404'}}
            raise error
        value = self.objects[Key]
        return dict(ContentLength=len(value['body']), ETag='"' + value['etag'] + '"')

    def put_object(self, Bucket, Key, Body, ContentLength, ContentType, CacheControl, **condition):
        self.calls.append(('put', Key, condition))
        self._store(Key, Body, md5(Body).hexdigest())
        return dict(ETag='"' + md5(Body).hexdigest() + '"')

    def get_object(self, Bucket, Key):
        import io
        value = self.objects[Key]
        return dict(Body=io.BytesIO(value['body']), LastModified=value['modified'], ETag='"' + value['etag'] + '"')

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        start = int(ContinuationToken or 0)
        page = keys[start:start + self.page_size]
        more = start + self.page_size < len(keys)
        return dict(Contents=[dict(Key=k, LastModified=self.objects[k]['modified'], Size=len(self.objects[k]['body']))
                              for k in page], IsTruncated=more,
                    **(dict(NextContinuationToken=str(start + self.page_size)) if more else {}))

    def delete_object(self, Bucket, Key):
        self.calls.append(('delete', Key))
        del self.objects[Key]


def test_publish_is_create_only_for_the_export_and_conditional_for_the_pointer(tmp_path):
    pointer, output = run(tmp_path, 1 << 20)
    bucket, stages = Bucket(), []
    first = export.publish(bucket, bucket='archive', export_path=output, pointer=pointer,
                           expected_pointer_etag=None, journal=stages.append)
    assert first['export'] == 'created' and stages[-1]['stage'] == 'completed'
    assert ('complete', pointer['key'], '*') in bucket.calls
    assert bucket.objects[pointer['key']]['body'] == output.read_bytes()
    assert ('put', 'derived/body_text/current.json', {'IfNoneMatch': '*'}) in bucket.calls
    again = export.publish(bucket, bucket='archive', export_path=output, pointer=pointer,
                           expected_pointer_etag=first['pointer'].etag, journal=stages.append)
    assert again['export'] == 'already_exists'  # verified against the existing object's identity
    assert ('put', 'derived/body_text/current.json', {'IfMatch': first['pointer'].etag}) in bucket.calls
    bucket.objects[pointer['key']]['body'] = b'other bytes'
    with pytest.raises(ValueError, match='other bytes'):
        export.publish(bucket, bucket='archive', export_path=output, pointer=pointer,
                       expected_pointer_etag=None, journal=stages.append)
    with pytest.raises(ValueError, match='differ from the pointer'):
        export.publish(bucket, bucket='archive', export_path=output, pointer=dict(pointer, bytes=1),
                       expected_pointer_etag=None, journal=stages.append)


def test_row_groups_hold_the_declared_row_count(tmp_path):
    names = [f'body-{i}' for i in range(300)]
    rows = [dict(body_sha=digest(n), parser='html_text', parser_version=VERSIONS['html_text'], text=n,
                 page_offsets=[0], ocr_pages=[], text_sha256=sha256(n.encode()).digest(), macos_build=None)
            for n in names]
    path, detail = tmp_path / 'body-text.parquet', tmp_path / 'detail.parquet'
    pq.write_table(pa.Table.from_pylist(rows, schema=body_text._text_schema()), path)
    pq.write_table(pa.table({'saved_body': pa.array([digest(n) for n in names], pa.binary(32))}), detail)
    pointer = export.export(engine=NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']), work=tmp_path / 'export',
                            body_text=path, detail=detail, versions=VERSIONS)
    metadata = pq.ParquetFile(tmp_path / 'export/export.parquet').metadata
    assert [metadata.row_group(i).num_rows for i in range(metadata.num_row_groups)] == [256, 44]
    saved = pq.read_table(tmp_path / 'export/export.parquet', columns=['saved_body']).column(0).to_pylist()
    assert saved == sorted(saved) and pointer['rows'] == 300


def test_the_command_plans_builds_and_publishes_with_a_pointer_compare_and_swap(tmp_path, capsys):
    path, detail = stage(tmp_path)
    spec = tmp_path / 'spec.json'

    def command(work, *flags, client=None):
        spec.write_text(json.dumps(dict(body_text=str(path), detail=str(detail), work=str(tmp_path / work))))
        assert export.main(['--spec', str(spec), *flags], client=client) == 0
        return json.loads(capsys.readouterr().out)

    planned = command('first', '--plan')
    assert (planned['status'], planned['executed']) == ('planned', False) and not (tmp_path / 'first').exists()
    bucket = Bucket()
    first = command('first', '--execute', '--publish', client=bucket)
    assert first['status'] == 'published' and first['published']['export'] == 'created'
    assert ('put', 'derived/body_text/current.json', {'IfNoneMatch': '*'}) in bucket.calls
    assert json.loads((tmp_path / 'first/upload-journal.json').read_text())['stage'] == 'completed'
    pointer_etag = bucket.head_object(Bucket='archive', Key='derived/body_text/current.json')['ETag']
    second = command('second', '--execute', '--publish', client=bucket)  # the same export again
    assert second['published']['export'] == 'already_exists'
    assert ('put', 'derived/body_text/current.json', {'IfMatch': pointer_etag}) in bucket.calls
    with pytest.raises(SystemExit):
        export.main(['--spec', str(spec), '--plan', '--publish'])


def test_publishing_keeps_only_the_export_the_current_pointer_names(tmp_path):
    pointer, output = run(tmp_path, 1 << 20)
    bucket = Bucket(page_size=2)  # several listing pages
    prefix = 'derived/body_text/'
    old = [prefix + sha256(str(i).encode()).hexdigest() + '.parquet' for i in range(3)]
    for key in old:
        bucket._store(key, b'an earlier export', md5(b'an earlier export').hexdigest())
    for key in (prefix + 'notes.txt', prefix + 'staging/' + 'a' * 64 + '.parquet', 'derived/other/x.parquet'):
        bucket._store(key, b'not an export', md5(b'not an export').hexdigest())
    first = export.publish(bucket, bucket='archive', export_path=output, pointer=pointer,
                           expected_pointer_etag=None, journal=lambda stage: None)
    assert sorted(first['retired']) == sorted(old)
    assert [c for c in bucket.calls if c[0] == 'delete'] == [('delete', k) for k in first['retired']]
    assert pointer['key'] in bucket.objects and prefix + 'current.json' in bucket.objects
    assert {prefix + 'notes.txt', prefix + 'staging/' + 'a' * 64 + '.parquet', 'derived/other/x.parquet'} <= set(bucket.objects)
    # Another publisher's export, uploaded after the pointer last moved, waits for its own pointer move.
    pending = prefix + 'b' * 64 + '.parquet'
    bucket._store(pending, b'next export', md5(b'next export').hexdigest())
    assert export.retire_unnamed(bucket, bucket='archive', prefix=prefix, pointer_key=prefix + 'current.json') == []
    # Once the pointer names it, the earlier one goes and the named one stays.
    bucket._store(prefix + 'current.json', json.dumps(dict(pointer, key=pending)).encode(), 'p')
    assert export.retire_unnamed(bucket, bucket='archive', prefix=prefix, pointer_key=prefix + 'current.json') \
        == [pointer['key']]
    assert pending in bucket.objects and pointer['key'] not in bucket.objects
