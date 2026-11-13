"""The body-text producer: work list, file-returning workers and commit order (data model §6.6).

Each test reads back what the native engine committed to a local catalog, so the claims are
about the tables a later run plans against, not about the producer's own report.
"""
import hashlib
import json

import pyarrow.parquet as pq
import pytest

from body_text_fixtures import (HTML, PAGE_ONE, PAGE_TWO, STAMP, TABLES, XML, committed, lake, scanned_pdf,
                                two_page_pdf, warc_member)
from congress_api.lake import body_text


def test_one_run_settles_every_parser_and_leaves_ocr_bodies_listed(tmp_path):
    assert body_text.FORMAT_PARSERS == {'pdf': 'pdf_text', 'html': 'html_text', 'xml': 'xml_text'}
    bodies = dict(pdf=(two_page_pdf(), 'pdf'), scan=(scanned_pdf(), 'pdf'), html=(HTML, 'html'),
                  xml=(XML, 'xml'), warc=(warc_member(HTML), 'warc'), broken=(b'<x><y>', 'xml'),
                  zip=(b'PK\x03\x04', 'zip'))
    args, names = lake(tmp_path, bodies, gzip_stored={'html'})
    report = body_text.run(**args, work=tmp_path / 'run', execute=True)
    assert report['status'] == 'pending' and report['work_items'] == 5  # WARC envelopes and ZIP are not candidates
    [batch] = report['batches']
    assert (batch['ocr_pending'], batch['pending_reads'], batch['unreadable']) == (1, 0, 0)
    text = {names[bytes.fromhex(r['body'])]: r for r in committed(args, tmp_path / 'text', 'body_text',
            "parser,text,page_offsets,encode(text_sha256,'hex') AS sha,macos_build")}
    assert set(text) == {'pdf', 'html', 'xml'}
    assert text['pdf']['text'] == PAGE_ONE + '\n' + PAGE_TWO and text['pdf']['page_offsets'] == [0, len(PAGE_ONE) + 1]
    assert all(r['sha'] == hashlib.sha256(r['text'].encode()).hexdigest() and r['macos_build'] is None
               for r in text.values())
    rows = {names[bytes.fromhex(r['body'])]: r for r in committed(args, tmp_path / 'readings', 'readings',
            'parser,parser_version,status,error_type,text_bytes')}
    assert set(rows) == {'pdf', 'html', 'xml', 'broken'}  # the scan stays pending: no row
    assert rows['broken']['status'] == 'error' and rows['broken']['parser'] == 'xml_text'
    assert {r['parser_version'] for r in rows.values()} <= set(body_text.current_versions().values())
    assert all(rows[n]['text_bytes'] == len(text[n]['text'].encode()) for n in text)
    again = body_text.run(**args, work=tmp_path / 'again', execute=False)
    assert again['work_items'] == 1 and again['by_parser'][0]['parser'] == 'pdf_text'


def test_text_commits_first_and_a_crash_between_commits_rereads_one_body_without_a_second_text(tmp_path, monkeypatch):
    from congress_api.lake import tables
    args, names = lake(tmp_path, dict(pdf=(two_page_pdf(), 'pdf'), xml=(XML, 'xml')))
    real, order = tables.append_rows, []

    def crash_on_readings(source, *, table, **kwargs):
        order.append(table['name'])
        if table['name'] == 'readings' and order.count('readings') == 1:
            raise RuntimeError('simulated crash between the two commits')
        return real(source, table=table, **kwargs)
    monkeypatch.setattr(tables, 'append_rows', crash_on_readings)
    with pytest.raises(RuntimeError, match='between the two commits'):
        body_text.run(**args, work=tmp_path / 'first', execute=True)
    assert order == ['body_text', 'readings']
    assert len(committed(args, tmp_path / 'text-1', 'body_text', 'parser')) == 2
    assert committed(args, tmp_path / 'readings-1', 'readings', 'parser') == []
    retry = body_text.run(**args, work=tmp_path / 'retry', execute=True)
    assert retry['work_items'] == 2  # still listed: only a readings row settles a body
    appended = retry['batches'][0]['append']
    assert appended['body_text']['files'] == []  # the PK anti-join keeps the text row single
    assert sum(f['rows'] for f in appended['readings']['files']) == 2
    assert len(committed(args, tmp_path / 'text-2', 'body_text', 'parser')) == 2
    assert len(committed(args, tmp_path / 'readings-2', 'readings', 'parser')) == 2
    assert body_text.run(**args, work=tmp_path / 'settled', execute=False)['work_items'] == 0


