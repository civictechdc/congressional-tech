"""Availability is a relationship, never a substitute capture or grouping key."""
import json

import pyarrow as pa
import pytest

from congress_api.retention import document_index as index
from congress_api.retention.catalog_availability import annotate_availability, hearing_package, package_from_format
from congress_api.retention.raw_archive import STATE_SCHEMA, STATE_KEY, encode_table
from congress_api.retention.raw_catalog import rebuild_catalog
from test_raw_source_sync import MemoryStore
from test_raw_catalog import table
from test_raw_rebuild import retain


def state(*rows):
    return pa.Table.from_pylist(rows, schema=STATE_SCHEMA)


def saved(package, kind='pdf'):
    suffix = 'pdf' if kind == 'pdf' else 'htm'
    return dict(url=f'https://www.govinfo.gov/content/pkg/{package}/{kind}/{package}.{suffix}',
                body_key='bodies/' + package + '.' + suffix, outcome='retained', http_status=200,
                media_type='application/pdf' if kind == 'pdf' else 'text/html')


def test_endpoint_candidate_never_changes_api_response_or_merges_documents(tmp_path):
    api = 'https://api.congress.gov/v3/hearing/118/senate/53528?format=json'
    pdf = saved('CHRG-118shrg53528')
    rows = list(annotate_availability([dict(body_key=None, filename='53528', source_url=api,
        http_status=['403'], capture_outcome=['http_error'])], state(pdf)))
    reference = rows[0]
    assert reference['body_key'] is None and reference['http_status'] == ['403']
    assert reference['hearing_resources'][0]['association_basis'] == 'endpoint_package_candidate'
    index.write_filename_metadata(tmp_path, rows, workers=1)
    from congress_api.retention.catalog_publication import local_catalog_paths
    import pyarrow.parquet as pq
    sources, documents = [pq.read_table(p).to_pylist() for p in local_catalog_paths(tmp_path)]
    assert len(documents) == 2
    reference = next(row for row in sources if row['source_url'] == api)
    assert reference['record_role'] == ['source-record']
    assert reference['body_key'] is None and reference['http_status'] == ['403']
    assert reference['hearing_resources'][0]['body_key'] == pdf['body_key']


@pytest.mark.parametrize(('path', 'package'), [
    ('115/house/2', 'CHRG-115hhrg24725-pt2'),
    ('116/house/1', 'CHRG-116hhrg49571-add1'),
    ('116/joint/40895', 'CHRG-116shrg40895'),
    ('118/senate/49104057', 'CHRG-118shrg049104057'),
    ('116/house/49708', 'CHRG-117hhrg49708'),
])
def test_native_formats_override_conventional_package_without_event_inference(path, package):
    api = f'https://api.congress.gov/v3/hearing/{path}?format=json'
    publisher = f'https://congress.gov/{path.split("/")[0]}/chrg/{package}/{package}.pdf'
    record = dict(url=api, hearing={'formats': [{'type': 'PDF', 'url': publisher}]})
    captured = [dict(body_key='api-json-body', pointer_json='["content", "body"]')]
    pdf = saved(package)
    rows = list(annotate_availability([dict(body_key=None, filename='1', source_url=api + '&limit=1')],
        state(pdf, saved(hearing_package(api))), hearing_records=[(record, captured)]))
    assert rows[0]['hearing_package_id'] == [package]
    related, = rows[0]['hearing_resources']
    assert related['publisher_format_url'] == publisher
    assert related['association_basis'] == 'publisher_api_format_package'
    assert related['api_response_body_key'] == 'api-json-body'
    assert not rows[0].get('source_committee_code') and not rows[0].get('source_meeting_id')


def test_failed_body_or_matching_basename_does_not_establish_availability():
    api = 'https://api.congress.gov/v3/hearing/118/senate/53528'
    pdf = saved('CHRG-118shrg53528'); pdf['outcome'] = 'http_error'; pdf['http_status'] = 404
    unrelated = dict(pdf, url='https://other.test/CHRG-118shrg53528.pdf', outcome='saved', http_status=200)
    rows = list(annotate_availability([dict(body_key=None, filename='53528', source_url=api)], state(pdf, unrelated)))
    assert rows[0]['hearing_resources'] is None
    assert package_from_format('https://fake.gov/content/pkg/CHRG-118shrg53528/pdf/CHRG-118shrg53528.pdf') is None
    assert hearing_package('https://api.congress.gov.evil/v3/hearing/118/senate/53528') is None


@pytest.mark.parametrize(('outcome', 'media'), [('html', 'text/html'), ('saved', 'text/html'), ('saved', 'application/zip')])
def test_pdf_url_that_served_other_bytes_is_not_a_retained_pdf(outcome, media):
    api = 'https://api.congress.gov/v3/hearing/114/house/94225'
    wrong = dict(saved('CHRG-114hhrg94225'), outcome=outcome, media_type=media)
    wrong['url'] = wrong['url'].replace('https://www.govinfo.gov/content/', 'http://www.gpo.gov/fdsys/')
    row = next(annotate_availability([dict(source_url=api, body_key=None, filename='94225')], state(wrong)))
    assert row['hearing_resources'] is None


