"""Useful filename values survive flattening; parser diagnostics do not."""
from catalog_test_helpers import selected_path
import gzip
import json
from pathlib import Path
import subprocess
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

SCRIPT = Path(__file__).parents[1] / 'docs/youtube-coverage/research/scripts/index_document_filenames.py'
from congress_api.retention import document_index as index


DIAGNOSTICS = {'observations', 'suppressed', 'extraction_json', 'rules', 'capture_refs',
               'parse_status', 'error_code', 'error_message', 'convention_valid',
               'convention_ambiguous', 'parser_source_url', 'start', 'end', 'note'}


def test_metadata_comes_from_the_package_without_requiring_a_valid_convention():
    name = 'HHRG-113-PW00-Bio-OBrienPrimmerM-20130530.docx'
    result = index.Engine().extract(name)
    assert not result['valid']
    assert index.extract((name, None)) == result['metadata']
    assert result['metadata']['document_kind'] == ['witness-biography']


def test_html_extension_fallback_uses_the_same_format_as_response_metadata():
    assert index.file_formats(None, ['htm']) == ['html']
    assert index.file_formats(['text/html'], ['htm']) == ['html']
    assert index.file_formats(['text/html'], ['pdf']) == ['html']


def test_precise_categories_survive_both_parquet_tables_without_retyping_sources(tmp_path):
    (tmp_path / 'indexes').mkdir()
    cases = [
        ('2023-11-02-ebm-results', 'meeting-results', 'other'),
        ('fy24_cjs_bill_text.pdf', 'legislative-text', 'Support Document'),
        ('fy25_thud_senate_bill_summary.pdf', 'summary', 'SD'),
    ]
    sources = [dict(body_key=None, filename=name, source_url=f'https://example.test/{name}',
                    source_document_type=[native_type]) for name, _, native_type in cases]
    # No bodies or receipts: the consumer only interprets supplied filenames.
    index.write_filename_metadata(tmp_path, sources, workers=1)
    filenames = pq.read_table(selected_path(tmp_path / 'indexes/document-filenames.parquet')).to_pylist()
    documents = pq.read_table(selected_path(tmp_path / 'indexes/documents.parquet')).to_pylist()
    for rows in (filenames, documents):
        by_name = {row['filename']: row for row in rows}
        for name, kind, native_type in cases:
            assert by_name[name]['document_kind'] == [kind]
            assert by_name[name]['source_document_type'] == [native_type]
    assert not DIAGNOSTICS & filenames[0].keys()


def test_role_wording_survives_both_tables_without_person_or_source_inference(tmp_path):
    (tmp_path / 'indexes').mkdir()
    name = 'Acting Vice Chairman Jones Testimony.pdf'
    source = dict(body_key=None, filename=name, source_url='https://example.test/jones.pdf',
                  source_document_type=['Witness Statement'], source_committee_code=['hsii00'])
    index.write_filename_metadata(tmp_path, [source], workers=1)
    for filename in ('document-filenames.parquet', 'documents.parquet'):
        row, = pq.read_table(selected_path(tmp_path / 'indexes' / filename)).to_pylist()
        assert row['subject_role_wording'] == ['Vice Chairman']
        assert row['subject_role_wording_code'] == ['vice-chair']
        assert row['subject_role_modifier'] == ['Acting']
        assert row['subject_role_modifier_code'] == ['acting']
        assert row['subject_token'] == ['Jones']
        assert row['source_document_type'] == ['Witness Statement']
        assert row['source_committee_code'] == ['hsii00']
        assert not (DIAGNOSTICS | {'person_id', 'officeholder', 'party', 'author'}) & row.keys()


def test_metadata_refresh_keeps_source_rows_and_identity_without_reopening_evidence(tmp_path):
    (tmp_path / 'indexes').mkdir()
    path = tmp_path / 'indexes/document-filenames.parquet'
    source = dict(body_key='saved-body', filename='Levi Pesata REVISED testimony.pdf',
                  source_url='https://example.test/testimony.pdf',
                  filename_origins=['url_path'], source_paths=['old-cache/testimony.pdf'],
                  media_type=['application/pdf'], http_status=['200'])
    schema = pa.schema([*index.SOURCE_SCHEMA, ('obsolete_metadata', index.STRINGS)])
    index.write_document_indexes(path, [{**source, 'obsolete_metadata': ['old parser']}], schema)
    before = pq.read_table(selected_path(path))
    # The fixture intentionally has no receipts, bodies, captures or inventories.
    run = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path), '--rebuild',
                          '--workers', '1'], check=True, capture_output=True, text=True)
    result = json.loads(run.stdout)
    after = pq.read_table(selected_path(path))
    assert result['rows'] == 1
    assert after.select(list(source)).to_pylist() == [source]
    assert all(after[name].to_pylist() == [None] for name in index.RESPONSE_FIELDS)
    assert after['source_id'].to_pylist() == before['source_id'].to_pylist()
    assert after['document_id'].to_pylist() == before['document_id'].to_pylist()
    assert after['subject_token'].to_pylist() == [['Levi Pesata']]
    assert 'obsolete_metadata' not in after.column_names


