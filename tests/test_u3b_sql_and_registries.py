"""Validation of PR-U3b SQL steps and JSON registries on unmodified DataFusion plans."""
import hashlib
import json
import os
from pathlib import Path
import re

from congress_api.lake import filenames
from congress_api.parsers.html_metadata import reading_row
from congress_api.retention.provenance import json_input, list_of, run_job, struct
from docspec_client.client import NativeDatasets
import pyarrow as pa
import pyarrow.parquet as pq
from viewer_publication.archive_annotations import annotation_steps
from viewer_publication.archive_model import PAGE_METADATA_STEPS, REGISTRIES, registry_inputs

ROOT = Path(__file__).resolve().parents[1]


def test_registries_schema_row_counts_and_bounded_print_cover_pattern():
    commissions = json.loads((ROOT / 'model/registries/congressional-commissions.json').read_text())
    expected_keys = set(REGISTRIES['congressional_commissions'])
    assert len(commissions) == 7
    for entry in commissions:
        assert set(entry) == expected_keys
        assert all(isinstance(entry[k], str) and entry[k].strip() for k in expected_keys)
        re.compile(entry['pattern'])

    signals = json.loads((ROOT / 'model/registries/page-signals.json').read_text())
    by_id = {s['id']: s for s in signals}
    for sig in signals:
        if sig.get('pattern') is not None:
            re.compile(sig['pattern'])
    print_cover_pat = by_id['gpo_printed_hearing_cover']['pattern']
    assert '.*' not in print_cover_pat


