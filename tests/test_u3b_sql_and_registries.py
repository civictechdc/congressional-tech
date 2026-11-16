"""Validation of PR-U3b SQL steps (DuckDB + DataFusion) and JSON registries."""
import hashlib
import json
import os
from pathlib import Path
import re

import duckdb
import pytest

from congress_api.parsers.html_metadata import reading_row
from congress_api.retention.provenance import json_input, list_of, run_job, struct
from docspec_client.client import NativeDatasets
from viewer_publication.archive_annotations import annotation_steps
from viewer_publication.archive_model import PAGE_METADATA_STEPS, REGISTRIES, registry_inputs

ROOT = Path(__file__).resolve().parents[1]


def test_congressional_commissions_and_page_signals_registries_schema_and_patterns():
    commissions = json.loads((ROOT / 'model/registries/congressional-commissions.json').read_text())
    expected_keys = set(REGISTRIES['congressional_commissions'])
    ids = set()
    for entry in commissions:
        assert set(entry) == expected_keys
        assert all(isinstance(entry[k], str) and entry[k].strip() for k in expected_keys)
        re.compile(entry['pattern'])
        ids.add(entry['id'])

    assert 'scnc00' in ids
    assert 'congressional-oversight-commission' in ids

    signals = json.loads((ROOT / 'model/registries/page-signals.json').read_text())
    for sig in signals:
        if sig.get('pattern') is not None:
            re.compile(sig['pattern'])