def test_worker_returns_text_larger_than_the_supervisor_pipe_by_file(tmp_path):
    line = b'Mr. SMITH. The witness will please rise and be sworn in before the committee.\n'
    body = b'<html><body><pre>' + line * (9 * (1 << 20) // len(line)) + b'</pre></body></html>'
    assert len(body) > body_text.worker_limits()['max_output_bytes']
    args, _ = lake(tmp_path, dict(big=(body, 'html')))
    planned = body_text.plan(captures=args['captures'], engine=args['engine'], work=tmp_path / 'plan',
                             decided_at=STAMP, local_root=args['local_root'])
    staged = body_text.stage(planned, list(pq.read_table(planned['work_list']).to_pylist()),
                             engine=args['engine'], work=tmp_path / 'stage')
    [row] = pq.read_table(staged['body_text']).to_pylist()
    assert row['text'].encode() == body[len(b'<html><body><pre>'):-len(b'</pre></body></html>')]
    assert pq.read_table(staged['readings']).to_pylist()[0]['text_bytes'] > 8 << 20
    assert not (tmp_path / 'stage/texts').exists()  # staged text files leave with the stage


class Scripted:
    """An in-process worker answering each parse with the next scripted outcome."""
    script, calls = [], []

    def __init__(self, *args, **limits):
        self.limits = limits

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def parse(self, input_id, payload):
        Scripted.calls.append(json.loads(payload))
        return Scripted.script.pop(0)


def test_page_deadline_retries_once_then_decides_unreadable(tmp_path):
    args, _ = lake(tmp_path, dict(a=(two_page_pdf(), 'pdf'), b=(scanned_pdf(), 'pdf')))
    planned = body_text.plan(captures=args['captures'], engine=args['engine'], work=tmp_path / 'plan',
                             decided_at=STAMP, local_root=args['local_root'])
    items = pq.read_table(planned['work_list']).to_pylist()
    retry = dict(status='completed', value=dict(retry='page_deadline'))
    Scripted.script, Scripted.calls = [retry, retry, dict(status='completed', value=dict(pending='ocr_required'))], []
    staged = body_text.stage(planned, items, engine=args['engine'], work=tmp_path / 'stage',
                             worker_factory=Scripted, unreadable_store=args['unreadable_store'])
    assert len(Scripted.calls) == 3 and Scripted.calls[0] == Scripted.calls[1]
    assert (staged['unreadable'], staged['ocr_pending'], staged['readings_rows']) == (1, 1, 0)
    decisions = [json.loads(line) for line in (tmp_path / 'raw-provenance' / staged['unreadable_key']).read_text().splitlines()]
    assert [(d['reason'], d['parser'], d['decided_by']) for d in decisions] == [('page_deadline', 'pdf_text', 'body_text')]
    assert decisions[0]['body_sha256'] == Scripted.calls[0]['body_sha']


def test_stored_size_limit_settles_without_opening_the_body(tmp_path):
    import pyarrow as pa
    args, _ = lake(tmp_path, dict(huge=(two_page_pdf(), 'pdf')))
    table = pq.read_table(args['captures'])
    pq.write_table(table.set_column(table.schema.get_field_index('stored_bytes'), 'stored_bytes',
                                    pa.array([body_text.MAX_STORED_BYTES + 1], pa.int64())), args['captures'])
    Scripted.script, Scripted.calls = [], []
    report = body_text.run(**args, work=tmp_path / 'run', execute=True, worker_factory=Scripted)
    assert Scripted.calls == []
    [row] = committed(args, tmp_path / 'readings', 'readings', 'status,error_type')
    assert (row['status'], row['error_type']) == ('size_limit', 'stored_size_limit')
    assert report['batches'][0]['body_text_rows'] == 0


def test_explicit_recovery_reads_above_both_byte_exclusions_and_preserves_old_policy(tmp_path):
    """A real padded PDF crosses both limits; its text is unchanged and separately identified."""
    body = two_page_pdf() + b'\n' * (body_text.MAX_STORED_BYTES + 1)
    args, _ = lake(tmp_path, dict(large=(body, 'pdf')))
    plan = body_text.plan(captures=args['captures'], engine=args['engine'], work=tmp_path / 'plan',
                          decided_at=STAMP, local_root=args['local_root'])
    items = pq.read_table(plan['work_list']).to_pylist()
    with pytest.raises(ValueError, match='recovery reading versions'):
        body_text.stage(plan, items, engine=args['engine'], work=tmp_path / 'refused', recovery=True)
    versions = body_text.recovery_versions()
    plan['versions'] = versions
    for item in items:
        item['parser_version'] = versions[item['parser']]
    staged = body_text.stage(plan, items, engine=args['engine'], work=tmp_path / 'recovered', recovery=True)
    [row] = pq.read_table(staged['body_text']).to_pylist()
    assert row['text'] == PAGE_ONE + '\n' + PAGE_TWO
    assert row['parser_version'] == versions['pdf_text'] != body_text.current_versions()['pdf_text']
    [outcome] = [json.loads(line) for line in (tmp_path / 'recovered/body-outcomes.jsonl').read_text().splitlines()]
    assert outcome['reading_status'] == 'completed'
    # The remote path decodes gzip through the same hash rule, with the exclusion removed explicitly.
    import gzip
    from contextlib import nullcontext
    from unittest.mock import patch
    stored = gzip.compress(body)
    class Source:
        size = len(stored)
        def read(self, *_): return stored
        def close(self): pass
    request = dict(body_sha=hashlib.sha256(body).hexdigest(), stored_bytes=len(stored), cache=str(tmp_path),
                   remote=dict(origin='https://example.invalid', key='unused', bucket='unused', etag='"pin"', md5=None))
    with patch.object(body_text.readings, '_ReadOnceBody', return_value=Source()), \
            patch.object(body_text, '_origin_store', return_value=None), \
            patch('congress_api.lake.readings.reading_input', nullcontext):
        assert body_text._read_remote(request) is None
        assert body_text._read_remote(dict(request, unlimited_body_bytes=True)) == body


def test_batches_are_sized_by_an_upper_bound_on_their_text():
    item = lambda decoded, stored=10: dict(decoded_bytes=decoded, stored_bytes=stored)
    budget = body_text.MAX_DECODED_BYTES
    items = [item(budget // 2), item(budget // 2), item(1), item(None), item(5, body_text.MAX_STORED_BYTES + 1)]
    sizes = [len(b) for b in body_text.batches(iter(items), max_cache_bytes=budget, max_items=10)]
    assert sizes == [2, 1, 2]  # an unknown size counts the whole bound; an oversize body counts nothing
    assert [len(b) for b in body_text.batches(iter(items), max_cache_bytes=10 * budget, max_items=2)] == [2, 2, 1]
    with pytest.raises(ValueError):
        list(body_text.batches(iter(items), max_cache_bytes=11 << 30))


def test_a_page_rule_this_host_cannot_build_refuses_before_any_body_is_read(tmp_path):
    args, _ = lake(tmp_path, dict(a=(two_page_pdf(), 'pdf')))
    planned = body_text.plan(captures=args['captures'], engine=args['engine'], work=tmp_path / 'plan',
                             decided_at=STAMP, local_root=args['local_root'])
    Scripted.script, Scripted.calls = [], []
    with pytest.raises(AttributeError):
        body_text.stage(planned, pq.read_table(planned['work_list']).to_pylist(), engine=args['engine'],
                        work=tmp_path / 'stage', worker_factory=Scripted,
                        strategy='congress_api.parsers.body_text:no_such_engine')
    assert Scripted.calls == []


def test_the_work_list_runs_newest_congress_first_then_newest_capture(tmp_path):
    """Each body takes the highest Congress its captures' filenames read at the current catalog
    version; a body with none, or only at another version, falls back to its newest capture."""
    import pyarrow as pa
    from congress_api.lake import filenames
    names = ['old_congress', 'new_congress', 'no_congress', 'other_version', 'no_url', 'two_captures']
    bodies = {n: (b'<doc><p>' + n.encode() + b'</p></doc>', 'xml') for n in names}
    urls = {n: f'https://docs.house.gov/meetings/{n}.pdf' for n in names if n != 'no_url'}
    args, by_digest = lake(tmp_path, bodies, urls=urls)
    captures = pq.read_table(args['captures'])
    rows = captures.to_pylist()
    second = dict(next(r for r in rows if r['url'] == urls['two_captures']), receipt_key='receipts/again.jsonl',
                  url='https://docs.house.gov/meetings/two_captures_later.pdf')
    pq.write_table(pa.Table.from_pylist(rows + [second], schema=captures.schema), args['captures'])
    current, other = filenames.current_version(), 'f' * 64
    readings_rows = [('old_congress', current, 117), ('new_congress', current, 119), ('no_congress', current, None),
                     ('other_version', other, 120), ('two_captures', current, 116),
                     ('two_captures_later', current, 118)]
    path = tmp_path / 'filename-readings.parquet'
    pq.write_table(pa.Table.from_pylist(
        [dict(filename=n + '.pdf', source_url=f'https://docs.house.gov/meetings/{n}.pdf', catalog_version=v, congress=c)
         for n, v, c in readings_rows],
        schema=pa.schema([('filename', pa.string()), ('source_url', pa.string()), ('catalog_version', pa.string()),
                          ('congress', pa.int32())])), path)
    planned = body_text.plan(captures=args['captures'], engine=args['engine'], work=tmp_path / 'plan',
                             decided_at=STAMP, filename_readings=path)
    order = [(by_digest[r['body_sha']], r['congress']) for r in pq.read_table(planned['work_list']).to_pylist()]
    # Newest capture last in `bodies`, so the fallback runs in reverse order of insertion.
    assert order == [('new_congress', 119), ('two_captures', 118), ('old_congress', 117), ('no_url', None),
                     ('other_version', None), ('no_congress', None)]
    assert planned['with_congress'] == 3
    unordered = body_text.plan(captures=args['captures'], engine=args['engine'], work=tmp_path / 'plain',
                               decided_at=STAMP)
    assert [by_digest[r['body_sha']] for r in pq.read_table(unordered['work_list']).to_pylist()] == names[::-1]


def test_the_command_plans_and_executes_from_a_spec(tmp_path, capsys):
    from congress_api.cli import body_text as command
    args, _ = lake(tmp_path, dict(pdf=(two_page_pdf(), 'pdf'), xml=(XML, 'xml')))
    spec = dict(captures=str(args['captures']), work=str(tmp_path / 'plan'), decided_at=STAMP,
                catalog_root=str(args['catalog_root']), tables=TABLES, local_root=str(args['local_root']))
    path = tmp_path / 'spec.json'
    path.write_text(json.dumps(spec))
    assert command.main(['--spec', str(path), '--plan']) == 0
    planned = json.loads(capsys.readouterr().out)
    assert (planned['status'], planned['work_items'], planned['applied']) == ('planned', 2, False)
    path.write_text(json.dumps(dict(spec, work=str(tmp_path / 'run'))))
    assert command.main(['--spec', str(path), '--execute', '--durable-unreadable-root', str(tmp_path / 'raw')]) == 0
    done = json.loads(capsys.readouterr().out)
    assert (done['status'], done['applied']) == ('completed', True)
    assert len(committed(args, tmp_path / 'read', 'readings', 'status')) == 2
    path.write_text(json.dumps(dict(spec, work=str(tmp_path / 'both'), origin=body_text.ORIGIN)))
    with pytest.raises(SystemExit):  # exactly one body source
        command.main(['--spec', str(path), '--plan'])
    with pytest.raises(SystemExit):  # execution names its durable unreadable store
        command.main(['--spec', str(path), '--execute'])


def test_worker_memory_limit_is_2_gib_and_pool_budget_allows_16_workers_under_14_gib_engine(tmp_path, capsys):
    from congress_api.cli import body_text as command
    from docspec_client.client import NativeDatasets
    import os

    assert body_text.WORKER_MEMORY_BYTES == 2 << 30
    assert body_text.worker_limits()['memory_bytes'] == 2 << 30
    assert body_text.PARSER_MEMORY_BYTES == 32 << 30
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        engine_mem = json.loads(engine.limits.read_text())['memory_bytes']
    assert engine_mem == 14 << 30  # 14 GiB SQL engine limit must not cap body_text workers to 7

    args, _ = lake(tmp_path, dict(xml=(XML, 'xml')))
    spec = dict(captures=str(args['captures']), work=str(tmp_path / 'plan-16'), decided_at=STAMP,
                catalog_root=str(args['catalog_root']), tables=TABLES, local_root=str(args['local_root']))
    path = tmp_path / 'spec.json'
    path.write_text(json.dumps(spec))
    assert command.main(['--spec', str(path), '--plan', '--parser-workers', '16']) == 0
    capsys.readouterr()

    path.write_text(json.dumps(dict(spec, work=str(tmp_path / 'plan-17'))))
    with pytest.raises(SystemExit):  # 17 * 2 GiB > default 32 GiB pool budget
        command.main(['--spec', str(path), '--plan', '--parser-workers', '17'])

    path.write_text(json.dumps(dict(spec, work=str(tmp_path / 'plan-18'))))
    assert command.main(['--spec', str(path), '--plan', '--parser-workers', '18',
                         '--parser-memory-bytes', str(36 << 30)]) == 0
    capsys.readouterr()


def test_withdrawn_unreadable_decision_reopens_the_body_at_the_same_parser_version(tmp_path):
    from congress_api.retention.provenance import import_unreadable, validate_provenance
    from congress_api.retention.provenance_inventory import unreadable_inventory

    args, _ = lake(tmp_path, dict(pdf=(two_page_pdf(), 'pdf')))
    planned = body_text.plan(captures=args['captures'], engine=args['engine'], work=tmp_path / 'plan-0',
                             decided_at=STAMP, local_root=args['local_root'])
    items = pq.read_table(planned['work_list']).to_pylist()
    retry = dict(status='completed', value=dict(retry='page_deadline'))
    Scripted.script, Scripted.calls = [retry, retry], []
    staged = body_text.stage(planned, items, engine=args['engine'], work=tmp_path / 'stage-0',
                             worker_factory=Scripted, unreadable_store=args['unreadable_store'])
    assert staged['unreadable'] == 1
    [wrong] = [json.loads(line) for line in (tmp_path / 'raw-provenance' / staged['unreadable_key']).read_text().splitlines()]

    inv_before = unreadable_inventory(args['unreadable_store'], work=tmp_path / 'inv-before').files()
    blocked = body_text.run(**args, work=tmp_path / 'blocked', unreadable_files=inv_before, execute=False)
    assert blocked['work_items'] == 0

    withdrawal = dict(
        id=hashlib.sha256(f"withdraw:{wrong['id']}".encode()).hexdigest(),
        body_sha256=wrong['body_sha256'],
        parser=wrong['parser'],
        parser_version=wrong['parser_version'],
        reason='withdrawn',
        decided_by='ct-a73a',
        decided_at='2026-11-12T00:00:00Z',
        supersedes=wrong['id'],
    )
    with pytest.raises(ValueError, match='Invalid unreadable'):
        validate_provenance('unreadable', dict(withdrawal, supersedes=None))

    withdraw_path = tmp_path / 'withdraw.jsonl'
    withdraw_path.write_text(json.dumps(withdrawal, separators=(',', ':')) + '\n')
    import_unreadable(args['unreadable_store'], withdraw_path, decided_at='2026-11-12T00:00:00Z')

    reopened = body_text.run(**args, work=tmp_path / 'reopened', execute=True)
    assert (reopened['status'], reopened['work_items'], reopened['applied']) == ('completed', 1, True)
    [row] = committed(args, tmp_path / 'text-after', 'body_text', 'parser,parser_version,text')
    assert row['parser'] == 'pdf_text' and row['parser_version'] == wrong['parser_version']
    assert row['text'] == PAGE_ONE + '\n' + PAGE_TWO


def test_stage_records_per_body_peak_rss_and_error_outcomes(tmp_path):
    """[BLOCKER-2] stage() records per-body status, reason, error, and measured peak_rss_bytes."""
    args, names = lake(tmp_path, dict(pdf=(two_page_pdf(), 'pdf'), broken=(b'<x><y>', 'xml')))
    planned = body_text.plan(captures=args['captures'], engine=args['engine'], work=tmp_path / 'plan',
                             decided_at=STAMP, local_root=args['local_root'])
    staged = body_text.stage(planned, pq.read_table(planned['work_list']).to_pylist(),
                             engine=args['engine'], work=tmp_path / 'stage',
                             unreadable_store=args['unreadable_store'])
    by_name = {names[bytes.fromhex(o['body_sha256'])]: o for o in staged['body_outcomes']}
    assert set(by_name) == {'pdf', 'broken'}
    assert by_name['pdf']['status'] == 'read' and by_name['pdf']['reading_status'] == 'completed'
    assert isinstance(by_name['pdf']['peak_rss_bytes'], int) and by_name['pdf']['peak_rss_bytes'] > 0
    assert by_name['broken']['status'] == 'read' and by_name['broken']['reading_status'] == 'error'
    assert by_name['broken']['error'] is not None
    assert isinstance(by_name['broken']['peak_rss_bytes'], int) and by_name['broken']['peak_rss_bytes'] > 0


def test_retry_unreadable_script_dry_run_live_guard_and_idempotent_resume(tmp_path, monkeypatch):
    """[BLOCKER-2] scripts/retry_unreadable_body_text.py handles dry-run, live-writer guard, and idempotent resume."""
    import importlib.util
    from pathlib import Path
    import subprocess
    from congress_api.retention.provenance import import_unreadable

    script_path = Path(__file__).resolve().parents[3] / 'scripts' / 'retry_unreadable_body_text.py'
    assert script_path.is_file(), f'Missing {script_path}'
    spec = importlib.util.spec_from_file_location('retry_unreadable_body_text', script_path)
    retry_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(retry_mod)

    args, names = lake(tmp_path, dict(a=(two_page_pdf(), 'pdf'), b=(HTML, 'html')))
    digests = {name: digest.hex() for digest, name in names.items()}
    vers = body_text.current_versions()
    wrong_rows = [
        dict(id='1' * 64, body_sha256=digests['a'], parser='pdf_text', parser_version=vers['pdf_text'],
             reason='page_deadline', decided_by='body_text', decided_at='2026-11-09T19:00:00Z', supersedes=None),
        dict(id='2' * 64, body_sha256=digests['b'], parser='html_text', parser_version=vers['html_text'],
             reason='memory_limit', decided_by='body_text', decided_at='2026-11-09T19:00:00Z', supersedes=None),
    ]
    wrong_jsonl = tmp_path / 'wrong.jsonl'
    wrong_jsonl.write_text(''.join(json.dumps(r) + '\n' for r in wrong_rows))
    import_unreadable(args['unreadable_store'], wrong_jsonl, decided_at='2026-11-09T19:00:00Z')

    unr_root = tmp_path / 'raw-provenance'
    common = [
        '--unreadable-root', str(unr_root),
        '--catalog-root', str(args['catalog_root']),
        '--captures', str(args['captures']),
        '--local-root', str(args['local_root']),
        '--strategy', 'congress_api.parsers.body_text:native_only',
    ]

    # 1. Dry-run leaves unreadable-store untouched and proves 0 -> 2 targeted items.
    dry_dir = tmp_path / 'dry-work'
    assert retry_mod.main([*common, '--dry-run', '--work-dir', str(dry_dir)]) == 0
    dry_summary = json.loads((dry_dir / 'dry-run-summary.json').read_text())
    assert dry_summary['targeted_work_items_before_withdraw'] == 0
    assert dry_summary['targeted_work_items_after_withdraw'] == 2
    assert len(list((unr_root / 'provenance/unreadable').glob('*.jsonl'))) == 1

    # 2. Live-writer preflight refuses --apply when a writer is active unless --allow-concurrent is passed.
    real_run = subprocess.run
    pgrep_stdout = '55948 python bt_full_driver.py\n'

    def fake_pgrep(cmd, *p_args, **p_kwargs):
        if cmd and cmd[0] == 'pgrep':
            return subprocess.CompletedProcess(cmd, 0 if pgrep_stdout else 1, stdout=pgrep_stdout, stderr='')
        return real_run(cmd, *p_args, **p_kwargs)

    monkeypatch.setattr(subprocess, 'run', fake_pgrep)
    with pytest.raises(RuntimeError, match='bt_full_driver'):
        retry_mod.main([*common, '--apply', '--work-dir', str(tmp_path / 'blocked-apply')])

    # Also verify --body-listing passthrough in remote --dry-run mode.
    import pyarrow as pa
    listing_rows = []
    for digest_hex in digests.values():
        f = next(args['local_root'].glob(f'bodies/sha256/*/{digest_hex}*'))
        raw_bytes = f.read_bytes()
        listing_rows.append({
            'key': f.relative_to(args['local_root']).as_posix(),
            'size': len(raw_bytes),
            'etag': '"' + hashlib.md5(raw_bytes).hexdigest() + '"',
        })
    listing_path = tmp_path / 'listing.parquet'
    pq.write_table(pa.Table.from_pylist(listing_rows, schema=body_text.LISTING_SCHEMA), listing_path)
    remote_dry_dir = tmp_path / 'remote-dry-work'
    assert retry_mod.main([
        '--unreadable-root', str(unr_root),
        '--catalog-root', str(args['catalog_root']),
        '--captures', str(args['captures']),
        '--origin', 'https://example.invalid',
        '--body-listing', str(listing_path),
        '--dry-run',
        '--work-dir', str(remote_dry_dir),
    ]) == 0
    assert json.loads((remote_dry_dir / 'dry-run-summary.json').read_text())['targeted_work_items_after_withdraw'] == 2

    # 3. Partial --apply (body 'b' missing on disk -> pending_reads == 1) then idempotent resume on same --work-dir!
    pgrep_stdout = ''
    b_file = next(args['local_root'].glob(f"bodies/sha256/*/{digests['b']}*"))
    saved_b_bytes = b_file.read_bytes()
    b_file.unlink()

    apply_dir = tmp_path / 'apply-work'
    assert retry_mod.main([*common, '--apply', '--workers', '1', '--decided-at', '2026-11-12T01:00:00Z',
                           '--work-dir', str(apply_dir)]) == 0
    first = json.loads((apply_dir / 'apply-summary.json').read_text())
    by_sha_1 = {o['body_sha256']: o for o in first['outcomes']}
    assert by_sha_1[digests['a']]['status'] == 'read'
    assert by_sha_1[digests['a']]['peak_rss_bytes'] > 0
    assert by_sha_1[digests['b']]['status'] == 'pending'

    # Restore body 'b' and re-run --apply on the EXACT SAME --work-dir (also checking --allow-concurrent when pgrep is non-empty):
    pgrep_stdout = '55948 python bt_full_driver.py\n'
    b_file.write_bytes(saved_b_bytes)
    assert retry_mod.main([*common, '--apply', '--allow-concurrent', '--workers', '1',
                           '--decided-at', '2026-11-12T01:05:00Z', '--work-dir', str(apply_dir)]) == 0
    second = json.loads((apply_dir / 'apply-summary.json').read_text())
    assert second['withdrawn_count'] == 0
    by_sha_2 = {o['body_sha256']: o for o in second['outcomes']}
    assert by_sha_2[digests['a']]['status'] == 'read'
    assert by_sha_2[digests['a']]['peak_rss_bytes'] > 0
    assert by_sha_2[digests['b']]['status'] == 'read'
    assert by_sha_2[digests['b']]['peak_rss_bytes'] > 0