def test_current_state_only_urls_are_queryable_without_fake_success(tmp_path):
    store = MemoryStore()
    current = [dict(url='https://publisher.gov/never-captured', outcome='pending', attempts=0),
               dict(url='https://publisher.gov/missing.pdf', outcome='http_error', http_status=404)]
    store.objects[STATE_KEY] = encode_table(state(*current))
    before = store.objects[STATE_KEY]
    result = rebuild_catalog(store, workers=1)
    assert result['rows'] == 2
    rows = {row['source_url']: row for row in table(store).to_pylist()}
    assert set(rows) == {row['url'] for row in current}
    assert all(row['body_key'] is None and row['record_role'] == ['capture-state'] for row in rows.values())
    assert rows[current[0]['url']]['state_outcome'] == ['pending']
    assert store.objects[STATE_KEY] == before
    assert not any(key in {STATE_KEY, 'indexes/captures.parquet'} for key in store.writes)
    # New URL-only state must invalidate the ordinary no-new-receipts fast path.
    store.objects[STATE_KEY] = encode_table(state(*current, dict(url='https://publisher.gov/new', outcome='pending')))
    assert rebuild_catalog(store, workers=1)['rows'] == 3
    assert rebuild_catalog(store, workers=1)['unchanged'] is True


def test_rebuild_reads_exact_hearing_formats_from_retained_metadata_receipts():
    store = MemoryStore()
    package = 'CHRG-116shrg40895'
    api = 'https://api.congress.gov/v3/hearing/116/joint/40895?format=json'
    native = dict(requested_url=api, http_status=200, hearing={'formats': [
        {'type': 'PDF', 'url': f'https://congress.gov/116/chrg/{package}/{package}.pdf'}]})
    retain(store, native, family='congress/hearings', source_file='api.json', url=api,
           body=json.dumps(native).encode(), pointer=['content', 'body'])
    store.objects[STATE_KEY] = encode_table(state(saved(package), dict(url=api, outcome='retained', body_key='api-body', http_status=200)))
    rebuild_catalog(store, workers=1)
    reference = next(row for row in table(store).to_pylist() if row['source_url'] == api)
    assert reference['hearing_package_id'] == [package]
    assert reference['hearing_resources'][0]['association_basis'] == 'publisher_api_format_package'


def test_corrupt_state_fails_before_publishing_or_replacing_archive_state():
    store = MemoryStore()
    store.objects[STATE_KEY] = b'not a parquet state'
    with pytest.raises(pa.ArrowInvalid):
        rebuild_catalog(store, workers=1)
    assert not store.writes


def test_availability_survives_static_publication(tmp_path):
    import importlib.util
    from pathlib import Path
    import pyarrow.parquet as pq
    from congress_api.retention.catalog_publication import local_catalog_paths
    script=Path(__file__).resolve().parents[1]/'apps/site/scripts/publish-filename-viewer.py'
    spec=importlib.util.spec_from_file_location('availability_publication',script)
    publisher=importlib.util.module_from_spec(spec);spec.loader.exec_module(publisher)
    api='https://api.congress.gov/v3/hearing/118/senate/53528?format=json'
    pdf=saved('CHRG-118shrg53528')
    missing=dict(url='https://committee.test/missing',outcome='pending')
    rows=list(annotate_availability([dict(body_key=None, filename='53528', source_url=api,
        source_occurrences=[dict(source_occurrence_scope=['source_record'], source_page_url=[api])])], state(pdf,missing)))
    index.write_filename_metadata(tmp_path,rows,workers=1)
    output=tmp_path/'public'
    publication=publisher.publish(tmp_path,output)
    for name,path in zip(('filenames','documents'),local_catalog_paths(tmp_path)):
        original=pq.read_table(path)
        published=pq.read_table(output/publication['files'][name]['path'])
        assert original.equals(published,check_metadata=True)
    sources=pq.read_table(local_catalog_paths(tmp_path)[0]).to_pylist()
    reference=next(row for row in sources if row['source_url']==api)
    assert reference['body_key'] is None
    assert reference['hearing_resources'][0]['association_basis']=='endpoint_package_candidate'
    unavailable=next(row for row in sources if row['source_url']==missing['url'])
    assert unavailable['record_role']==['capture-state']
    assert unavailable['state_outcome']==['pending']


def test_filename_refresh_preserves_availability_and_structured_resources(tmp_path):
    from congress_api.retention.catalog_publication import local_catalog_paths
    import pyarrow.parquet as pq

    api = 'https://api.congress.gov/v3/hearing/118/senate/53528?format=json'
    rows = list(annotate_availability(
        [dict(body_key=None, filename='53528', source_url=api)],
        state(saved('CHRG-118shrg53528'), dict(url='https://committee.test/pending', outcome='pending'))))
    index.write_filename_metadata(tmp_path, rows, workers=1)
    before = [pq.read_table(path) for path in local_catalog_paths(tmp_path)]
    index.refresh_filename_metadata(tmp_path, workers=1)
    after = [pq.read_table(path) for path in local_catalog_paths(tmp_path)]
    for original, refreshed in zip(before, after, strict=True):
        assert original.equals(refreshed)