def test_body_signals_and_transcript_print_covers_on_native_datafusion(tmp_path):
    gpo_cover_text = (
        'IMPLEMENTING THE FARM BILL\nHEARING\nBEFORE THE\nCOMMITTEE ON AGRICULTURE\n'
        'UNITED STATES SENATE\nS. Hrg. 118-42\nU.S. GOVERNMENT PUBLISHING OFFICE'
    )
    gpo_footer_first = (
        'U.S. GOVERNMENT PUBLISHING OFFICE\n99-123 PDF WASHINGTON : 2024\n'
        'OVERSIGHT OF FEDERAL SPECTRUM\nHEARING\nBEFORE THE\nCOMMITTEE ON COMMERCE\n'
        'SERIAL NO. 118-55'
    )
    steno_text = (
        'STENOGRAPHIC TRANSCRIPT OF PROCEEDINGS\nHEARING BEFORE THE COMMITTEE ON ARMED SERVICES\n'
        'UNITED STATES SENATE\nALDERSON COURT REPORTING'
    )
    page_rows = [
        dict(
            body_hex='11' * 32,
            status='completed',
            xml_root=None,
            title='Access Denied: Challenges for Women- and Minority-Owned Businesses | Committee on Small Business',
            heading='Access Denied: Challenges for Women- and Minority-Owned Businesses',
            text_head='Full Committee Hearing before the Committee on Small Business examining capital access.',
            text_bytes=4200,
            link_count=3,
            link_text_bytes=50,
        ),
        dict(
            body_hex='22' * 32,
            status='completed',
            xml_root=None,
            title='Access denied | Committee on Energy and Commerce',
            heading='Access denied',
            text_head=(
                'Skip to main content Committee on Energy and Commerce Subcommittees Hearings Markups '
                'Access denied You are not authorized to access this page.'
            ),
            text_bytes=2400,
            link_count=12,
            link_text_bytes=220,
        ),
        dict(
            body_hex='33' * 32,
            status='completed',
            xml_root=None,
            title='Page Not Found',
            heading='',
            text_head='404 page not found',
            text_bytes=250,
            link_count=1,
            link_text_bytes=10,
        ),
        dict(
            body_hex='44' * 32,
            status='completed',
            xml_root=None,
            title='Access Denied',
            heading='',
            text_head='%PDF-1.7 raw pdf bytes with /Title (Access Denied)',
            text_bytes=2500,
            link_count=0,
            link_text_bytes=0,
        ),
        dict(
            body_hex='55' * 32,
            status='completed',
            xml_root=None,
            title='Hearing',
            heading='',
            text_head=gpo_cover_text,
            text_bytes=8000,
            link_count=0,
            link_text_bytes=0,
        ),
        dict(
            body_hex='66' * 32,
            status='completed',
            xml_root=None,
            title='Hearing',
            heading='',
            text_head=gpo_footer_first,
            text_bytes=8000,
            link_count=0,
            link_text_bytes=0,
        ),
        dict(
            body_hex='77' * 32,
            status='completed',
            xml_root=None,
            title='Stenographic Transcript',
            heading='',
            text_head=steno_text,
            text_bytes=8000,
            link_count=0,
            link_text_bytes=0,
        ),
    ]
    norm_rows = [
        dict(doc_key='doc_gpo_1', body_hex='55' * 32, document_kind=['transcript']),
        dict(doc_key='doc_gpo_2', body_hex='66' * 32, document_kind=['transcript']),
        dict(doc_key='doc_steno', body_hex='77' * 32, document_kind=['transcript']),
    ]
    inputs = registry_inputs(tmp_path / 'registries') + [
        json_input(
            tmp_path,
            'page_facts_raw',
            page_rows,
            body_hex='Utf8',
            status='Utf8',
            xml_root='Utf8',
            title='Utf8',
            heading='Utf8',
            text_head='Utf8',
            text_bytes='Int64',
            link_count='Int64',
            link_text_bytes='Int64',
        ),
        json_input(
            tmp_path,
            'base_normalized',
            norm_rows,
            doc_key='Utf8',
            body_hex='Utf8',
            document_kind=list_of('Utf8'),
        ),
    ]
    steps = [
        dict(
            name='page_facts',
            sql="SELECT arrow_cast(decode(body_hex,'hex'),'FixedSizeBinary(32)') AS body_sha,* EXCLUDE(body_hex) FROM page_facts_raw",
            materialize=True,
        ),
        dict(name='body_signals', sql=(ROOT / 'model/sql/body-signals.sql').read_text(), materialize=True),
        dict(name='transcript_print_covers', sql=(ROOT / 'model/sql/transcript-print-covers.sql').read_text(), materialize=True),
    ]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        res = run_job(
            tmp_path / 'bs_job',
            engine,
            inputs=inputs,
            steps=steps,
            outputs=[],
            queries=[
                dict(name='bs', sql="SELECT encode(body_sha,'hex') AS body_hex, error_response FROM body_signals ORDER BY body_hex"),
                dict(name='tpc', sql='SELECT doc_key FROM transcript_print_covers ORDER BY doc_key'),
            ],
        )

    by_hex = {r['body_hex']: r['error_response'] for r in res['bs']}
    assert by_hex['11' * 32] is False  # Substantive "Access Denied: <subtitle>" hearing page preserved
    assert by_hex['22' * 32] is True   # Themed committee Drupal 403 "Access denied | Committee on..." flagged!
    assert by_hex['33' * 32] is True   # Genuine 404 Page Not Found flagged
    assert by_hex['44' * 32] is False  # Raw %PDF- magic guarded
    assert [r['doc_key'] for r in res['tpc']] == ['doc_gpo_1', 'doc_gpo_2']


