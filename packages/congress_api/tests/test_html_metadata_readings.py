"""html_metadata is a derived readings parser: the existing producer plans, reads and appends it.

Expectations come from the contract (one row per html body, gaps are pending reads, a
failure never erases another parser's row), not from the reader's own output.
"""
import hashlib
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake import compatible_versions, readings
from congress_api.parsers import html_metadata
from congress_api.parsers.html_metadata import facts_from_fields, page_facts, read_html_metadata, reading_row
from congress_api.retention.body_store import BodyStore, LocalAdapter
from congress_api.retention.parser_worker import ParserWorker
from docspec_client.client import NativeDatasets
from native_test_helpers import lake_readings_table

FIXTURES = Path(__file__).parent / 'fixtures/html_metadata'
STAMP = '2026-11-02T12:00:00Z'
SNIFF = readings.current_version('sniff')
# Minimal reproduction of gov.uk f3a990b3513c8c42: JSON-LD articleBody with markup, no RDFa.
GOV_UK = (b'<html><head><title>Statement</title><script type="application/ld+json">'
          b'{"@type":"Article","articleBody":"<div class=\\"govspeak\\"><p>With permission</p></div>"}'
          b'</script></head><body><p>With permission</p></body></html>')


def bodies():
    return {'marked': (FIXTURES / 'marked-testimony.html').read_bytes(),
            'no_statement': (FIXTURES / 'marked-no-statement.html').read_bytes(),
            'gov_uk': GOV_UK, 'pdf': b'%PDF-1.7\n%fixture\n', 'missing': b'<html><body>not on disk</body></html>'}


def inputs(root):
    root.mkdir()
    raw = root / 'raw'
    captures, inventory, sniff, digests = [], [], [], {}
    for name, data in bodies().items():
        digest = hashlib.sha256(data).digest()
        digests[name] = digest
        key = 'bodies/sha256/' + digest.hex()[:2] + '/' + digest.hex()
        if name != 'missing':
            (raw / key).parent.mkdir(parents=True, exist_ok=True)
            (raw / key).write_bytes(data)
            inventory.append(dict(body_sha=digest, physical_key=key, relative_path=key, stored_bytes=len(data), stored_gzip=False))
        captures.append(dict(sha256=digest, bytes=len(data), media_type='text/html', fidelity='exact-bytes'))
        sniff.append(dict(body_sha=digest, parser='sniff', parser_version=SNIFF, status='completed',
                          format='pdf' if name == 'pdf' else 'html'))
    cap, inv, existing = root / 'captures.parquet', root / 'inventory.parquet', root / 'sniff.parquet'
    pq.write_table(pa.Table.from_pylist(captures, schema=pa.schema([('sha256', pa.binary(32)), ('bytes', pa.int64()),
        ('media_type', pa.string()), ('fidelity', pa.string()), ('sniffed_format', pa.string()),
        ('sniff_version', pa.string()), ('intact', pa.bool_())])), cap)
    pq.write_table(pa.Table.from_pylist(inventory, schema=pa.schema([('body_sha', pa.binary(32)), ('physical_key', pa.string()),
        ('relative_path', pa.string()), ('stored_bytes', pa.int64()), ('stored_gzip', pa.bool_())])), inv)
    pq.write_table(lake_readings_table(sniff), existing)
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    return dict(captures=cap, body_inventory=inv, local_root=raw, decided_at=STAMP, engine=engine), existing, digests


def by_name(rows, digests):
    names = {digest: name for name, digest in digests.items()}
    return {names[row['body_sha']]: row for row in rows}


def fields(row):
    return {item['field']: item['value'] for item in row['fields']}


def test_stage_reads_only_html_bodies_and_records_outcomes(tmp_path):
    args, existing, digests = inputs(tmp_path / 'source')
    staged = readings.stage(**args, existing=existing, work=tmp_path / 'stage', parser='html_metadata')
    rows = by_name(pq.read_table(staged['readings']).to_pylist(), digests)
    assert set(rows) == {'marked', 'no_statement', 'gov_uk'}  # the PDF is no candidate; the missing body is a gap
    assert staged['work_items'] == 4 and staged['pending_reads'] == 1 and staged['unreadable'] == 0
    assert {row['parser'] for row in rows.values()} == {'html_metadata'}
    assert {row['parser_version'] for row in rows.values()} == {readings.current_version('html_metadata')}
    outcomes = {name: fields(row)['main_content:outcome'] for name, row in rows.items()}
    assert outcomes == dict(marked='marked', no_statement='marked_no_content', gov_uk='fallback_required')
    assert rows['no_statement']['text_head'] == 'No prepared statement.'
    assert rows['marked']['text_head'] and rows['marked']['text_bytes'] > len(rows['marked']['text_head'])
    assert fields(rows['gov_uk'])['main_content:reason'] == 'no_candidate' and rows['gov_uk']['text_head'] is None
    from importlib.metadata import version
    assert {fields(row)['extruct_version'] for row in rows.values()} == {version('extruct')}
    assert all(row['fingerprint'] is None and row['status'] == 'completed' for row in rows.values())