def test_explicit_columns_preserve_meanings_and_useful_convention_fields():
    filename = 'HHRG-119-IF14-Wstate-WosinskaM-20260318.pdf'
    row = index.extract((filename, 'https://docs.house.gov/' + filename))
    assert row['congress'] == ['119']
    assert row['committee_code'] == ['IF14']
    assert row['document_token'] == ['Wstate']
    assert row['document_token_code'] == ['wstate']
    assert row['document_token_label'] == ['Witness Testimony or Witness Statement']
    assert row['subject_token'] == ['WosinskaM']
    assert row['date_token_candidates'] == ['2026-03-18']
    assert row['witness_id'] == ['WosinskaM']
    assert row['document_kind'] == ['witness-statement']
    assert row['meeting_date'] == ['20260318']
    assert not DIAGNOSTICS & row.keys()
    assert all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in row.values())


def test_multiple_references_ambiguous_dates_and_unread_names():
    row = index.extract(('HR1-S2-010203.pdf', None))
    assert row['measure_number'] == ['1', '2']
    assert row['measure_references'] == ['hr1', 's2']
    dated = index.extract(('Testimony-01-02-2003.pdf', None))
    assert dated['date_token_candidates'] == ['2003-01-02', '2003-02-01']
    fallback = index.extract(('sammy.pdf', None))
    assert fallback['name_token'] == ['sammy']
    assert 'document_kind' not in fallback
    assert index.extract((None, None)) == {}
    assert index.extract(('a/b.pdf', None)) == {}


def test_bad_url_does_not_hide_readable_filename_metadata():
    name = '2019-07-17 Chairman Paul Opening Statement.pdf'
    row = index.extract((name, 'https://www.hsgac.senate.gov/' + name))
    assert row['date_token_candidates'] == ['2019-07-17']
    assert row['label'] == ['Opening Statement']
    assert not DIAGNOSTICS & row.keys()


def test_api_record_identifier_is_not_a_document_date():
    row = index.extract(('62925', 'https://api.congress.gov/v3/hearing/119/senate/62925?format=json&limit=1'))
    assert row == {'source_record_identifier': ['62925'], 'source_record_type': ['hearing']}
    # A filename elsewhere does not acquire endpoint semantics from its digits.
    ordinary = index.extract(('62925.pdf', 'https://example.test/62925.pdf'))
    assert 'source_record_identifier' not in ordinary
    assert ordinary['extension'] == ['pdf']


def test_rare_values_and_structured_references_are_not_lost():
    row = index.extract(('BILLS-115hr4790-RCP115-67.pdf', None))
    assert row['measure_references'] == ['hr4790']
    assert row['print_congress'] == ['115']
    assert row['rules_committee_print_references'] == ['RCP115-67']
    assert row['print_number'] == ['67']
    versioned = index.extract(('BILLS-115hr1892eas2.pdf', None))
    assert versioned['version_token_label'] == ['Engrossed Amendment Senate']
    assert versioned['stage_occurrence'] == ['2']
    assert versioned['version_number_token'] == ['2']
    report = index.extract(('CRPT-119hrpt12-pt2.pdf', None))
    assert report['report_number'] == ['12']
    assert report['part'] == ['2']


def test_new_semantic_fields_become_columns_without_an_allowlist():
    source = {'observations': [{'fields': [dict(name='new_subject', raw='Something',
        code='s', label='Subject meaning', candidates=['Another reading'],
        start=0, end=9, note='diagnostic', vocabulary_url='https://example.test')]}], 'matches': []}
    assert index.flatten(source) == {'new_subject': ['Something'], 'new_subject_code': ['s'],
        'new_subject_label': ['Subject meaning'], 'new_subject_candidates': ['Another reading']}


@pytest.mark.parametrize(('url', 'expected'), [
    ('https://x.test/A%20B+C.pdf?download=1#fragment', 'A B+C.pdf'),
    ('https://x.test/a%2520b.pdf', 'a%20b.pdf'),
    ('https://x.test/', None), ('https://[invalid', None),
])
def test_url_names_are_decoded_once_without_changing_path_pluses(url, expected):
    assert index.url_filename(url) == expected