def test_source_annotations_exported_committees_hsru_floor_host_and_html_pdf_parity(tmp_path):
    cases = [
        # (source_id, filename, source_url, body_sha, format, html_text_head)
        ('s_scnc', 'hearing.pdf', 'https://www.drugcaucus.senate.gov/wp-content/uploads/2023/05/hearing.pdf', '1' * 64, 'pdf', None),
        ('s_csce', 'briefing.pdf', 'https://www.csce.gov/files/briefing.pdf', '2' * 64, 'pdf', None),
        ('s_dem_house', 'memo.pdf', 'https://democrats-energycommerce.house.gov/sites/evo/files/memo.pdf', '3' * 64, 'pdf', None),
        ('s_wb_senate', 'Smith-Bio.pdf', 'https://web.archive.org/web/20240501120000/https://www.finance.senate.gov/imo/media/doc/Smith-Bio.pdf', '4' * 64, 'pdf', None),
        ('s_hsru_floor', 'BILLS-118hr1435-RCP118-27.pdf', 'https://docs.house.gov/billsthisweek/20230911/BILLS-118hr1435-RCP118-27.pdf', '5' * 64, 'pdf', None),
        ('s_hsru_rules_pdf', '118-Rules.pdf', 'https://rules.house.gov/sites/evo-subsites/rules.house.gov/files/documents/118-Rules.pdf', '6' * 64, 'pdf', None),
        ('s_hsru_clerk', 'HHRG-118-RU00-Transcript-20230912.pdf', 'https://docs.house.gov/meetings/RU/RU00/20230912/116345/HHRG-118-RU00-Transcript-20230912.pdf', '7' * 64, 'pdf', None),
        (
            's_html_banking',
            'oversight-hearing.html',
            'https://www.banking.senate.gov/hearings/oversight-hearing',
            '8' * 64,
            'html',
            'Senator Tim Scott, Ranking Member of the Committee on Banking, welcomed witnesses who previously testified before the Committee on Finance.',
        ),
    ]

    sources = [dict(source_id=sid, filename=fn, source_url=url, body_sha=bsha) for sid, fn, url, bsha, _, _ in cases]
    fn_rows = [filenames.read_filename(fn, url, catalog_version='current') for _, fn, url, _, _, _ in cases]
    filename_path = tmp_path / 'filename-readings.parquet'
    pq.write_table(pa.Table.from_pylist(fn_rows, schema=filenames.SCHEMA), filename_path)

    captures = [
        dict(source_id=sid, body_sha=bsha, context_url=url, member_path=None, requested_filename=None, requested_url=url)
        for sid, _, url, bsha, _, _ in cases
    ]
    # Production page-facts.sql ONLY contains html/xml/json readings — NEVER pdf!
    html_pages = [
        dict(body_hex=bsha, status='completed', title='Hearing', heading=None, content_date=None, text_head=thead, named_meetings=[])
        for _, _, _, bsha, fmt, thead in cases
        if fmt == 'html'
    ]

    def run_with_committees(sub_name: str, spicy_rows: list[dict]):
        sub = tmp_path / sub_name
        inputs = registry_inputs(sub / 'registries') + [
            dict(name='filename_readings', kind='parquet', path=str(filename_path)),
            json_input(sub, 'source_files', sources, source_id='Utf8', filename='Utf8', source_url='Utf8', body_sha='Utf8'),
            json_input(sub, 'capture_sources', captures, source_id='Utf8', body_sha='Utf8', context_url='Utf8',
                       member_path='Utf8', requested_filename='Utf8', requested_url='Utf8'),
            json_input(sub, 'publisher_links', [], source_id='Utf8', doc_type='Utf8', text='Utf8', page_body='Utf8',
                       context='Utf8', context_url='Utf8', first_good_at='Utf8', link_index='Int64', split_position='Int64'),
            json_input(sub, 'page_inputs', html_pages, body_hex='Utf8', status='Utf8', title='Utf8', heading='Utf8',
                       content_date='Utf8', text_head='Utf8', named_meetings=list_of('Int64')),
            json_input(sub, 'spicy_committees', spicy_rows, system_code='Utf8', parent_system_code='Utf8', website_url='Utf8'),
        ]
        steps = [
            dict(name='capture_source_contexts', sql='SELECT * FROM capture_sources'),
            dict(name='page_facts', sql="SELECT arrow_cast(decode(body_hex,'hex'),'FixedSizeBinary(32)') AS body_sha,* EXCLUDE(body_hex),cast(content_date AS DATE) AS day,cast(NULL AS VARCHAR) AS xml_root FROM page_inputs"),
            dict(name='meeting_document_urls', sql='SELECT cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS url WHERE false'),
            dict(name='model_url_keys', sql='SELECT cast(NULL AS VARCHAR) AS url,cast(NULL AS VARCHAR) AS url_key,cast(NULL AS VARCHAR) AS error WHERE false'),
            dict(name='copy_url_keys', sql='SELECT cast(NULL AS VARCHAR) AS source_id,cast(NULL AS VARCHAR) AS url_key WHERE false'),
        ]
        with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
            return run_job(
                sub / 'job',
                engine,
                inputs=inputs,
                steps=steps + annotation_steps('current', root=ROOT),
                outputs=[],
                queries=[
                    dict(name='final', sql='SELECT source_id, committee_keys, chambers FROM source_annotations ORDER BY source_id'),
                ],
            )['final']

    # 1. Empty spicy_committees (Gate 3 invariant): URL-host rules emit ZERO unexported committee codes!
    empty_res = {r['source_id']: r for r in run_with_committees('empty_sc', [])}
    assert empty_res['s_scnc']['committee_keys'] == []
    assert empty_res['s_csce']['committee_keys'] == []
    assert empty_res['s_wb_senate']['committee_keys'] == []
    assert empty_res['s_hsru_floor']['committee_keys'] == []
    # Clerk filename reading still resolves HHRG-118-RU00-... via filename_readings
    assert empty_res['s_hsru_clerk']['committee_keys'] == ['hsru00']

    # 2. Populated spicy_committees:
    populated_sc = [
        dict(system_code='SCNC00', parent_system_code=None, website_url=None),
        dict(system_code='JCSE00', parent_system_code=None, website_url=None),
        dict(system_code='HSIF00', parent_system_code=None, website_url='https://energycommerce.house.gov/'),
        dict(system_code='SSFI00', parent_system_code=None, website_url='https://www.finance.senate.gov/'),
        dict(system_code='HSRU00', parent_system_code=None, website_url='https://rules.house.gov/'),
        dict(system_code='SSBK00', parent_system_code=None, website_url='https://www.banking.senate.gov/'),
    ]
    pop_res = {r['source_id']: r for r in run_with_committees('pop_sc', populated_sc)}
    assert pop_res['s_scnc']['committee_keys'] == ['scnc00']
    assert pop_res['s_csce']['committee_keys'] == ['jcse00']
    assert pop_res['s_dem_house']['committee_keys'] == ['hsif00']
    # Witness bio PDF on finance.senate.gov keeps ssfi00
    assert pop_res['s_wb_senate']['committee_keys'] == ['ssfi00']
    # docs.house.gov/billsthisweek RCP excludes hsru00, while rules.house.gov PDF & HHRG-118-RU00 keep hsru00!
    assert pop_res['s_hsru_floor']['committee_keys'] == []
    assert pop_res['s_hsru_rules_pdf']['committee_keys'] == ['hsru00']
    assert pop_res['s_hsru_clerk']['committee_keys'] == ['hsru00']
    # Committee HTML page mentioning "Ranking Member of..." and "testified before..." keeps ssbk00!
    assert pop_res['s_html_banking']['committee_keys'] == ['ssbk00']