def _current(tmp_path, args, parts):
    from congress_api.retention.provenance import parquet_output, run_job
    out = tmp_path / ('current-' + str(len(list(tmp_path.glob('current-*')))))
    out.mkdir()
    sources = [dict(name=f'p{i}', kind='parquet', path=str(path)) for i, path in enumerate(parts)]
    run_job(out, args['engine'], inputs=sources, steps=[], outputs=[parquet_output(out, 'readings',
        ' UNION ALL '.join(f'SELECT * FROM {s["name"]}' for s in sources), readings.PK)])
    return out / 'readings.parquet'


def test_rerun_is_zero_work_and_a_new_version_reselects_only_html_bodies(tmp_path, monkeypatch):
    args, existing, digests = inputs(tmp_path / 'source')
    first = readings.stage(**args, existing=existing, work=tmp_path / 'first', parser='html_metadata')
    current = _current(tmp_path, args, [existing, first['readings']])
    again = readings.stage(**args, existing=current, work=tmp_path / 'again', parser='html_metadata')
    assert again['work_items'] == 1 and again['pending_reads'] == 1  # only the missing body, still a gap
    real = readings.current_version
    monkeypatch.setattr(readings, 'current_version', lambda p, **k: 'moved' if p == 'html_metadata' else real(p, **k))
    moved = readings.plan(**args, existing=current, work=tmp_path / 'moved', parser='html_metadata')
    listed = {row['body_sha'] for row in pq.read_table(moved['work_list']).to_pylist()}
    assert listed == {digests[n] for n in ('marked', 'no_statement', 'gov_uk', 'missing')}
    for leaf in ('html', 'sniff'):  # a moved html_metadata pin re-reads no leaf
        assert readings.current_version(leaf) == real(leaf)


def _as_lists(source, target):
    """The fixture helper writes large lists; the table declares lists."""
    def plain(kind):
        if pa.types.is_large_list(kind):
            return pa.list_(plain(kind.value_type))
        if pa.types.is_struct(kind):
            return pa.struct([field.with_type(plain(field.type)) for field in kind])
        return kind
    table = pq.read_table(source)
    pq.write_table(table.cast(pa.schema([field.with_type(plain(field.type)) for field in table.schema])), target)
    return target


class _FailSecondBatch:
    started = 0

    def __init__(self, *args, **kwargs):
        type(self).started += 1
        if type(self).started == 2:
            raise RuntimeError('worker start failed')
        self.worker = ParserWorker(*args, **kwargs)

    def __enter__(self):
        self.worker.__enter__()
        return self

    def __exit__(self, *args):
        return self.worker.__exit__(*args)

    def parse(self, key, payload):
        return self.worker.parse(key, payload)


