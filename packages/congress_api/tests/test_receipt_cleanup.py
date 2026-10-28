"""B0: permit exactly the named cleanup, including interrupted conditional rewrites."""
import gzip
import hashlib
import json
from pathlib import Path
import pytest


def encode(rows):
    return gzip.compress(b''.join(json.dumps(x).encode() + b'\n' for x in rows), mtime=0)


class Files:
    """Injected file transfer with compare-and-swap and create-only backup semantics."""
    def __init__(self, objects=None):
        self.objects, self.puts = objects or {}, []

    def get_file(self, key, path):
        if key not in self.objects:
            return None
        data = self.objects[key]
        path.write_bytes(data)
        return dict(size=len(data), etag=hashlib.md5(data).hexdigest())

    def put_file(self, key, path, *, if_match=None, create_only=False):
        if create_only and key in self.objects:
            raise ValueError('existing backup')
        if if_match is not None:
            assert key in self.objects
            assert hashlib.md5(self.objects[key]).hexdigest() == if_match
        assert create_only or if_match is not None
        self.puts.append((key, if_match, create_only))
        self.objects[key] = path.read_bytes()


def test_named_cleanup_is_recursive_and_keeps_other_values():
    from congress_api.retention.receipt_privacy import clean_older_line
    source = dict(record=dict(
        response_headers={'Set-Cookie': 'private', 'AUTHORIZATION': 'private', 'etag': 'keep'},
        nested=[{'name': 'x-archive-orig-set-cookie', 'value': 'private', 'extra': 7},
                ['Cookie', 'private']],
        body_path='/private/tmp/a/b/document.pdf',
        error='cannot open /Users/example/cache/doc.xml; retry',
        windows='C:\\Users\\example\\doc.pdf',
        url='https://example.gov/home/reports/a.pdf?x=1',
        links=[{'url': 'https://example.gov/a', 'text': 'keep'}]),
        captures=[{'pointer': ['content', 'body']}])
    source['record']['content'] = dict(body=None, sha256='a' * 64)
    cleaned, cuts = clean_older_line(source)
    assert source['record']['response_headers']['Set-Cookie'] == 'private'
    assert cleaned['record'] == dict(response_headers={'etag': 'keep'},
        nested=[{'name': 'x-archive-orig-set-cookie', 'extra': 7}, ['Cookie', None]],
        body_path='document.pdf', error='cannot open doc.xml; retry', windows='doc.pdf',
        url=source['record']['url'], links=source['record']['links'],
        content=source['record']['content'])
    assert sum(n for (kind, _, _), n in cuts.items() if kind == 'header') == 4
    assert sum(n for (kind, _, _), n in cuts.items() if kind == 'path') == 3


def test_urls_embedded_in_error_text_and_link_values_never_change():
    from congress_api.retention.receipt_privacy import clean_older_line
    row = {'error': 'failed at https://example.gov/home/x.pdf after /tmp/read/x.pdf',
           'links': ['https://example.gov/private/x.pdf']}
    cleaned, _ = clean_older_line(row)
    assert cleaned == dict(error='failed at https://example.gov/home/x.pdf after x.pdf',
                          links=row['links'])


def test_path_keys_are_cut_except_keys_a_pointer_uses():
    from congress_api.retention.receipt_privacy import clean_older_line
    row = dict(record={'/tmp/a.json': {'body': None}, '/tmp/b.json': 2},
               captures=[{'pointer': ['/tmp/a.json', 'body']}])
    cleaned, cuts = clean_older_line(row)
    assert cleaned['record'] == {'/tmp/a.json': {'body': None}, 'b.json': 2}
    assert any(kind == 'protected_path' for kind, _, _ in cuts)


def test_basename_collisions_are_refused():
    from congress_api.retention.receipt_privacy import clean_older_line
    with pytest.raises(ValueError, match='collision'):
        clean_older_line({'/tmp/a/item': 1, '/tmp/b/item': 2})


