"""Page metadata reaches documents through model SQL and the page-signals registry (ct-93zs D5/D6).

Readings rows are made by the real reader (``reading_row``) from small pages, so the SQL reads
the producer's own field vocabulary. Expectations follow the contract, not the SQL.
"""
import hashlib
import json
import os
from pathlib import Path

import pytest

from congress_api.adapters.common import reported_time
from congress_api.parsers.html_metadata import reading_row
from congress_api.retention.provenance import json_input, list_of, run_job, struct
from docspec_client.client import NativeDatasets

ROOT = Path(__file__).parents[3]
CHAIN = ['html-metadata-readings', 'page-metadata-values', 'page-dates', 'page-descriptions', 'document-page-metadata']


def page(*, title='Hearing page', head='', body='<p>Body</p>'):
    return f'<html><head><title>{title}</title>{head}</head><body>{body}</body></html>'.encode()


def og(name, value):
    return f'<meta property="{name}" content="{value}">'


def json_ld(value):
    return f'<script type="application/ld+json">{json.dumps(value)}</script>'


def run(tmp_path, documents, bodies, *, queries):
    """documents: (doc_key, body bytes or None, source_url, format); bodies are read once each."""
    from viewer_publication.archive_model import registry_inputs
    readings = []
    for body in bodies:
        row = reading_row(body)
        readings.append(dict(body_hex=hashlib.sha256(body).hexdigest(), parser='html_metadata', status=row['status'],
                             title=row.get('title'), base_href=row.get('base_href'), text_bytes=row.get('text_bytes'),
                             text_head=row.get('text_head'), fields=row['fields']))
    readings.append(dict(body_hex='0' * 64, parser='html', status='completed', title='Other parser', base_href=None,
                         text_bytes=None, text_head=None, fields=[]))  # another parser's row on a candidate body
    docs = [dict(doc_key=key, format=fmt, source_url=url, body_hex=hashlib.sha256(body).hexdigest() if body else '0' * 64)
            for key, body, url, fmt in documents]
    inputs = registry_inputs(tmp_path / 'registries') + [
        json_input(tmp_path, 'base_normalized', docs, doc_key='Utf8', format='Utf8', source_url='Utf8', body_hex='Utf8'),
        json_input(tmp_path, 'readings_json', readings, body_hex='Utf8', parser='Utf8', status='Utf8', title='Utf8',
                   base_href='Utf8', text_bytes='Int64', text_head='Utf8', fields=list_of(struct(field='Utf8', value='Utf8')))]
    steps = [dict(name='selected_readings', sql="""SELECT arrow_cast(decode(body_hex,'hex'),'FixedSizeBinary(32)') AS body_sha,
                 * EXCLUDE(body_hex,text_bytes),cast(text_bytes AS INT) AS text_bytes FROM readings_json""")]
    steps += [dict(name=name.replace('-', '_'), sql=(ROOT / 'model/sql' / (name + '.sql')).read_text(), materialize=True) for name in CHAIN]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        return run_job(tmp_path / 'job', engine, inputs=inputs, steps=steps, outputs=[], queries=queries)


def entries_query(doc_key):
    return dict(name=doc_key, sql=f"""SELECT e['field'] AS field,e['value'] AS value,e['format'] AS format,e['path'] AS path,
        cast(e['date'] AS VARCHAR) AS date,e['precision'] AS precision,e['resolved'] AS resolved,e['selected'] AS selected
        FROM (SELECT unnest(page_metadata) AS e FROM document_page_metadata WHERE doc_key='{doc_key}') ORDER BY path""")


COLUMNS = dict(name='columns', sql="""SELECT doc_key,description,cast(published_on AS VARCHAR) AS published_on,
    cast(modified_on AS VARCHAR) AS modified_on,publisher_labels,main_content['outcome'] AS outcome,
    main_content['snippet'] AS snippet,main_content['text_bytes'] AS text_bytes,main_content['selector'] AS selector
    FROM document_page_metadata ORDER BY doc_key""")