def test_response_filename_and_url_are_both_retained():
    row = dict(context_url='https://x.test/download/123', pointer_json='["raw_path"]',
               original_path='/cache/' + 'a' * 64 + '.body.gz')
    record = {'raw_path': row['original_path'], 'response_headers': {
        'CONTENT-DISPOSITION': "attachment; filename=resume.pdf; filename*=UTF-8''r%C3%A9sum%C3%A9.pdf"}}
    names = index.source_names(row, record)
    assert [(n[0], n[1]) for n in names] == [('résumé.pdf', 'content_disposition'), ('123', 'url_path')]
    nested = {'one': record, 'two': {'raw_path': 'other'}}
    assert index.nearest_record(nested, '["two","raw_path"]') == nested['two']
    assert index.source_names({**row, 'context_url': None}, {'raw_path': row['original_path']}) == []
    redirected = {**record, 'final_url': 'https://x.test/BILLS-119hr1ih.pdf'}
    assert index.source_names(row, redirected)[-1][0] == 'BILLS-119hr1ih.pdf'


def test_build_keeps_body_coverage_and_merges_repeated_name_origins(tmp_path):
    (tmp_path/'indexes').mkdir()
    (tmp_path/'receipts').mkdir()
    receipt_key = 'receipts/source.jsonl.gz'
    rows, records = [], []
    for i, (body, url) in enumerate([
        ('one', 'https://one.test/HR1.pdf'), ('one', 'https://one.test/HR1.pdf'),
        ('one', 'https://two.test/HR2.pdf'), ('two', 'https://one.test/HR1.pdf'),
        ('unknown', None), ('one', None),
    ], 1):
        row = dict(family='documents', body_key=body, receipt_key=receipt_key,
                   receipt_line=i, pointer_json='["raw_path"]',
                   context_url=url, original_path='/cache/' + 'a'*64 + '.body.gz')
        rows.append(row)
        record = {'raw_path': row['original_path']}
        if i == 1:
            record['response_headers'] = {'Content-Disposition': 'attachment; filename=HR1.pdf'}
        records.append({'record': record})
    pq.write_table(pa.Table.from_pylist(rows), tmp_path/'indexes/captures.parquet')
    with gzip.open(tmp_path/receipt_key, 'wt') as stream:
        for record in records:
            stream.write(json.dumps(record)+'\n')
    write_inventory(tmp_path/'inventory', [], [])
    subprocess.run([sys.executable, str(SCRIPT), str(tmp_path), '--inventory-dir',
                    str(tmp_path/'inventory'), '--workers', '1'], check=True, capture_output=True)
    table = pq.read_table(selected_path(tmp_path/'indexes/document-filenames.parquet'))
    actual = table.to_pylist()
    assert len(actual) == 4
    assert {r['body_key'] for r in actual} == {'one', 'two', 'unknown'}
    hr1 = next(r for r in actual if r['body_key'] == 'one' and r['filename'] == 'HR1.pdf')
    assert hr1['filename_origins'] == ['content_disposition', 'url_path']
    assert hr1['measure_references'] == ['hr1']
    assert next(r for r in actual if r['body_key'] == 'unknown')['measure_references'] is None
    assert not DIAGNOSTICS & set(table.schema.names)
    assert all(f.name == 'source_occurrences' or pa.types.is_string(f.type) or
               (pa.types.is_list(f.type) and pa.types.is_string(f.type.value_type)) for f in table.schema)
    assert pa.types.is_struct(table.schema.field('source_occurrences').type.value_type)
    assert not (tmp_path/'bodies').exists()


def write_inventory(path, filenames, urls):
    path.mkdir()
    pq.write_table(pa.Table.from_pylist(filenames, schema=pa.schema([
        ('filename_key', pa.string()), ('filename', pa.string()),
        ('variants', pa.list_(pa.string())),
    ])), path/'filenames.parquet')
    pq.write_table(pa.Table.from_pylist(urls, schema=pa.schema([
        ('url', pa.string()), ('filename_keys', pa.list_(pa.string())),
    ])), path/'urls.parquet')