def test_interrupted_backfill_resumes_without_duplicates_or_touching_other_parsers(tmp_path):
    args, existing, digests = inputs(tmp_path / 'source')
    table = dict(namespace=['archive'], name='readings')
    target = dict(table=table, catalog_root=tmp_path / 'catalog')
    readings.create_table(engine=args['engine'], work=tmp_path / 'create', catalog_root=tmp_path / 'catalog',
                          table=table, location=tmp_path / 'lake', create_namespace=True)
    from congress_api.lake.tables import append_rows
    append_rows(_as_lists(existing, tmp_path / 'seed.parquet'), engine=args['engine'], work=tmp_path / 'seed', catalog_root=tmp_path / 'catalog', table=table,
                keys=readings.PK, definition='readings:sniff:' + SNIFF)
    store = BodyStore(LocalAdapter(tmp_path / 'durable'))
    with pytest.raises(RuntimeError, match='worker start failed'):
        readings.run(**args, **target, work=tmp_path / 'first', mode='backfill', execute=True, batch_size=1,
                     parser='html_metadata', worker_factory=_FailSecondBatch, unreadable_store=store)
    second = readings.run(**args, **target, work=tmp_path / 'second', mode='backfill', execute=True, batch_size=2,
                          parser='html_metadata', unreadable_store=store)
    assert second['work_items'] == 3 and second['pending_reads'] == 1  # the first batch's body is settled
    from congress_api.lake.tables import resolve_tables
    current = resolve_tables(engine=args['engine'], work=tmp_path / 'read', catalog_root=tmp_path / 'catalog',
                             tables={'readings': table})['readings']
    assert compatible_versions.preflight(engine=args['engine'], work=tmp_path / 'preflight', inputs={'readings': current}) == {'readings': 0}
    from congress_api.lake.tables import table_input
    from congress_api.retention.provenance import run_job
    counts = run_job(tmp_path / 'count', args['engine'], inputs=[table_input('r', current)],
                     steps=[], outputs=[], queries=[dict(name='n', sql='SELECT parser,parser_version,count(*) AS n FROM r GROUP BY parser,parser_version ORDER BY parser')])['n']
    assert counts == [dict(parser='html_metadata', parser_version=readings.current_version('html_metadata'), n=3),
                      dict(parser='sniff', parser_version=SNIFF, n=5)]


def test_a_worker_kill_is_an_unreadable_decision_at_html_metadata(tmp_path):
    args, existing, digests = inputs(tmp_path / 'source')

    class Killed:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def parse(self, key, payload): return dict(status='unreadable', reason='timeout', attempts=2)

    staged = readings.stage(**args, existing=existing, work=tmp_path / 'stage', parser='html_metadata', worker_factory=Killed,
                            unreadable_store=BodyStore(LocalAdapter(tmp_path / 'durable')))
    assert pq.ParquetFile(staged['readings']).metadata.num_rows == 0 and staged['unreadable'] == 3
    decisions = [json.loads(line) for p in (tmp_path / 'durable').rglob('*.jsonl') for line in p.read_text().splitlines()]
    assert {(d['parser'], d['parser_version']) for d in decisions} == {('html_metadata', readings.current_version('html_metadata'))}


def test_the_bundle_does_not_hash_html_metadata(monkeypatch):
    before = readings.bundle_version({p: readings.current_version(p) for p in compatible_versions.LEAF_PARSERS},
                                     policy=readings.worker_limits())
    monkeypatch.setattr(html_metadata, 'FORMAT_TIMEOUT_SECONDS', 1.0)
    after = readings.bundle_version({p: readings.current_version(p) for p in compatible_versions.LEAF_PARSERS},
                                    policy=readings.worker_limits())
    assert before == after and readings.worker_limits()['timeout_seconds'] == readings.WORKER_TIMEOUT_SECONDS


def test_a_format_deadline_is_partial_and_flagged(monkeypatch):
    from congress_api.models.html_metadata import FormatResult

    def slow(body, name, timeout):
        if name == 'rdfa':
            return FormatResult(status='failed', error_type='format_timeout', error_message='exceeded')
        return FormatResult(status='absent', basis='extractor', items=[])

    monkeypatch.setattr(html_metadata, '_read_format', slow)
    row = reading_row((FIXTURES / 'all-formats.html').read_bytes())
    values = fields(row)
    assert row['status'] == 'partial' and values['wall_clock_dependent'] == 'true'
    assert values['format:rdfa'] == 'failed:format_timeout' and values['format:json-ld'] == 'absent'


def test_a_reader_failure_is_an_error_row_not_an_empty_reading(monkeypatch):
    monkeypatch.setattr(html_metadata, 'read_html_metadata', lambda body: (_ for _ in ()).throw(MemoryError()))
    assert reading_row(b'<html></html>') == dict(status='error', error_type='MemoryError', format='html', fields=[])


def test_fact_fields_round_trip_and_pointers_have_no_space():
    metadata = read_html_metadata((FIXTURES / 'all-formats.html').read_bytes())
    expected = tuple(fact for fact in page_facts(metadata) if isinstance(fact.value, str))
    row = reading_row((FIXTURES / 'all-formats.html').read_bytes())
    facts = [item for item in row['fields'] if item['field'].startswith('fact:')]
    assert expected and facts_from_fields(row['fields']) == expected
    assert all(item['field'].count(' ') == 1 for item in facts)
    assert {fact.field for fact in expected} >= {'published_time', 'modified_time', 'description'}