def test_rewrite_backs_up_then_cas_then_verifies_and_records(tmp_path):
    from congress_api.retention.receipt_cleanup import rewrite_receipt
    key = 'receipts/documents/2026-10-01/run.jsonl.gz'
    untouched = b'{ "url": "https://example.gov/a.pdf", "keep": 2 }\n'
    raw = gzip.compress(untouched + b'{"headers":{"Set-Cookie":"private"},"path":"/tmp/a.pdf"}\n', mtime=0)
    live, backup, recorded = Files({key: raw}), Files(), []
    result = rewrite_receipt(live, backup, key, scratch=tmp_path, record=recorded.append)
    assert backup.objects[key] == raw
    assert live.puts == [(key, hashlib.md5(raw).hexdigest(), False)]
    lines = gzip.decompress(live.objects[key]).splitlines(keepends=True)
    assert lines[0] == untouched
    assert json.loads(lines[1]) == dict(headers={}, path='a.pdf')
    assert recorded == [result] and result['backup_object'] == key
    assert result['original_etag'] == hashlib.md5(raw).hexdigest()
    assert result['cookies_removed'] == 1 and result['paths_removed'] == 1
    assert result['credential_parameters_removed'] == 0
    assert result['verified'] is True
    # A verified rerun transfers nothing and performs no second rewrite.
    assert rewrite_receipt(live, backup, key, scratch=tmp_path, verified=result) == result
    assert len(live.puts) == 1


def test_crash_after_write_resumes_from_the_immutable_backup(tmp_path):
    from congress_api.retention.receipt_cleanup import rewrite_receipt
    key = 'receipts/documents/undated/old.jsonl.gz'
    original = encode([{'path': '/tmp/a.pdf'}])
    live, backup = Files({key: original}), Files()
    def crash(result):
        raise RuntimeError('lost after rewrite')
    with pytest.raises(RuntimeError, match='lost'):
        rewrite_receipt(live, backup, key, scratch=tmp_path, record=crash)
    result = rewrite_receipt(live, backup, key, scratch=tmp_path)
    assert result['verified'] is True and len(live.puts) == 1
    assert backup.objects[key] == original


def test_no_match_records_result_without_rewriting(tmp_path):
    from congress_api.retention.receipt_cleanup import rewrite_receipt
    key = 'receipts/family/undated/run.jsonl.gz'
    original = encode([{'url': 'https://example.gov/a'}])
    live, backup = Files({key: original}), Files()
    result = rewrite_receipt(live, backup, key, scratch=tmp_path)
    assert result['changed'] is False and result['verified'] is True
    assert not live.puts and not backup.puts


def test_changed_live_object_is_never_rebased_or_overwritten(tmp_path):
    from congress_api.retention.receipt_cleanup import rewrite_receipt
    key = 'receipts/family/undated/run.jsonl.gz'
    backup = Files({key: encode([{'path': '/tmp/original'}])})
    live = Files({key: encode([{'path': '/tmp/different'}])})
    with pytest.raises(ValueError, match='changed'):
        rewrite_receipt(live, backup, key, scratch=tmp_path)
    assert not live.puts and not backup.puts


def test_cleaner_never_changes_urls_links_or_pointer_targets():
    from congress_api.retention.receipt_cleanup import verify_line
    row = {'record': {'content': {'body': None}, 'url': 'https://example.gov/a',
                      'links': ['keep']}, 'captures': [{'pointer': ['content', 'body']}]}
    for bad in [dict(row, record=dict(row['record'], url='https://example.gov/b')),
                dict(row, record=dict(row['record'], links=[])),
                dict(row, record=dict(row['record'], content={'body': 'changed'}))]:
        with pytest.raises(ValueError):
            verify_line(row, bad)


def test_local_command_scan_apply_and_resume_use_the_same_rules(tmp_path, capsys):
    from congress_api.cli.receipt_cleanup import main
    root, backup, scratch = (tmp_path / name for name in ('local', 'backup', 'scratch'))
    key = 'receipts/documents/2026-10-01/run.jsonl.gz'
    path = root / key
    path.parent.mkdir(parents=True)
    raw = encode([{'response_headers': {'authorization': 'never-report-this'},
                   'path': '/tmp/a.pdf', 'url': 'https://example.gov/a.pdf'}])
    path.write_bytes(raw)
    report, records = tmp_path / 'report.json', tmp_path / 'records.jsonl'
    main(['--root', str(root), '--report', str(report)])
    scan = json.loads(report.read_text())
    assert scan['receipts'] == 1 and scan['lines'] == 1
    assert scan['counts'] == dict(header=1, path=1)
    assert 'never-report-this' not in report.read_text() + capsys.readouterr().out
    args = ['--root', str(root), '--report', str(report), '--apply',
            '--backup-root', str(backup), '--scratch', str(scratch), '--records', str(records)]
    assert main(args) == 0
    assert (backup / key).read_bytes() == raw
    first = path.read_bytes()
    assert main(args) == 0
    assert path.read_bytes() == first and len(records.read_text().splitlines()) == 1
    main(['--root', str(root), '--report', str(report)])
    assert json.loads(report.read_text())['counts'] == {}