def test_duckdb_executes_touched_sql_invariants():
    con = duckdb.connect()
    con.execute('CREATE MACRO regexp_like(s, p) AS regexp_matches(s, p)')
    commissions = json.loads((ROOT / 'model/registries/congressional-commissions.json').read_text())
    con.execute(
        'CREATE TABLE congressional_commissions (id VARCHAR, name VARCHAR, pattern VARCHAR, '
        'created_by VARCHAR, members_serve VARCHAR, citation_status VARCHAR)'
    )
    for row in commissions:
        con.execute(
            'INSERT INTO congressional_commissions VALUES (?, ?, ?, ?, ?, ?)',
            [row['id'], row['name'], row['pattern'], row['created_by'], row['members_serve'], row['citation_status']],
        )

    matched = con.execute(
        "SELECT id FROM congressional_commissions WHERE regexp_matches('co-chair, senate caucus on international narcotics control', pattern)"
    ).fetchall()
    assert matched == [('scnc00',)]

    # Validate source-annotations-codes.sql in DuckDB (using DuckDB regexp_extract equivalent check + syntax check on print covers)
    signals = json.loads((ROOT / 'model/registries/page-signals.json').read_text())
    con.execute('CREATE TABLE page_signals (id VARCHAR, kind VARCHAR, pattern VARCHAR, number BIGINT)')
    for s in signals:
        con.execute('INSERT INTO page_signals VALUES (?, ?, ?, ?)', [s['id'], s['kind'], s.get('pattern'), s.get('number')])

    con.execute(
        'CREATE TABLE page_facts (body_sha BLOB, status VARCHAR, xml_root VARCHAR, title VARCHAR, '
        'heading VARCHAR, text_head VARCHAR, text_bytes BIGINT, link_count BIGINT, link_text_bytes BIGINT)'
    )
    con.execute(
        "INSERT INTO page_facts VALUES "
        "(from_hex('11'), 'completed', NULL, 'Access Denied: Challenges for Women- and Minority-Owned Businesses', "
        "'Small Business Hearing', 'Committee on Small Business hearing testimony and agenda.', 4200, 3, 50), "
        "(from_hex('22'), 'completed', NULL, 'Page Not Found', '', '404 page not found', 250, 1, 10), "
        "(from_hex('33'), 'completed', NULL, '%PDF-1.7', '', '%PDF-1.7 raw pdf error word', 2500, 0, 0)"
    )
    body_signals_sql = (ROOT / 'model/sql/body-signals.sql').read_text()
    rows = {
        r[0].hex(): dict(error_response=r[1])
        for r in con.execute(f'SELECT body_sha, error_response FROM ({body_signals_sql})').fetchall()
    }
    assert rows['11']['error_response'] is False  # substantive Access Denied hearing title preserved
    assert rows['22']['error_response'] is True   # genuine 404 Page Not Found caught
    assert rows['33']['error_response'] is False  # %PDF- raw prefix guarded

    # Also execute transcript-print-covers.sql and page-dates.sql in DuckDB
    con.execute('CREATE MACRO arrow_cast(val, typ) AS val')
    con.execute('CREATE MACRO decode(val, enc) AS from_hex(val)')
    con.execute('CREATE MACRO array_has(arr, elem) AS list_contains(arr, elem)')
    con.execute('CREATE MACRO regexp_match(s, p) AS regexp_extract_all(s, p)')
    con.execute(
        'CREATE TABLE base_normalized (doc_key VARCHAR, body_hex VARCHAR, document_kind VARCHAR[], source_url VARCHAR)'
    )
    gpo_cover_text = (
        'IMPLEMENTING THE FARM BILL\nHEARING\nBEFORE THE\nCOMMITTEE ON AGRICULTURE\n'
        'UNITED STATES SENATE\nS. Hrg. 118-42\nU.S. GOVERNMENT PUBLISHING OFFICE'
    )
    con.execute("INSERT INTO page_facts VALUES (from_hex('44'), 'completed', NULL, 'Hearing', '', ?, 8000, 0, 0)", [gpo_cover_text])
    con.execute(
        "INSERT INTO base_normalized VALUES "
        "('doc_gpo', '44', ['transcript'], 'https://www.govinfo.gov/content/pkg/CHRG-118shrg42/html/CHRG.htm'), "
        "('doc_cms', '55', ['testimony'], 'https://oversight.house.gov/wp-content/uploads/2023/08/item.html'), "
        "('doc_ok', '66', ['testimony'], 'https://oversight.house.gov/hearings/2021-item')"
    )
    tpc_sql = (ROOT / 'model/sql/transcript-print-covers.sql').read_text()
    assert con.execute(tpc_sql).fetchall() == [('doc_gpo',)]

    con.execute('CREATE TABLE page_metadata_documents AS SELECT doc_key, from_hex(body_hex) AS body_sha FROM base_normalized')
    con.execute(
        'CREATE TABLE page_metadata_values (body_sha BLOB, field VARCHAR, format VARCHAR, path VARCHAR, value VARCHAR, date DATE)'
    )
    con.execute('CREATE TABLE html_metadata_readings (body_sha BLOB, base_href VARCHAR)')
    con.execute(
        "INSERT INTO page_metadata_values VALUES "
        "(from_hex('55'), 'published_time', 'opengraph', '/og/0', '2023-08-14', DATE '2023-08-14'), "
        "(from_hex('66'), 'published_time', 'opengraph', '/og/0', '2021-04-15', DATE '2021-04-15')"
    )
    page_dates_sql = (ROOT / 'model/sql/page-dates.sql').read_text().replace(
        "(regexp_match(addr,'(?i)^https?://(?:web[.]archive[.]org/web/|webarchive[.]loc[.]gov/all/|[^/?#]*webharvest[.]gov/[^/?#]+/)([0-9]{4})([0-9]{2})([0-9]{2})[0-9]{6}'))[1]\n   ||'-'||\n   (regexp_match(addr,'(?i)^https?://(?:web[.]archive[.]org/web/|webarchive[.]loc[.]gov/all/|[^/?#]*webharvest[.]gov/[^/?#]+/)([0-9]{4})([0-9]{2})([0-9]{2})[0-9]{6}'))[2]\n   ||'-'||\n   (regexp_match(addr,'(?i)^https?://(?:web[.]archive[.]org/web/|webarchive[.]loc[.]gov/all/|[^/?#]*webharvest[.]gov/[^/?#]+/)([0-9]{4})([0-9]{2})([0-9]{2})[0-9]{6}'))[3]",
        "regexp_extract(addr,'(?i)^https?://(?:web[.]archive[.]org/web/|webarchive[.]loc[.]gov/all/|[^/?#]*webharvest[.]gov/[^/?#]+/)([0-9]{4})([0-9]{2})([0-9]{2})[0-9]{6}', 1) || '-' || regexp_extract(addr,'(?i)^https?://(?:web[.]archive[.]org/web/|webarchive[.]loc[.]gov/all/|[^/?#]*webharvest[.]gov/[^/?#]+/)([0-9]{4})([0-9]{2})([0-9]{2})[0-9]{6}', 2) || '-' || regexp_extract(addr,'(?i)^https?://(?:web[.]archive[.]org/web/|webarchive[.]loc[.]gov/all/|[^/?#]*webharvest[.]gov/[^/?#]+/)([0-9]{4})([0-9]{2})([0-9]{2})[0-9]{6}', 3)",
    )
    pd_rows = con.execute(f'SELECT hex(body_sha), cast(published_on AS VARCHAR) FROM ({page_dates_sql})').fetchall()
    assert pd_rows == [('66', '2021-04-15')]