def test_all_known_names_include_unfetched_variants_headers_and_newer_metadata(tmp_path):
    (tmp_path/'indexes').mkdir()
    (tmp_path/'receipts').mkdir()
    key = 'receipts/source.jsonl.gz'
    rows = [dict(family='documents', body_key='saved', receipt_key=key, receipt_line=1,
                 pointer_json='["raw_path"]', context_url='https://a.test/HR1.pdf',
                 original_path='a.pdf'),
            dict(family='documents', body_key=None, receipt_key=key, receipt_line=2,
                 pointer_json=None, context_url=None, original_path=None)]
    pq.write_table(pa.Table.from_pylist(rows), tmp_path/'indexes/captures.parquet')
    with gzip.open(tmp_path/key, 'wt') as stream:
        stream.write(json.dumps({'record': {'raw_path': 'a.pdf'}})+'\n')
        stream.write(json.dumps({'record': {'url': 'https://new.test/New.pdf'}})+'\n')
    files = [dict(filename_key=n.casefold(), filename=n, variants=v) for n,v in [
        ('HR1.pdf', ['HR1.pdf']), ('HR2.pdf', ['HR2.pdf', 'hr2.pdf']),
        ('HR3.pdf', ['HR3.pdf']), ('Statement.pdf', ['Statement.pdf']),
        ('Orphan.pdf', ['Orphan.pdf', 'ORPHAN.pdf']),
    ]]
    urls = [dict(url=u, filename_keys=[k]) for u,k in [
        ('https://a.test/HR1.pdf', 'hr1.pdf'),
        ('https://b.test/HR1.pdf', 'hr1.pdf'),
        ('https://b.test/HR2.pdf', 'hr2.pdf'),
        ('https://b.test/hr2.pdf', 'hr2.pdf'),
        ('https://b.test/download?filename=HR3.pdf', 'hr3.pdf'),
        ('https://b.test/download', 'statement.pdf'),
        # A different header-only filename at an already captured URL is not
        # proof that the saved body contains that document.
        ('https://a.test/HR1.pdf', 'statement.pdf'),
    ]]
    write_inventory(tmp_path/'inventory', files, urls)
    names, _, bodies, variants = index.collect_names(tmp_path, tmp_path/'inventory')
    assert bodies == {'saved'}
    assert variants <= {name for _,name,_ in names}
    assert ('saved', 'HR1.pdf', 'https://a.test/HR1.pdf') in names
    assert (None, 'HR1.pdf', 'https://a.test/HR1.pdf') not in names
    assert (None, 'HR1.pdf', 'https://b.test/HR1.pdf') in names
    assert (None, 'Statement.pdf', 'https://a.test/HR1.pdf') in names
    assert (None, 'Statement.pdf', 'https://b.test/download') in names
    assert (None, 'HR3.pdf', 'https://b.test/download?filename=HR3.pdf') in names
    assert (None, 'New.pdf', 'https://new.test/New.pdf') in names
    assert (None, 'Orphan.pdf', None) in names
    assert (None, 'ORPHAN.pdf', None) in names
    assert (None, 'HR2.pdf', 'https://b.test/HR2.pdf') in names
    assert (None, 'hr2.pdf', 'https://b.test/hr2.pdf') in names


def test_query_filenames_do_not_decode_twice_or_turn_endpoints_into_filenames():
    assert index.url_document_names('https://x.test/download?filename=A%2520B%2BC.pdf') == [
        ('A%20B+C.pdf', 'url_query')]
    assert index.url_document_names('https://x.test/download') == []


def test_response_format_and_status_follow_the_saved_body_not_the_url(tmp_path):
    (tmp_path/'indexes').mkdir()
    (tmp_path/'receipts').mkdir()
    key = 'receipts/source.jsonl.gz'
    url = 'https://x.test/download?download=1'
    records = [
        {'url': url, 'raw_path': 'one', 'http_status': 200,
         'response_headers': {'CONTENT-TYPE': 'application/pdf'},
         'final_url': 'https://x.test/report.pdf'},
        # The same URL can later return an HTML error. Its metadata must stay
        # with that response, even when the path/query suggest a document.
        {'url': url, 'raw_path': 'two', 'http_status': 404,
         'response_headers': {'Content-Type': 'text/html; charset=UTF-8'}},
    ]
    rows = [dict(family='documents', body_key=record['raw_path'], receipt_key=key,
                 receipt_line=i, pointer_json='["raw_path"]', context_url=url,
                 original_path='a'*64+'.body.gz', media_type=None, http_status=record['http_status'])
            for i,record in enumerate(records, 1)]
    pq.write_table(pa.Table.from_pylist(rows), tmp_path/'indexes/captures.parquet')
    with gzip.open(tmp_path/key, 'wt') as stream:
        for record in records:
            stream.write(json.dumps({'record': record})+'\n')
    write_inventory(tmp_path/'inventory', [dict(filename_key='report.pdf', filename='report.pdf',
                                               variants=['report.pdf'])],
                    [dict(url='https://unfetched.test/report.pdf', filename_keys=['report.pdf'])])
    names, _, _, _ = index.collect_names(tmp_path, tmp_path/'inventory')
    assert names[('one', 'download', url)]['media_type'] == {'application/pdf'}
    assert names[('one', 'report.pdf', 'https://x.test/report.pdf')]['http_status'] == {'200'}
    assert names[('two', 'download', url)]['media_type'] == {'text/html; charset=UTF-8'}
    assert names[('two', 'download', url)]['http_status'] == {'404'}
    assert not names[(None, 'report.pdf', 'https://unfetched.test/report.pdf')]['media_type']
    nested = {'one': records[0], 'two': {'raw_path': 'other'}}
    assert index.response_metadata({'pointer_json': '["two","raw_path"]'}, nested) == {
        'media_type': set(), 'http_status': set()}


def test_nomination_subject_and_part_survive_the_flat_export():
    row = index.extract(('01 19 2021 Nominations -- Blinken Part 1.pdf', None))
    assert row['label'] == ['Nominations']
    assert row['subject_token'] == ['Blinken']
    assert row['part_number'] == ['1']
    assert row['date_token_candidates'] == ['2021-01-19']
    assert 'name_token' not in row
    assert 'witness_id' not in row


