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


def run(tmp_path, documents, bodies, *, queries, extra_contexts=()):
    """documents: (doc_key, body bytes or None, source_url, format); bodies are read once each."""
    from viewer_publication.archive_model import registry_inputs
    readings = []
    for body in bodies:
        row = reading_row(body)
        readings.append(dict(body_hex=hashlib.sha256(body).hexdigest(), parser='html_metadata', parser_version='test-pin', status=row['status'], error_type=row.get('error_type'),
                             title=row.get('title'), base_href=row.get('base_href'), text_bytes=row.get('text_bytes'),
                             text_head=row.get('text_head'), fields=row['fields']))
    readings.append(dict(body_hex='0' * 64, parser='html', parser_version='test-pin', status='completed', error_type=None, title='Other parser', base_href=None,
                         text_bytes=None, text_head=None, fields=[]))  # another parser's row on a candidate body
    docs = [dict(doc_key=key, format=fmt, source_url=url, body_hex=hashlib.sha256(body).hexdigest() if body else '0' * 64)
            for key, body, url, fmt in documents]
    contexts = [dict(source_id=doc['doc_key'], body_sha=doc['body_hex'], context_url=doc['source_url'], outcome='stored', is_real_file=True)
                for doc in docs if doc['source_url']] + list(extra_contexts)
    inputs = registry_inputs(tmp_path / 'registries') + [
        json_input(tmp_path, 'document_identities', [dict(document_id=d['doc_key'], component=d['doc_key']) for d in docs],
                   document_id='Utf8', component='Utf8'),
        json_input(tmp_path, 'document_members', [dict(component=d['doc_key'], source_id=d['doc_key'], body_sha=d['body_hex']) for d in docs],
                   component='Utf8', source_id='Utf8', body_sha='Utf8'),
        json_input(tmp_path, 'capture_sources', contexts,
                   source_id='Utf8', body_sha='Utf8', context_url='Utf8', outcome='Utf8', is_real_file='Boolean'),
        json_input(tmp_path, 'base_normalized', docs, doc_key='Utf8', format='Utf8', source_url='Utf8', body_hex='Utf8'),
        json_input(tmp_path, 'parser_versions', [dict(parser='html_metadata', version='test-pin')], parser='Utf8', version='Utf8'),
        json_input(tmp_path, 'accepted_versions', [dict(parser='html_metadata', version='test-pin')], parser='Utf8', version='Utf8'),
        json_input(tmp_path, 'active_unreadable', [], id='Utf8', body_sha256='Utf8', parser='Utf8',
                   parser_version='Utf8', reason='Utf8', decided_at='Utf8'),
        json_input(tmp_path, 'readings_json', readings, body_hex='Utf8', parser='Utf8', parser_version='Utf8', status='Utf8', error_type='Utf8', title='Utf8',
                   base_href='Utf8', text_bytes='Int64', text_head='Utf8', fields=list_of(struct(field='Utf8', value='Utf8')))]
    steps = [dict(name='selected_readings', sql="""SELECT arrow_cast(decode(body_hex,'hex'),'FixedSizeBinary(32)') AS body_sha,
                 * EXCLUDE(body_hex,text_bytes),cast(text_bytes AS INT) AS text_bytes FROM readings_json""")]
    steps += [dict(name=name.replace('-', '_'), sql=(ROOT / 'model/sql' / (name + '.sql')).read_text(), materialize=True) for name in CHAIN]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        return run_job(tmp_path / 'job', engine, inputs=inputs, steps=steps, outputs=[], queries=queries)


def entries_query(doc_key):
    return dict(name=doc_key, sql=f"""SELECT e['field'] AS field,e['value'] AS value,e['format'] AS format,e['path'] AS path,
        cast(e['date'] AS VARCHAR) AS date,e['precision'] AS precision,e['resolved'] AS resolved,e['selected'] AS selected,e['context_url'] AS context_url
        FROM (SELECT unnest(page_metadata) AS e FROM document_page_metadata WHERE doc_key='{doc_key}') ORDER BY path,context_url""")


COLUMNS = dict(name='columns', sql="""SELECT doc_key,description,cast(published_on AS VARCHAR) AS published_on,
    cast(modified_on AS VARCHAR) AS modified_on,publisher_labels,main_content['outcome'] AS outcome,
    main_content['snippet'] AS snippet,main_content['text_bytes'] AS text_bytes,main_content['selector'] AS selector
    FROM document_page_metadata ORDER BY doc_key""")