def test_local_adapter_refuses_stale_cas_and_backup_overwrite(tmp_path):
    from congress_api.retention.receipt_cleanup_stores import DirectoryFiles
    store = DirectoryFiles(tmp_path / 'store')
    key, source = 'receipts/family/undated/run.jsonl.gz', tmp_path / 'input'
    source.write_bytes(b'original')
    store.put_file(key, source, create_only=True)
    with pytest.raises(FileExistsError):
        store.put_file(key, source, create_only=True)
    source.write_bytes(b'changed')
    with pytest.raises(ValueError, match='race'):
        store.put_file(key, source, if_match='0' * 32)
    assert store.path(key).read_bytes() == b'original'
    with pytest.raises(ValueError):
        store.put_file('receipts/../../escape', source, create_only=True)


def test_r2_rewriter_adapter_uses_only_single_conditional_put(tmp_path):
    from congress_api.retention.receipt_cleanup_stores import R2ReceiptFiles
    import base64
    class Client:
        def __init__(self):
            self.calls = []
        def put_object(self, **args):
            self.calls.append(args)
            payload = args['Body'].read()
            assert base64.b64decode(args['ContentMD5']) == hashlib.md5(payload).digest()
            assert args['IfMatch'] == 'old-etag'
            assert args['ContentLength'] == len(payload)
            assert 'IfNoneMatch' not in args
            return dict(ETag='"'+hashlib.md5(payload).hexdigest()+'"')
    client = Client()
    store = R2ReceiptFiles(client, 'fixture')
    source = tmp_path / 'file'
    source.write_bytes(b'content')
    for key in ('bodies/x', 'provenance/x'):
        with pytest.raises(ValueError):
            store.put_file(key, source, if_match='old-etag')
    assert client.calls == []
    store.put_file('receipts/family/undated/run.jsonl.gz', source, if_match='old-etag')
    assert len(client.calls) == 1


def test_scan_groups_paths_and_bounds_examples_per_field(tmp_path):
    from congress_api.cli.receipt_cleanup import scan
    root = tmp_path
    key = 'receipts/family/undated/run.jsonl.gz'
    path = root / key
    path.parent.mkdir(parents=True)
    path.write_bytes(encode([{'path': f'/tmp/source/{i}.pdf'} for i in range(10)]))
    report = scan(root, [key])
    assert len(report['fields']) == 1
    [field] = report['fields']
    assert field['path'] == 'path' and field['count'] == 10
    assert len(field['examples']) == 3


def test_owner_inventory_lists_all_receipt_prefixes_without_writes():
    from congress_api.cli.receipt_cleanup import receipt_inventory
    class Paginator:
        def paginate(self, **kwargs):
            assert kwargs == dict(Bucket='raw', Prefix='receipts/')
            yield {'Contents': [{'Key': 'receipts/b/undated/old.jsonl.gz', 'Size': 2, 'ETag': '"bb"'}]}
            yield {'Contents': [{'Key': 'receipts/a/2026-10-27/new.jsonl.gz', 'Size': 3, 'ETag': '"aa"'}]}
    class Client:
        def get_paginator(self, name):
            assert name == 'list_objects_v2'
            return Paginator()
    result = receipt_inventory(Client(), 'raw')
    assert result == [dict(key='receipts/a/2026-10-27/new.jsonl.gz', size=3, etag='aa'),
                      dict(key='receipts/b/undated/old.jsonl.gz', size=2, etag='bb')]


def test_owner_final_rescan_reads_every_live_receipt_through_local_copies(tmp_path):
    from congress_api.cli.receipt_cleanup import scan_live
    key = 'receipts/family/undated/run.jsonl.gz'
    store = Files({key: encode([{'url': 'https://example.gov/a', 'headers': {'etag': 'keep'}}])})
    report = scan_live(store, tmp_path / 'mirror', [key])
    assert report['receipts'] == 1 and report['lines'] == 1 and report['counts'] == {}
    assert (tmp_path / 'mirror' / key).read_bytes() == store.objects[key]
    assert store.puts == []