@pytest.mark.parametrize(('filename', 'subject'), [
    ('01.09.2020 Feinstien Statement.pdf', 'Feinstien'),
    ('Statement 01.09.2020 Feinstien.pdf', 'Feinstien'),
    ('Feinstien 01.09.2020 Statement.pdf', 'Feinstien'),
    ('01.09.2020 123 Feinstien Statement.pdf', 'Feinstien'),
])
def test_flat_subject_uses_refined_text_and_preserves_date_readings(filename, subject):
    row = index.extract((filename, None))
    assert row['subject_token'] == [subject]
    assert row['label'] == ['Statement']
    assert row['date_token'] == ['01.09.2020']
    assert row['date_token_candidates'] == ['2020-01-09', '2020-09-01']
    assert 'witness_id' not in row
    if '123' in filename:
        assert row['generic_identifier'] == ['123']


def test_refinement_does_not_remove_the_same_text_from_an_unrelated_subject():
    def subject(raw, start):
        return dict(name='subject_token', raw=raw, start=start, end=start + len(raw),
                    code=None, label=None, candidates=[])
    result = {'observations': [
        {'scope': 'stem', 'fields': [subject('2020 Smith', 0), subject('2020 Smith', 30)]},
        {'scope': 'subject-refinement', 'fields': [subject('Smith', 5)]},
    ], 'matches': []}
    assert index.flatten(result)['subject_token'] == ['2020 Smith', 'Smith']


def test_root_document_identity_and_preferred_source_are_independent_of_row_order():
    def row(filename, url, subject):
        return dict(body_key='pdf-hash', filename=filename, source_url=url,
                    media_type=['application/pdf'], http_status=['200'],
                    extension=['pdf'] if filename.endswith('.pdf') else None,
                    subject_token=[subject])
    sources = [row('endpoint', 'https://x.test/download/endpoint', 'Endpoint wording'),
               row('transcript.pdf', 'https://x.test/files/transcript.pdf', 'Transcript wording')]
    schema = pa.schema([*index.SOURCE_SCHEMA, ('extension', index.STRINGS), ('subject_token', index.STRINGS)])
    original = [dict(row) for row in sources]
    first, _, documents, _ = index.prepare_document_indexes([dict(row) for row in sources], schema)
    _, _, reversed_documents, _ = index.prepare_document_indexes([dict(row) for row in reversed(sources)], schema)
    assert documents == reversed_documents
    document, = documents
    assert document['filename'] == 'transcript.pdf'
    assert document['filenames'] == ['endpoint', 'transcript.pdf']
    assert document['subject_token'] == ['Endpoint wording', 'Transcript wording']
    assert {r['document_id'] for r in first} == {document['document_id']}
    assert document['source_id'] == first[1]['source_id']
    for before, after in zip(original, first):
        assert all(after[key] == value for key, value in before.items())
    _, _, extended, _ = index.prepare_document_indexes(
        [*first, row('alias', 'https://mirror.test/alias', 'Mirror wording')], schema)
    assert extended[0]['document_id'] == document['document_id']


def test_document_indexes_keep_unknown_files_and_can_refresh_without_parsing(tmp_path, monkeypatch):
    root = tmp_path / 'archive'
    (root / 'indexes').mkdir(parents=True)
    path = root / 'indexes/document-filenames.parquet'
    rows = [dict(body_key=None, filename='unfetched.pdf', source_url='https://x.test/unfetched.pdf')]
    pq.write_table(pa.Table.from_pylist(rows, schema=index.SOURCE_SCHEMA), path)
    def fail(*args, **kwargs):
        pytest.fail('Document regrouping must not parse filenames or collect sources.')
    monkeypatch.setattr(index, 'extract', fail)
    monkeypatch.setattr(index, 'collect_names', fail)
    assert index.reindex_documents(root)['document_rows'] == 1
    source = pq.read_table(selected_path(path))
    document = pq.read_table(selected_path(path.with_name('documents.parquet')))
    assert source['body_key'].to_pylist() == [None]
    assert document['body_keys'].to_pylist() == [None]
    assert document['source_urls'].to_pylist() == [['https://x.test/unfetched.pdf']]
    assert source.schema.metadata[b'catalog_id'] == document.schema.metadata[b'catalog_id']
    first_id = document['document_id'].to_pylist()
    index.reindex_documents(root)
    assert pq.read_table(selected_path(path.with_name('documents.parquet')))['document_id'].to_pylist() == first_id