def test_one_body_at_two_addresses_resolves_in_the_same_document(tmp_path):
    body = page(head='<link rel="canonical" href="../z">')
    digest = hashlib.sha256(body).hexdigest()
    result = run(tmp_path, [('a', body, 'https://one.test/x/y/page', 'html'), ('c', body, None, 'html')],
                 [body], queries=[entries_query(k) for k in 'ac'], extra_contexts=[
                     dict(source_id='a', body_sha=digest, context_url='https://two.test/p/q', outcome='stored', is_real_file=True),
                     dict(source_id='a', body_sha=digest, context_url='https://fake.test/', outcome='reference', is_real_file=False),
                 ])
    assert [(r['value'], r['context_url'], r['resolved']) for r in result['a']] == [
        ('../z', 'https://one.test/x/y/page', 'https://one.test/x/z'),
        ('../z', 'https://two.test/p/q', 'https://two.test/z'),
    ]
    assert [r['resolved'] for r in result['c']] == [None]


def test_capture_context_fanout_and_long_resolutions_keep_bounded_literal_evidence(tmp_path):
    bodies = [
        page(head=og('og:description', f'Publisher summary {i}') + '<link rel="canonical" href="next">')
        for i in range(2)
    ]
    documents = [(str(i), body, 'https://publisher.test/root/', 'html') for i, body in enumerate(bodies)]
    contexts = [
        dict(source_id='0', body_sha=hashlib.sha256(bodies[0]).hexdigest(),
             context_url=f'https://publisher.test/{i}/', outcome='stored', is_real_file=True)
        for i in range(600)
    ]
    # These contexts fit before URL resolution. Including each resolved address
    # would exceed the final byte budget even though there are only eight.
    contexts += [
        dict(source_id='1', body_sha=hashlib.sha256(bodies[1]).hexdigest(),
             context_url=f'https://publisher.test/{i}/' + 'a' * 6000 + '/', outcome='stored', is_real_file=True)
        for i in range(8)
    ]
    evidence = dict(name='evidence', sql="""SELECT doc_key,page_metadata,main_content['evidence_limited'] AS limited
        FROM document_page_metadata ORDER BY doc_key""")
    result = run(tmp_path, documents, bodies, queries=[evidence], extra_contexts=contexts)

    for row in result['evidence']:
        assert row['limited']
        facts = {fact['field']: fact for fact in row['page_metadata']}
        assert facts['description']['value'] == f"Publisher summary {row['doc_key']}"
        assert facts['description']['selected']
        assert facts['declared_url']['value'] == 'next'
        assert facts['declared_url']['context_url'] is None and facts['declared_url']['resolved'] is None
        assert len(json.dumps(row['page_metadata']).encode()) <= 65536


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


def _release(tmp_path, *, with_metadata, extra_pages=(), unreadable=()):
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
    records = []
    for url, data in [('https://fixture.test/a/hearing.htm', html), *extra_pages]:
        digest = hashlib.sha256(data).hexdigest()
        stored = gzip.compress(data, mtime=0)
        key = f'bodies/sha256/{digest[:2]}/{digest}.gz'
        (raw / key).parent.mkdir(parents=True, exist_ok=True)
        (raw / key).write_bytes(stored)
        records.append(dict(writer=dict(job='fixture', commit='a' * 40), run_id='fixture', mode='fetch',
            family='documents', outcome='stored', requested_url=url, url=url, response_headers={}, http_status=200,
            complete=True, retrieved_at='2026-10-27T12:00:00Z',
            captures=[dict(sha256=digest, bytes=len(data), media_type='text/html', fidelity='exact-bytes',
                sniffed_format='html', sniff_version=readings.current_version('sniff'), intact=None, stored_suffix='.gz',
                stored_bytes=len(stored), stored_md5=hashlib.md5(stored).hexdigest())]))
    receipt = raw / 'receipts/documents/2026-10-27/slice.jsonl.gz'
    receipt.parent.mkdir(parents=True)
    encoded = gzip.compress(''.join(json.dumps(row) + '\n' for row in records).encode(), mtime=0)
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
    unreadable_files = []
    if unreadable:
        decision_file = tmp_path / 'unreadable.jsonl'
        decision_file.write_text(''.join(json.dumps(row) + '\n' for row in unreadable))
        unreadable_files = [dict(key='unreadable/fixture.jsonl', path=str(decision_file))]
    common = dict(captures=captures, body_inventory=inventory / 'bodies.parquet', local_root=raw, engine=engine, decided_at='2026-10-27T12:00:00Z')
    parts = [readings.stage(**common, work=tmp_path / 'html-stage', parser='html')['readings']]
    versions = {p: readings.current_version(p) for p in ['sniff', 'html', 'xml', 'json']}
    if with_metadata:
        versions['html_metadata'] = readings.current_version('html_metadata')
        staged = readings.stage(**common, work=tmp_path / 'metadata-stage', parser='html_metadata',
                                unreadable_files=unreadable_files)
        eligible = {hashlib.sha256(data).hexdigest() for _, data in extra_pages}
        settled = {row['body_sha256'] for row in unreadable if row['parser_version'] == versions['html_metadata']}
        assert staged['work_items'] == len(eligible - settled) + 1
        parts.append(staged['readings'])
    joined = tmp_path / 'readings'
    joined.mkdir()
    run_job(joined, engine, inputs=[dict(name=f'p{i}', kind='parquet', path=str(p)) for i, p in enumerate(parts)], steps=[], outputs=[
        parquet_output(joined, 'readings', ' UNION ALL '.join(f'SELECT * FROM p{i}' for i in range(len(parts))), readings.PK)])
    names = filenames.stage(captures=captures, recovery_files=(), engine=engine, work=tmp_path / 'filename-stage', decided_at='2026-10-27T12:00:00Z')
    build_release(captures=captures, readings=joined / 'readings.parquet', filename_readings=names['readings'], parser_versions=versions,
                  catalog_version=names['catalog_version'], engine=engine, output=tmp_path / 'release', scratch=tmp_path / 'model',
                  unreadable_files=unreadable_files)
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