def test_one_body_at_two_addresses_resolves_against_each_address(tmp_path):
    body = page(head='<link rel="canonical" href="../z">')
    result = run(tmp_path, [('a', body, 'https://one.test/x/y/page', 'html'), ('b', body, 'https://two.test/p/q', 'html'),
                            ('c', body, None, 'html')], [body], queries=[entries_query(k) for k in 'abc'])
    assert [(r['field'], r['value'], r['resolved']) for r in result['a']] == [('declared_url', '../z', 'https://one.test/x/z')]
    assert [r['resolved'] for r in result['b']] == ['https://two.test/z']
    assert [r['resolved'] for r in result['c']] == [None]  # no address, no resolution


def test_declared_base_comes_before_the_document_address(tmp_path):
    body = page(head='<base href="https://base.test/d/e/"><link rel="canonical" href="f">')
    result = run(tmp_path, [('a', body, 'https://one.test/x/y', 'html')], [body], queries=[entries_query('a')])
    assert [r['resolved'] for r in result['a']] == ['https://base.test/d/e/f']


def test_description_order_rejections_and_conflicts(tmp_path):
    ranked = page(head=og('og:description', 'From OpenGraph') + '<meta name="description" content="From meta">'
                  + json_ld({'@type': 'Article', 'description': 'From JSON-LD'}))
    titled = page(title='Same As Title', head=og('og:description', ' same as title ') + '<meta name="description" content="Kept">')
    site = page(head=og('og:site_name', 'House Committee') + og('og:description', 'house committee')
                + json_ld({'@graph': [{'@type': 'WebSite', 'description': 'The site'}, {'@type': 'Article', 'description': 'The article'}]}))
    template = page(head=og('og:description', 'The official website of the committee'))
    result = run(tmp_path, [('ranked', ranked, 'https://h.test/1', 'html'), ('titled', titled, 'https://h.test/2', 'html'),
                            ('site', site, 'https://h.test/3', 'html'), ('template', template, 'https://h.test/4', 'html')],
                 [ranked, titled, site, template], queries=[COLUMNS, entries_query('ranked')])
    described = {row['doc_key']: row['description'] for row in result['columns']}
    assert described == dict(ranked='From OpenGraph', titled='Kept', site='The article', template=None)
    shown = [(r['value'], r['selected']) for r in result['ranked'] if r['field'] == 'description']
    assert sorted(shown) == [('From JSON-LD', False), ('From OpenGraph', True), ('From meta', False)]  # conflicts listed, one selected


def test_a_description_repeated_across_one_hosts_bodies_is_a_template(tmp_path):
    bodies = [page(title=f'Page {i}', head=og('og:description', 'Shared footer text')) for i in range(50)]
    other = page(title='Elsewhere', head=og('og:description', 'Shared footer text'))
    documents = [(f'd{i:02}', body, f'https://many.test/{i}', 'html') for i, body in enumerate(bodies)]
    result = run(tmp_path, documents + [('other', other, 'https://other.test/1', 'html')], bodies + [other], queries=[COLUMNS])
    described = {row['doc_key']: row['description'] for row in result['columns']}
    assert described['other'] == 'Shared footer text' and {described[k] for k, *_ in documents} == {None}


def test_dates_labels_and_main_content(tmp_path):
    from congress_api.models.html_metadata import SNIPPET_CHARS
    marked = (Path(__file__).parents[2] / 'congress_api/tests/fixtures/html_metadata/marked-testimony.html').read_bytes()
    dated = page(head=json_ld({'@type': 'Article', 'datePublished': '2017-03-01', 'dateModified': '2025-02-30',
                               'articleSection': ['Hearings', 'Hearings ']})
                 + og('article:modified_time', '2025-04-01T22:15:00-04:00') + og('article:section', 'Testimony'))
    result = run(tmp_path, [('dated', dated, 'https://h.test/d', 'html'), ('marked', marked, 'https://v.test/m', 'html'),
                            ('unread', page(title='Not read'), 'https://h.test/u', 'html'), ('pdf', None, 'https://h.test/f.pdf', 'pdf')],
                 [dated, marked], queries=[COLUMNS])
    rows = {row['doc_key']: row for row in result['columns']}
    assert set(rows) == {'dated', 'marked', 'unread'}  # only html documents
    assert (rows['dated']['published_on'], rows['dated']['modified_on']) == ('2017-03-01', '2025-04-01')  # 2025-02-30 is no date
    assert rows['dated']['publisher_labels'] == ['Hearings', 'Testimony']
    assert rows['dated']['outcome'] == 'fallback' and rows['dated']['snippet'] is None
    assert rows['marked']['outcome'] == 'marked' and rows['marked']['selector'].startswith('/html/body')
    assert 0 < len(rows['marked']['snippet']) <= SNIPPET_CHARS and rows['marked']['text_bytes'] > len(rows['marked']['snippet'])
    assert rows['unread']['outcome'] == 'unread'