def source_meeting(event='1001', congress=119, chamber='House', committee='hsif14'):
    return {'eventId': event, 'congress': congress, 'chamber': chamber,
            'date': '2025-06-01T10:00:00Z', 'title': 'Budget hearing', 'type': 'Hearing',
            '_url': f'https://api.congress.gov/v3/committee-meeting/{congress}/{chamber.lower()}/{event}',
            'committees': [{'systemCode': committee, 'name': 'Energy and Commerce'}],
            'meetingDocuments': [{'url': 'https://docs.test/report.pdf', 'documentType': 'Support Document',
                                  'name': 'Report on the budget', 'format': 'PDF'}],
            'witnessDocuments': [{'url': 'https://docs.test/testimony.pdf', 'documentType': 'Witness Statement'}]}


def test_source_context_uses_the_parent_meeting_and_exact_document_url():
    context = index.DocumentSources()
    context.add_meeting(source_meeting())
    report = context.for_url('https://docs.test/report.pdf')
    assert report['source_committee_code'] == ['hsif14']
    assert report['source_meeting_key'] == ['119/house/1001']
    assert report['source_document_type'] == ['Support Document']
    assert report['source_document_group'] == ['meetingDocuments']
    assert context.for_url('https://docs.test/testimony.pdf')['source_document_group'] == ['witnessDocuments']
    assert context.for_url('https://other.test/report.pdf') == {}
    assert context.for_url('https://docs.test/report.pdf?version=2') == {}


def test_shared_documents_keep_multiple_meetings_without_replacing_filename_metadata():
    context = index.DocumentSources()
    context.add_meeting(source_meeting())
    context.add_meeting(source_meeting('1002', committee='hsbu00'))
    data = context.for_url('https://docs.test/report.pdf')
    assert data['source_committee_code'] == ['hsbu00', 'hsif14']
    assert data['source_meeting_id'] == ['1001', '1002']
    assert 'committee_code' not in data and 'congress' not in data


def test_inventory_joins_explicit_events_and_keeps_source_document_typing():
    context = index.DocumentSources()
    context.add_meeting(source_meeting())
    context.add_inventory({'url': 'http://legacy.test/file.pdf', 'observations': [
        {'event_id': '1001', 'chamber': 'House', 'congress': 119,
         'group': 'meeting-document', 'group_attributes': {'type': 'BR'},
         'description': 'Bill as reported', 'native_file': {'doc-type': 'PDF'}}]})
    data = context.for_url('http://legacy.test/file.pdf')
    assert data['source_committee_code'] == ['hsif14']
    assert data['source_document_type'] == ['BR']
    assert data['source_document_label'] == ['Bill as reported']
    assert data['source_document_group'] == ['meeting-document']


def test_event_ids_do_not_cross_chambers_or_ambiguous_congresses():
    context = index.DocumentSources()
    context.add_meeting(source_meeting())
    context.add_meeting(source_meeting(chamber='Senate', committee='ssfi00'))
    context.add_inventory({'url': 'https://docs.test/unqualified.pdf', 'observations': [{'event_id':'1001'}]})
    assert 'source_committee_code' not in context.for_url('https://docs.test/unqualified.pdf')
    context.add_inventory({'url': 'https://docs.test/senate.pdf', 'observations': [{'event_id':'1001','chamber':'Senate'}]})
    assert context.for_url('https://docs.test/senate.pdf')['source_committee_code'] == ['ssfi00']


def test_senate_page_metadata_belongs_to_its_own_documents_only():
    context = index.DocumentSources()
    context.add_senate({'finance.senate.gov': {'pages': {
        'https://www.finance.senate.gov/hearings/one': {'title':'First hearing',
            'event': {'date':'2025-03-04','type':'Hearing'},
            'documents': [['statement','First witness','https://docs.test/one.pdf']]},
        'https://www.finance.senate.gov/hearings/two': {'title':'Second hearing',
            'documents': [['other','Second witness','https://docs.test/two.pdf']]},
    }}})
    data = context.for_url('https://docs.test/one.pdf')
    assert data['source_page_title'] == ['First hearing']
    assert data['source_page_url'] == ['https://www.finance.senate.gov/hearings/one']
    assert data['source_publisher_committee_code'] == ['ssfi00']
    assert data['source_document_label'] == ['First witness']
    assert 'source_committee_code' not in data  # Host identifies publisher, not meeting subcommittee.


def test_senate_links_keep_exact_anchor_and_witness_card_metadata():
    context = index.DocumentSources()
    url = 'https://www.aging.senate.gov/download/sca-example'
    unowned = 'https://www.aging.senate.gov/download/sca-chair'
    context.add_senate({'aging.senate.gov': {'pages': {'https://www.aging.senate.gov/hearings/one': {
        'documents': [['other', 'SCA_example', url], ['other', 'SCA_chair', unowned]],
        'document_labels': {url: 'Download testimony', unowned: ''},
        'document_metadata': {url: {'labels': ['Witness attachment'], 'witness_indexes': [0, True, -1, 99, '1']},
                              unowned: {'witness_indexes': []}},
        'witnesses': [{'name': 'Stephanie Blunt', 'position': 'Executive Director',
                       'organization': 'Trident Area Agency on Aging'}, {'name': 'Wrong witness'}],
    }}}})
    row = context.for_url(url)
    assert row['source_link_url'] == [url]
    assert row['source_link_label'] == ['Download testimony', 'Witness attachment']
    assert row['source_witness_name'] == ['Stephanie Blunt']
    assert row['source_witness_position'] == ['Executive Director']
    assert row['source_witness_organization'] == ['Trident Area Agency on Aging']
    assert row['source_document_type'] == ['other']
    index.fill_document_kind(row)
    assert row['document_kind'] is None
    assert not context.for_url(unowned).get('source_witness_name')