def test_native_partial_and_decided_unreadable_metadata(tmp_path):
    from congress_api.lake.readings import current_version
    from congress_api.parsers.html_metadata import MAX_DETAIL_FACT_BYTES

    partial = page(title='Page with oversized publisher facts',
                   head=og('og:description', 'a' * (MAX_DETAIL_FACT_BYTES + 1)),
                   body='<p>Independent substantive text. ' + 'This page contains a publisher report. ' * 30 + '</p>')
    blocked = page(title='Publisher page with worker failure',
                   body='<p>' + 'This other publisher page contains a hearing report. ' * 30 + '</p>')
    blocked_sha = hashlib.sha256(blocked).hexdigest()
    current = current_version('html_metadata')
    decision = dict(id='fixture-timeout', body_sha256=blocked_sha, parser='html_metadata', parser_version=current,
                    reason='timeout', decided_by='fixture', decided_at='2026-10-27T12:00:00Z', supersedes=None)
    # The superseding current decision supplies the outcome and citation.
    previous = dict(decision, id='fixture-earlier', reason='memory_limit', decided_at='2026-10-26T12:00:00Z')
    release, pq = _release(tmp_path, with_metadata=True, extra_pages=[
        ('https://fixture.test/partial.htm', partial),
        ('https://fixture.test/unreadable.htm', blocked),
    ], unreadable=[previous, dict(decision, supersedes=previous['id'])])

    detail = {row['saved_body'].hex(): row for row in pq.read_table(release / 'detail.parquet').to_pylist()}
    assert detail[hashlib.sha256(partial).hexdigest()]['main_content']['reading_status'] == 'partial'
    assert detail[hashlib.sha256(partial).hexdigest()]['main_content']['facts_limited']
    unreadable = detail[blocked_sha]['main_content']
    assert (unreadable['outcome'], unreadable['reading_status'], unreadable['reason']) == ('unreadable', 'unreadable', 'timeout')
    assert unreadable['reader_version'] == current and unreadable['decision_id'] == decision['id']
    assert detail[blocked_sha]['page_metadata'] == []


def test_shared_html_reader_fixture(tmp_path):
    fixtures = Path(__file__).parents[2] / 'congress_api/tests/fixtures/html_metadata'
    def original(name):
        fixture = (fixtures / name).read_bytes()
        mirror = os.environ.get('RAW_MIRROR')
        if mirror:
            import gzip
            import re
            digest = re.search(rb'sha256 ([a-f0-9]{64})', fixture).group(1).decode()
            stored = Path(mirror) / 'bodies/sha256' / digest[:2] / (digest + '.gz')
            body = gzip.decompress(stored.read_bytes())
            assert hashlib.sha256(body).hexdigest() == digest
            return body
        return fixture

    indian = original('indian-affairs.html')
    marked = original('marked-testimony.html')
    indian_url = ('https://www.indian.senate.gov/hearings/'
                  'oversight-hearing-high-risk-indian-programs-progress-and-efforts-addressing-gaos/')
    from congress_api.parsers.senate import parse_page
    source_event = parse_page(indian, indian_url).model_dump()['event']
    assert source_event['date'] == '2017-09-13'
    release, pq = _release(tmp_path, with_metadata=True, extra_pages=[
        (indian_url, indian),
        ('https://veterans.house.gov/witness-testimony/quinton-d-studer', marked),
    ])
    docs = {row['saved_body']: row for row in pq.read_table(release / 'detail.parquet').to_pylist()}
    event_page = docs[hashlib.sha256(indian).digest()]
    assert event_page['published_on'].isoformat() == '2017-09-13'
    assert event_page['modified_on'].isoformat() == '2025-04-01'
    assert event_page['document_date'] != event_page['modified_on']
    assert any(value['selected'] and value['field'] == 'modified_time' for value in event_page['page_metadata'])
    testimony = docs[hashlib.sha256(marked).digest()]
    expected = (fixtures / 'marked-testimony.txt').read_text().rstrip('\n')
    assert testimony['selected_text'] == expected
    assert testimony['main_content']['text_sha256'] == hashlib.sha256(expected.encode()).hexdigest()
    assert testimony['main_content']['text_available']
