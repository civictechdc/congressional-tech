"""The body-text producer: work list, file-returning workers and commit order (data model §6.6).

Each test reads back what the native engine committed to a local catalog, so the claims are
about the tables a later run plans against, not about the producer's own report.
"""
import hashlib
import json
import os

import pyarrow.parquet as pq
import pytest

from body_text_fixtures import HTML, PAGE_ONE, PAGE_TWO, XML, raw_inputs, scanned_pdf, two_page_pdf, warc_member
from congress_api.lake import body_text, readings
from congress_api.lake.tables import resolve_tables, table_input
from congress_api.retention.body_store import BodyStore, LocalAdapter
from congress_api.retention.provenance import run_job
from docspec_client.client import NativeDatasets

STAMP = '2026-11-08T12:00:00Z'
TABLES = dict(readings=dict(namespace=['archive'], name='readings'),
              body_text=dict(namespace=['archive'], name='body_text'))


def lake(tmp_path, bodies, **kwargs):
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    captures, _, raw, digests = raw_inputs(tmp_path / 'source', bodies,
                                           sniff_version=readings.current_version('sniff'), **kwargs)
    catalog = tmp_path / 'catalog'
    readings.create_table(engine=engine, work=tmp_path / 'create-readings', catalog_root=catalog,
                          table=TABLES['readings'], location=tmp_path / 'readings-table', create_namespace=True)
    body_text.create_table(engine=engine, work=tmp_path / 'create-text', catalog_root=catalog,
                           table=TABLES['body_text'], location=tmp_path / 'text-table')
    args = dict(engine=engine, captures=captures, local_root=raw, decided_at=STAMP, catalog_root=catalog,
                tables=TABLES, unreadable_store=BodyStore(LocalAdapter(tmp_path / 'raw-provenance')))
    return args, {digest: name for name, digest in digests.items()}


def committed(args, work, table, columns):
    pin = resolve_tables(engine=args['engine'], work=work / 'resolve', catalog_root=args['catalog_root'],
                         tables={'t': TABLES[table]})['t']
    rows = run_job(work / 'read', args['engine'], inputs=[table_input('t', pin)], steps=[], outputs=[],
                   queries=[dict(name='rows', sql=f"SELECT encode(body_sha,'hex') AS body,{columns} FROM t")])['rows']
    return rows


def test_one_run_settles_every_parser_and_leaves_ocr_bodies_listed(tmp_path):
    bodies = dict(pdf=(two_page_pdf(), 'pdf'), scan=(scanned_pdf(), 'pdf'), html=(HTML, 'html'),
                  xml=(XML, 'xml'), warc=(warc_member(HTML), 'warc'), broken=(b'<x><y>', 'xml'),
                  zip=(b'PK\x03\x04', 'zip'))
    args, names = lake(tmp_path, bodies, gzip_stored={'html'})
    report = body_text.run(**args, work=tmp_path / 'run', execute=True)
    assert report['status'] == 'pending' and report['work_items'] == 6  # the ZIP is no candidate
    [batch] = report['batches']
    assert (batch['ocr_pending'], batch['pending_reads'], batch['unreadable']) == (1, 0, 0)
    text = {names[bytes.fromhex(r['body'])]: r for r in committed(args, tmp_path / 'text', 'body_text',
            "parser,text,page_offsets,encode(text_sha256,'hex') AS sha,macos_build")}
    assert set(text) == {'pdf', 'html', 'xml', 'warc'}
    assert text['pdf']['text'] == PAGE_ONE + '\n' + PAGE_TWO and text['pdf']['page_offsets'] == [0, len(PAGE_ONE) + 1]
    assert text['warc']['text'] == text['html']['text'] and text['warc']['parser'] == 'warc'
    assert all(r['sha'] == hashlib.sha256(r['text'].encode()).hexdigest() and r['macos_build'] is None
               for r in text.values())
    rows = {names[bytes.fromhex(r['body'])]: r for r in committed(args, tmp_path / 'readings', 'readings',
            'parser,parser_version,status,error_type,text_bytes')}
    assert set(rows) == {'pdf', 'html', 'xml', 'warc', 'broken'}  # the scan stays pending: no row
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