def test_retained_redirect_transfers_link_context_without_guessing_from_basename():
    context = index.DocumentSources()
    requested = 'https://www.epw.senate.gov/public/?a=Files.Serve&File_id=ABC'
    final = 'https://www.epw.senate.gov/public/_cache/files/hash.spw.pdf'
    context.add_inventory({'url': requested, 'observations': [{'page_url': 'https://www.epw.senate.gov/hearings/one',
                           'kind': 'other', 'label': 'SPW 03152023.pdf'}]})
    context.add_redirect({'url': requested, 'final_url': final, 'http_status': 200, 'usable': True})
    row = context.for_url(final)
    assert row['source_page_url'] == ['https://www.epw.senate.gov/hearings/one']
    assert row['source_link_url'] == [requested]
    assert row['source_document_type'] == ['other']
    assert context.for_url('https://unrelated.test/hash.spw.pdf') == {}
    context.add_redirect({'url': requested, 'final_url': 'https://www.epw.senate.gov/login',
                          'http_status': 403, 'usable': False})
    failed = context.for_url('https://www.epw.senate.gov/login')
    assert failed['source_page_url'] == ['https://www.epw.senate.gov/hearings/one']
    assert failed['source_association_basis'] == ['publisher_redirect']
    assert failed['source_associated_url'] == [requested]
    assert 'document_kind' not in failed  # Provenance is not usable-content evidence.


def test_legacy_misrouted_downloads_recover_retained_bodies(tmp_path):
    (tmp_path/'indexes').mkdir()
    (tmp_path/'receipts').mkdir()
    requested = 'https://www.epw.senate.gov/public/?a=Files.Serve&File_id=ABC'
    final = 'https://www.epw.senate.gov/public/_cache/files/hash.spw.pdf'
    key = 'receipts/legacy.jsonl.gz'
    with gzip.open(tmp_path/key, 'wt') as f:
        f.write(json.dumps({'record': {'url': requested, 'final_url': final, 'raw_path': 'body.gz'}})+'\n')
    pq.write_table(pa.Table.from_pylist([dict(family='senate/pages', body_key='retained',
        receipt_key=key, receipt_line=1, pointer_json='["raw_path"]', context_url=requested,
        original_path='body.gz')]), tmp_path/'indexes/captures.parquet')
    write_inventory(tmp_path/'inventory', [dict(filename_key='hash.spw.pdf', filename='hash.spw.pdf',
        variants=['hash.spw.pdf'])], [dict(url=final, filename_keys=['hash.spw.pdf'])])
    names, _, bodies, _ = index.collect_names(tmp_path, tmp_path/'inventory')
    assert bodies == {'retained'}
    assert ('retained', 'hash.spw.pdf', final) in names
    assert (None, 'hash.spw.pdf', final) not in names
    assert index.collect_names(tmp_path, tmp_path/'inventory', families=('house/meeting-xml',))[2] == set()


def test_source_refresh_preserves_parser_fields_ids_and_alias_context(tmp_path):
    (tmp_path/'indexes').mkdir()
    path=tmp_path/'indexes/document-filenames.parquet'
    rows=[dict(body_key='same-body',filename='report.pdf',source_url=url,
               media_type=['application/pdf'],http_status=['200'],committee_code=['IF14'])
          for url in ['https://docs.test/report.pdf','https://alias.test/report.pdf']]
    schema=pa.schema([*index.SOURCE_SCHEMA,('committee_code', index.STRINGS)])
    index.write_document_indexes(path,rows,schema)
    before=pq.read_table(selected_path(path))
    context=index.DocumentSources();context.add_meeting(source_meeting())
    index.refresh_source_metadata(tmp_path,context)
    after=pq.read_table(selected_path(path))
    unchanged=[name for name in before.column_names
               if name not in {'document_kind', 'document_kind_source', 'document_family'}]
    assert before.select(unchanged).equals(after.select(unchanged),check_metadata=False)
    assert after['document_kind'].to_pylist()==[['support-document'],None]
    assert after['document_kind_source'].to_pylist()==[['source_document_type'],None]
    assert after['document_family'].to_pylist()==[['supporting-material'],None]
    docs=pq.read_table(selected_path(path.with_name('documents.parquet'))).to_pylist()
    assert len(docs)==1 and docs[0]['source_committee_code']==['hsif14']
    assert docs[0]['committee_code']==['IF14']
    assert after.to_pylist()[1]['source_committee_code'] is None
    # A filename-only refresh keeps the previously retained source context.
    subprocess.run([sys.executable, str(SCRIPT), str(tmp_path), '--metadata-only',
                    '--workers', '1'], check=True, capture_output=True)
    assert pq.read_table(selected_path(path))['source_committee_code'].to_pylist()==[['hsif14'],None]