def test_page_dates_sql_guards_cms_uploads_and_preserves_same_day_publications(tmp_path):
    def make_page(title, pub_iso, mod_iso=None):
        meta = f'<meta property="article:published_time" content="{pub_iso}">'
        if mod_iso:
            meta += f'<meta property="article:modified_time" content="{mod_iso}">'
        return f'<html><head><title>{title}</title>{meta}</head><body><p>Hearing record.</p></body></html>'.encode()

    wp_upload = make_page('2014 Hearing Attachment', '2023-08-14T10:00:00Z')
    drupal_upload = make_page('2016 Witness Bio', '2024-01-22T09:00:00Z')
    wayback_injected = make_page('Archived Hearing', '2024-05-19T14:22:10Z')
    wayback_sameday_day = make_page('Same-Day Archived Hearing (Day)', '2024-05-19', mod_iso='2024-05-19T14:22:10Z')
    wayback_sameday_time = make_page('Same-Day Archived Hearing (Morning)', '2024-05-19T09:30:00-04:00', mod_iso='2024-05-19T14:22:10Z')
    normal_page = make_page('Normal Hearing', '2021-04-15')

    documents = [
        ('wp_upload', wp_upload, 'https://oversight.house.gov/wp-content/uploads/2023/08/attachment-page', 'html'),
        ('drupal_upload', drupal_upload, 'https://rules.house.gov/sites/default/files/2024-01/bio-wrapper', 'html'),
        ('wb_injected', wayback_injected, 'https://web.archive.org/web/20240519142210/https://finance.senate.gov/hearings/tax', 'html'),
        ('wb_sameday_day', wayback_sameday_day, 'https://web.archive.org/web/20240519142210/https://finance.senate.gov/hearings/sameday-1', 'html'),
        ('wb_sameday_time', wayback_sameday_time, 'https://web.archive.org/web/20240519142210/https://finance.senate.gov/hearings/sameday-2', 'html'),
        ('normal', normal_page, 'https://finance.senate.gov/hearings/2021-hearing', 'html'),
    ]
    readings = []
    for _, body, _, _ in documents:
        row = reading_row(body)
        readings.append(dict(
            body_hex=hashlib.sha256(body).hexdigest(),
            parser='html_metadata',
            parser_version='test-pin',
            status=row['status'],
            error_type=row.get('error_type'),
            title=row.get('title'),
            base_href=row.get('base_href'),
            text_bytes=row.get('text_bytes'),
            text_head=row.get('text_head'),
            fields=row['fields'],
        ))
    docs = [
        dict(doc_key=k, format=fmt, source_url=u, body_hex=hashlib.sha256(b).hexdigest())
        for k, b, u, fmt in documents
    ]
    contexts = [
        dict(source_id=d['doc_key'], body_sha=d['body_hex'], context_url=d['source_url'], outcome='stored', is_real_file=True)
        for d in docs
    ]
    inputs = registry_inputs(tmp_path / 'registries') + [
        json_input(tmp_path, 'document_identities', [dict(document_id=d['doc_key'], component=d['doc_key']) for d in docs], document_id='Utf8', component='Utf8'),
        json_input(tmp_path, 'document_members', [dict(component=d['doc_key'], source_id=d['doc_key'], body_sha=d['body_hex']) for d in docs], component='Utf8', source_id='Utf8', body_sha='Utf8'),
        json_input(tmp_path, 'capture_sources', contexts, source_id='Utf8', body_sha='Utf8', context_url='Utf8', outcome='Utf8', is_real_file='Boolean'),
        json_input(tmp_path, 'base_normalized', docs, doc_key='Utf8', format='Utf8', source_url='Utf8', body_hex='Utf8'),
        json_input(tmp_path, 'parser_versions', [dict(parser='html_metadata', version='test-pin')], parser='Utf8', version='Utf8'),
        json_input(tmp_path, 'accepted_versions', [dict(parser='html_metadata', version='test-pin')], parser='Utf8', version='Utf8'),
        json_input(tmp_path, 'active_unreadable', [], id='Utf8', body_sha256='Utf8', parser='Utf8', parser_version='Utf8', reason='Utf8', decided_at='Utf8'),
        json_input(tmp_path, 'readings_json', readings, body_hex='Utf8', parser='Utf8', parser_version='Utf8', status='Utf8',
                   error_type='Utf8', title='Utf8', base_href='Utf8', text_bytes='Int64', text_head='Utf8',
                   fields=list_of(struct(field='Utf8', value='Utf8'))),
    ]
    page_dates_sql = (ROOT / 'model/sql/page-dates.sql').read_text()
    steps = [
        dict(name='selected_readings', sql="SELECT arrow_cast(decode(body_hex,'hex'),'FixedSizeBinary(32)') AS body_sha,* EXCLUDE(body_hex,text_bytes),cast(text_bytes AS INT) AS text_bytes FROM readings_json"),
    ] + [
        dict(name=name.replace('-', '_'), sql=(ROOT / 'model/sql' / (name + '.sql')).read_text(), materialize=True)
        for name in PAGE_METADATA_STEPS
    ]
    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        res = run_job(
            tmp_path / 'pm_job',
            engine,
            inputs=inputs,
            steps=steps,
            outputs=[],
            queries=[
                dict(
                    name='dates',
                    sql='SELECT doc_key, cast(published_on AS VARCHAR) AS published_on, cast(modified_on AS VARCHAR) AS modified_on '
                        'FROM document_page_metadata ORDER BY doc_key',
                ),
                dict(name='plan', sql='EXPLAIN ' + page_dates_sql),
            ],
        )

    got = {r['doc_key']: (r['published_on'], r['modified_on']) for r in res['dates']}
    assert got['wp_upload'] == (None, None)
    assert got['drupal_upload'] == (None, None)
    assert got['wb_injected'] == (None, None)
    assert got['wb_sameday_day'] == ('2024-05-19', None)
    assert got['wb_sameday_time'] == ('2024-05-19', None)
    assert got['normal'] == ('2021-04-15', None)

    logical_plan = next(r['plan'] for r in res['plan'] if r['plan_type'] == 'logical_plan')
    assert logical_plan.count('TableScan: base_normalized') == 1, logical_plan