def test_source_annotations_select_commissions_hsru_host_and_bio_embargo_guards(tmp_path):
    from congress_api.lake import filenames
    import pyarrow as pa
    import pyarrow.parquet as pq

    cases = [
        ('s_scnc', 'hearing.pdf', 'https://www.drugcaucus.senate.gov/wp-content/uploads/2023/05/hearing.pdf', '1' * 64, 'Senate Caucus on International Narcotics Control Hearing'),
        ('s_ccp', 'witness.pdf', 'https://selectcommitteeontheccp.house.gov/media/witness.pdf', '2' * 64, 'Select Committee on the CCP Testimony'),
        ('s_j6', 'report.pdf', 'https://january6th.house.gov/sites/democrats.january6th.house.gov/files/report.pdf', '3' * 64, 'Select Committee Report'),
        ('s_csce', 'briefing.pdf', 'https://www.csce.gov/files/briefing.pdf', '4' * 64, 'Helsinki Commission Briefing'),
        ('s_hsru_host', 'BILLS-118hr1435-RCP118-27.pdf', 'https://docs.house.gov/billsthisweek/20230911/BILLS-118hr1435-RCP118-27.pdf', '5' * 64, 'RULES COMMITTEE PRINT 118-27 TEXT OF H.R. 1435'),
        ('s_hsru_auth', 'HHRG-118-RU00-Transcript-20230912.pdf', 'https://docs.house.gov/meetings/RU/RU00/20230912/116345/HHRG-118-RU00-Transcript-20230912.pdf', '6' * 64, 'FROM THE COMMITTEE ON RULES Providing for consideration of the bill (H.R. 1435)'),
        ('s_bio_trap', 'Smith-Bio.pdf', 'https://www.finance.senate.gov/imo/media/doc/Smith-Bio.pdf', '7' * 64, 'Biography of Jane Smith. Prior to joining the firm, she served as Chief Tax Counsel to the Senate Committee on Finance from 2014 to 2019.'),
        ('s_embargo_trap', 'remarks.pdf', 'https://www.banking.senate.gov/imo/media/doc/remarks.pdf', '8' * 64, 'EMBARGOED UNTIL DELIVERY — Remarks of John Doe. Media contact: Committee on Banking.'),
    ]

    sources = [dict(source_id=sid, filename=fn, source_url=url, body_sha=bsha) for sid, fn, url, bsha, _ in cases]
    fn_rows = [filenames.read_filename(fn, url, catalog_version='current') for _, fn, url, _, _ in cases]
    filename_path = tmp_path / 'filename-readings.parquet'
    pq.write_table(pa.Table.from_pylist(fn_rows, schema=filenames.SCHEMA), filename_path)

    captures = [
        dict(source_id=sid, body_sha=bsha, context_url=url, member_path=None, requested_filename=None, requested_url=url)
        for sid, _, url, bsha, _ in cases
    ]
    pages = [
        dict(body_hex=bsha, status='completed', title='Doc', heading=None, content_date=None, text_head=thead, named_meetings=[])
        for _, _, _, bsha, thead in cases
    ]

    inputs = registry_inputs(tmp_path / 'registries') + [
        dict(name='filename_readings', kind='parquet', path=str(filename_path)),
        json_input(tmp_path, 'source_files', sources, source_id='Utf8', filename='Utf8', source_url='Utf8', body_sha='Utf8'),
        json_input(tmp_path, 'capture_sources', captures, source_id='Utf8', body_sha='Utf8', context_url='Utf8',
                   member_path='Utf8', requested_filename='Utf8', requested_url='Utf8'),
        json_input(tmp_path, 'publisher_links', [], source_id='Utf8', doc_type='Utf8', text='Utf8', page_body='Utf8',
                   context='Utf8', context_url='Utf8', first_good_at='Utf8', link_index='Int64', split_position='Int64'),
        json_input(tmp_path, 'page_inputs', pages, body_hex='Utf8', status='Utf8', title='Utf8', heading='Utf8',
                   content_date='Utf8', text_head='Utf8', named_meetings=list_of('Int64')),
    ]
    steps = [
        dict(name='capture_source_contexts', sql='SELECT * FROM capture_sources'),
        dict(name='page_facts', sql="SELECT decode(body_hex,'hex') AS body_sha,* EXCLUDE(body_hex),cast(content_date AS DATE) AS day,cast(NULL AS VARCHAR) AS xml_root FROM page_inputs"),
        # Empty spicy_committees proves scnc00 and House Select/Commission subdomains resolve without congress-legislators!
        dict(name='spicy_committees', sql='SELECT cast(NULL AS VARCHAR) AS system_code,cast(NULL AS VARCHAR) AS parent_system_code,cast(NULL AS VARCHAR) AS website_url WHERE false'),
        dict(name='meeting_document_urls', sql='SELECT cast(NULL AS BIGINT) AS event_id,cast(NULL AS VARCHAR) AS url WHERE false'),
        dict(name='model_url_keys', sql='SELECT cast(NULL AS VARCHAR) AS url,cast(NULL AS VARCHAR) AS url_key,cast(NULL AS VARCHAR) AS error WHERE false'),
        dict(name='copy_url_keys', sql='SELECT cast(NULL AS VARCHAR) AS source_id,cast(NULL AS VARCHAR) AS url_key WHERE false'),
    ]

    with NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']) as engine:
        res = run_job(
            tmp_path / 'job',
            engine,
            inputs=inputs,
            steps=steps + annotation_steps('current', root=ROOT),
            outputs=[],
            queries=[
                dict(
                    name='cmts',
                    sql='SELECT source_id, host_committee_keys, authoring_committee_keys, committee_keys, chambers '
                        'FROM source_annotation_committees ORDER BY source_id',
                ),
            ],
        )

    by_id = {r['source_id']: r for r in res['cmts']}
    assert by_id['s_scnc']['committee_keys'] == ['scnc00']
    assert by_id['s_ccp']['committee_keys'] == ['hlzs00']
    assert by_id['s_j6']['committee_keys'] == ['hlij00']
    assert by_id['s_csce']['committee_keys'] == ['jcse00']

    # hsru00 floor host vs authoring committee separation
    assert by_id['s_hsru_host']['host_committee_keys'] == ['hsru00']
    assert by_id['s_hsru_host']['authoring_committee_keys'] == []
    assert by_id['s_hsru_host']['committee_keys'] == []

    assert by_id['s_hsru_auth']['host_committee_keys'] == ['hsru00']
    assert by_id['s_hsru_auth']['authoring_committee_keys'] == ['hsru00']
    assert by_id['s_hsru_auth']['committee_keys'] == ['hsru00']

    # -Bio- 180-char career-prose & embargo banner traps excluded from authoring attribution
    assert by_id['s_bio_trap']['host_committee_keys'] == ['ssfi00']
    assert by_id['s_bio_trap']['authoring_committee_keys'] == []
    assert by_id['s_bio_trap']['committee_keys'] == []

    assert by_id['s_embargo_trap']['host_committee_keys'] == ['ssbk00']
    assert by_id['s_embargo_trap']['authoring_committee_keys'] == []
    assert by_id['s_embargo_trap']['committee_keys'] == []