DATES = ['2025-04-01', '2025-04-01T10:00', '2025-04-01T10:00:59', '2025-04-01 22:15:00-04:00', '2025-04-01T10:00Z',
         '2025-04-01T10:00:00.123+0530', '2025-04-01T10:00+05', ' 2025-04-01 ', '2025-02-30', '2025-04-01T25:00',
         '2025-04-01T10:60', '2025-04-01T10:00:61', '2025-04-01T10:00+25:00', '2025-04-01T10:00+05:99', '20250401',
         'Tue, 01 Apr 2025 10:00:00 GMT', '2025-4-1', '2025-04-01T10', '', 'April 1, 2025', '2024-02-29', '2023-02-29']


def test_sql_dates_equal_reported_time_both_ways(tmp_path):
    def python(value):
        try:
            parsed = reported_time(value)
        except ValueError:
            return None
        return parsed and (parsed.date.isoformat(), parsed.precision)
    head = ''.join(og('article:published_time', value) for value in DATES)
    body = page(head=head)
    result = run(tmp_path, [('d', body, 'https://h.test/d', 'html')], [body], queries=[dict(name='v', sql="""SELECT value,
        cast(date AS VARCHAR) AS date,precision FROM page_metadata_values WHERE field='published_time'""")])
    sql = {row['value']: row['date'] and (row['date'], row['precision']) for row in result['v']}
    assert set(sql) == set(DATES)
    assert sql == {value: python(value) for value in DATES}