def test_source_metadata_cli_reads_retained_records_without_fetching(tmp_path):
    (tmp_path/'indexes').mkdir()
    entries=[('congress/meetings','input/congress_meetings.jsonl.gz',source_meeting()),
             ('documents','input/documents/inventory.jsonl.gz',{
                 'url':'https://legacy.test/report.pdf','observations':[{
                     'event_id':'1001','chamber':'House','congress':119,
                     'group':'meeting-document','group_attributes':{'type':'BR'},
                     'description':'Legacy bill copy'}]}),
             ('senate/pages','input/documents/receipts.jsonl', {
                 'url':'https://legacy.test/report.pdf', 'final_url':'https://final.test/copy.pdf',
                 'http_status':200, 'usable':True})]
    captures=[]
    for n,(family,source,record) in enumerate(entries):
        key=f'receipts/{n}.jsonl.gz'
        (tmp_path/key).parent.mkdir(exist_ok=True)
        with gzip.open(tmp_path/key,'wt') as f:
            f.write(json.dumps({'source_file':source,'record':record})+'\n')
        captures.append(dict(family=family,source_file=source,receipt_key=key,receipt_line=1))
    pq.write_table(pa.Table.from_pylist(captures),tmp_path/'indexes/captures.parquet')
    path=tmp_path/'indexes/document-filenames.parquet'
    index.write_document_indexes(path,[dict(filename='report.pdf',source_url='https://legacy.test/report.pdf',
                                           body_key=None)],index.SOURCE_SCHEMA)
    run=subprocess.run([sys.executable,str(SCRIPT),str(tmp_path),'--source-metadata-only'],
                       check=True,capture_output=True,text=True)
    assert json.loads(run.stdout)['rows'] >= 1
    from congress_api.retention.catalog_publication import local_catalog_paths
    record=next(row for row in pq.read_table(selected_path(local_catalog_paths(tmp_path)[1])).to_pylist()
                if row['source_url']=='https://legacy.test/report.pdf')
    assert record['source_committee_code']==['hsif14']
    assert record['source_document_type']==['BR']
    assert record['source_meeting_key']==['119/house/1001']
    redirect=index.read_document_sources(tmp_path, {'https://final.test/copy.pdf'}).for_url('https://final.test/copy.pdf')
    assert redirect['source_meeting_key']==['119/house/1001']
    assert redirect['source_link_url']==['https://legacy.test/report.pdf']
    assert not (tmp_path/'bodies').exists()


def test_discovery_fixes_survive_both_parquet_tables(tmp_path):
    (tmp_path / 'indexes').mkdir()
    cases = [
        ('HHRG-113-JU00-Transcript-20130719.pdf&download=1',
         {'document_kind': ['committee-transcript']}),
        ('aa11bb22-1234-abcd-5678-000000000000_spw-12032025-hearing-on-nominations-of-beaman-and-weaver.pdf',
         {'name_token': ['spw-12032025-hearing-on-nominations-of-beaman-and-weaver']}),
        ('Smith (ACME) Testimony.pdf', {'subject_token': ['Smith (ACME)']}),
        ('Additional Materials for Norton Testimony 5-19-22.pdf',
         {'document_kind': ['supporting-material'], 'target_document_kind': ['testimony']}),
        ('the-path-forward-key-findings-in-the-syria-study-group-report-transcript-092419',
         {'subject_token': ['the-path-forward-key-findings-in-the-syria-study-group-report']}),
        ('chairman-s-opening-statement-final.pdf',
         {'subject_token': None, 'subject_role_wording_code': ['chair']}),
    ]
    sources = [dict(body_key=None, filename=name, source_url=f'https://example.test/source/{i}',
                    source_document_type=['Unchanged publisher value']) for i, (name, _) in enumerate(cases)]
    index.write_filename_metadata(tmp_path, sources, workers=1)
    for filename in ('document-filenames.parquet', 'documents.parquet'):
        by_name = {name: r for r in pq.read_table(selected_path(tmp_path / 'indexes' / filename)).to_pylist()
                   for name in (r.get('filenames') or [r['filename']])}
        for name, expected in cases:
            assert {key: by_name[name].get(key) for key in expected} == expected
            assert by_name[name]['source_document_type'] == ['Unchanged publisher value']
        assert not DIAGNOSTICS & set(next(iter(by_name.values())))