def test_page_dates_sql_guards_cms_upload_folders_and_14_digit_wayback_timestamps(tmp_path):
    def make_page(title, pub_iso, mod_iso=None, canonical=None):
        meta = f'<meta property="article:published_time" content="{pub_iso}">'
        if mod_iso:
            meta += f'<meta property="article:modified_time" content="{mod_iso}">'
        if canonical:
            meta += f'<link rel="canonical" href="{canonical}">'
        return f'<html><head><title>{title}</title>{meta}</head><body><p>Hearing record.</p></body></html>'.encode()

    wp_upload = make_page('2014 Hearing Attachment', '2023-08-14T10:00:00Z')
    drupal_upload = make_page('2016 Witness Bio', '2024-01-22T09:00:00Z')
    wayback_polluted = make_page('Archived Hearing', '2024-05-19T14:22:10Z')
    wayback_preserved = make_page('Archived 2015 Hearing', '2015-06-10', mod_iso='2024-05-19T14:22:10Z')
    normal_page = make_page('Normal Hearing', '2021-04-15')

    documents = [
        ('wp_upload', wp_upload, 'https://oversight.house.gov/wp-content/uploads/2023/08/attachment-page', 'html'),
        ('drupal_upload', drupal_upload, 'https://rules.house.gov/sites/default/files/2024-01/bio-wrapper', 'html'),
        ('wb_polluted', wayback_polluted, 'https://web.archive.org/web/20240519142210/https://finance.senate.gov/hearings/tax', 'html'),
        ('wb_preserved', wayback_preserved, 'https://web.archive.org/web/20240519142210/https://finance.senate.gov/hearings/2015-tax', 'html'),
        ('normal', normal_page, 'https://finance.senate.gov/hearings/2021-hearing', 'html'),
    ]
    bodies = [b for _, b, _, _ in documents]
    readings = []
    for body in bodies:
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
                )
            ],
        )

    got = {r['doc_key']: (r['published_on'], r['modified_on']) for r in res['dates']}
    assert got['wp_upload'] == (None, None)
    assert got['drupal_upload'] == (None, None)
    assert got['wb_polluted'] == (None, None)
    assert got['wb_preserved'] == ('2015-06-10', None)
    assert got['normal'] == ('2021-04-15', None)