def _release(tmp_path, *, with_metadata):
    """One html document from a receipt line through the real producers and the model."""
    import gzip
    import pyarrow.parquet as pq
    from congress_api.lake import filenames, readings
    from congress_api.lake.captures import stage_captures
    from congress_api.retention.provenance import parquet_output
    from viewer_publication.archive_model import build_release
    engine = NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG'])
    raw = tmp_path / 'raw'
    html = page(title='Full Committee Hearing', head=og('og:description', 'Hearing on rural transit')
                + og('article:modified_time', '2025-03-04T09:00:00-05:00') + og('article:section', 'Hearings')
                + '<link rel="canonical" href="/hearing">' + json_ld({'@type': 'Event', 'datePublished': '2017-06-01'}),
                body='<p>' + 'Hearing record text. ' * 60 + '</p>')
    digest = hashlib.sha256(html).hexdigest()
    stored = gzip.compress(html, mtime=0)
    key = f'bodies/sha256/{digest[:2]}/{digest}.gz'
    (raw / key).parent.mkdir(parents=True)
    (raw / key).write_bytes(stored)
    row = dict(writer=dict(job='fixture', commit='a' * 40), run_id='fixture', mode='fetch', family='documents', outcome='stored',
               requested_url='https://fixture.test/a/hearing.htm', url='https://fixture.test/a/hearing.htm', response_headers={}, http_status=200,
               complete=True, retrieved_at='2026-10-27T12:00:00Z',
               captures=[dict(sha256=digest, bytes=len(html), media_type='text/html', fidelity='exact-bytes', sniffed_format='html',
                              sniff_version=readings.current_version('sniff'), intact=None, stored_suffix='.gz', stored_bytes=len(stored),
                              stored_md5=hashlib.md5(stored).hexdigest())])
    receipt = raw / 'receipts/documents/2026-10-27/slice.jsonl.gz'
    receipt.parent.mkdir(parents=True)
    encoded = gzip.compress((json.dumps(row) + '\n').encode(), mtime=0)
    receipt.write_bytes(encoded)
    pin = tmp_path / 'receipt-pin.json'
    pin.write_text(json.dumps(dict(path=str(receipt), size=len(encoded), sha256=hashlib.sha256(encoded).hexdigest(), producer='fixture creation')))
    captures = stage_captures([dict(key=receipt.relative_to(raw).as_posix(), path=str(receipt), qualification=str(pin))],
                              engine=engine, work=tmp_path / 'capture-stage') / 'captures.parquet'
    inventory = tmp_path / 'inventory'
    inventory.mkdir()
    run_job(inventory, engine, inputs=[dict(name='captures', kind='parquet', path=str(captures))], steps=[], outputs=[
        parquet_output(inventory, 'bodies', """SELECT DISTINCT sha256 AS body_sha,
        'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS physical_key,
        'bodies/sha256/'||substr(encode(sha256,'hex'),1,2)||'/'||encode(sha256,'hex')||stored_suffix AS relative_path,
        stored_bytes,stored_suffix='.gz' AS stored_gzip FROM captures WHERE sha256 IS NOT NULL""", ['body_sha'])])
    common = dict(captures=captures, body_inventory=inventory / 'bodies.parquet', local_root=raw, engine=engine, decided_at='2026-10-27T12:00:00Z')
    parts = [readings.stage(**common, work=tmp_path / 'html-stage', parser='html')['readings']]
    versions = {p: readings.current_version(p) for p in ['sniff', 'html', 'xml', 'json']}
    if with_metadata:
        staged = readings.stage(**common, work=tmp_path / 'metadata-stage', parser='html_metadata')
        assert staged['work_items'] == 1
        parts.append(staged['readings'])
        versions['html_metadata'] = readings.current_version('html_metadata')
    joined = tmp_path / 'readings'
    joined.mkdir()
    run_job(joined, engine, inputs=[dict(name=f'p{i}', kind='parquet', path=str(p)) for i, p in enumerate(parts)], steps=[], outputs=[
        parquet_output(joined, 'readings', ' UNION ALL '.join(f'SELECT * FROM p{i}' for i in range(len(parts))), readings.PK)])
    names = filenames.stage(captures=captures, recovery_files=(), engine=engine, work=tmp_path / 'filename-stage', decided_at='2026-10-27T12:00:00Z')
    build_release(captures=captures, readings=joined / 'readings.parquet', filename_readings=names['readings'], parser_versions=versions,
                  catalog_version=names['catalog_version'], engine=engine, output=tmp_path / 'release', scratch=tmp_path / 'model')
    return tmp_path / 'release', pq


def test_page_columns_survive_export_and_change_no_other_column(tmp_path):
    from viewer_publication.archive_format import PAGE_COLUMNS
    release, pq = _release(tmp_path / 'with', with_metadata=True)
    bare, _ = _release(tmp_path / 'without', with_metadata=False)
    detail = pq.read_table(release / 'detail.parquet').to_pylist()
    assert len(detail) == 1
    row = detail[0]
    assert row['description'] == 'Hearing on rural transit'
    assert (row['published_on'].isoformat(), row['modified_on'].isoformat()) == ('2017-06-01', '2025-03-04')
    assert row['publisher_labels'] == ['Hearings']
    assert row['main_content']['outcome'] == 'fallback'
    resolved = [e['resolved'] for e in row['page_metadata'] if e['field'] == 'declared_url']
    assert resolved == ['https://fixture.test/hearing']
    assert {e['field'] for e in row['page_metadata'] if e['selected']} == {'description', 'published_time', 'modified_time', 'section'}
    without = pq.read_table(bare / 'detail.parquet').to_pylist()[0]
    assert without['main_content']['outcome'] == 'unread' and without['page_metadata'] == [] and without['description'] is None
    # A page date is never a document date; every other column is the build without metadata.
    assert {k: v for k, v in row.items() if k not in PAGE_COLUMNS} == {k: v for k, v in without.items() if k not in PAGE_COLUMNS}
    assert (release / 'list.parquet').read_bytes() == (bare / 'list.parquet').read_bytes()
    for name in ('links', 'urls', 'sources', 'meetings', 'url_state'):
        assert pq.read_table(release / f'{name}.parquet').to_pylist() == pq.read_table(bare / f'{name}.parquet').to_pylist(), name
