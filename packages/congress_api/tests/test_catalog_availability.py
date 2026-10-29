"""Availability is a relationship, never a substitute capture or grouping key."""
import json

import pyarrow as pa
import pytest

from congress_api.retention import document_index as index
from congress_api.retention.catalog_availability import annotate_availability, hearing_package, package_from_format
from congress_api.retention.raw_archive import STATE_SCHEMA, STATE_KEY, encode_table
from historical_raw_catalog import rebuild_catalog
from testing_fakes import MemoryStore
from test_raw_catalog import table
from test_raw_rebuild import retain


from congress_api.retention.raw_schemas import LEGACY_STATE_SCHEMA


def state(*rows):
    if any('body_key' in r for r in rows):
        legacy_rows = []
        for r in rows:
            row = dict(r)
            if isinstance(row.get('sha256'), bytes):
                row['sha256'] = row['sha256'].hex()
            for ts_col in ('retrieved_at', 'checked_at', 'next_attempt_at'):
                if row.get(ts_col) is not None:
                    row[ts_col] = str(row[ts_col])
            legacy_rows.append(row)
        return pa.Table.from_pylist(legacy_rows, schema=LEGACY_STATE_SCHEMA)
    return pa.Table.from_pylist(rows, schema=STATE_SCHEMA)


def saved(package, kind='pdf'):
    from hashlib import sha256
    from congress_api.retention.raw_archive import derive_body_key
    suffix = 'pdf' if kind == 'pdf' else 'htm'
    media = 'application/pdf' if kind == 'pdf' else 'text/html'
    digest = sha256(f'{package}.{suffix}'.encode()).digest()
    return dict(url=f'https://www.govinfo.gov/content/pkg/{package}/{kind}/{package}.{suffix}',
                body_key=derive_body_key(digest, media), sha256=digest, outcome='retained', http_status=200,
                media_type=media)


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


@pytest.mark.parametrize('disk_staging', [False, True])
def test_state_retained_body_is_exposed_without_rewriting_existing_observation(tmp_path, disk_staging):
    url = 'https://www.govinfo.gov/metadata/pkg/CHRG-117shrg45248/mods.xml'
    current = dict(url=url, body_key='bodies/retained.xml', outcome='retained', http_status=200,
                   media_type='application/xml')
    original = dict(body_key=None, filename='mods.xml', source_url=url,
                    source_page_title=['Publisher reference'],
                    source_occurrences=[dict(source_occurrence_scope=['source_record'], source_page_url=[url])])
    from congress_api.retention.catalog_staging import WorkingCatalog
    working = WorkingCatalog(tmp_path / 'availability.sqlite') if disk_staging else None
    try:
        rows = list(annotate_availability([original], state(current), working=working))
    finally:
        if working is not None:
            working.close()
    assert len(rows) == 2
    assert rows[0]['body_key'] is None
    assert rows[0]['source_page_title'] == ['Publisher reference']
    assert rows[1]['body_key'] == current['body_key']
    assert rows[1]['source_paths'] == [STATE_KEY]
    assert 'source_receipt_key' not in rows[1]
    assert list(annotate_availability(rows, state(current))) == rows
    index.write_filename_metadata(tmp_path, rows, workers=1)


@pytest.mark.parametrize('outcome,status', [('pending', None), ('http_error', 404)])
def test_failed_state_does_not_add_a_successful_body_to_an_existing_url(outcome, status):
    url = 'https://example.gov/file.pdf'
    rows = list(annotate_availability([dict(source_url=url, body_key=None, filename='file.pdf')],
        state(dict(url=url, body_key='bodies/error.html', outcome=outcome, http_status=status))))
    assert len(rows) == 1 and rows[0]['body_key'] is None






def test_html_reviews_bind_exact_source_and_body():
    from congress_api.retention.saved_responses import content_reviews, saved_response
    reviews = content_reviews()
    assert reviews
    for (url, body), usable in reviews.items():
        row = dict(source_url=url, body_key=body, media_type=['text/html'], http_status=['200'])
        assert saved_response(row) is usable
        assert not saved_response(dict(row, response_body_complete=['false']))
        assert not saved_response(dict(row, http_status=['503']))
        if usable:
            assert not saved_response(dict(row, source_url=url+'?different', response_usable=['false']))
        else:
            assert saved_response(dict(row, body_key=body+'different', response_usable=['true']))


def test_reviewed_error_page_is_unavailable_under_a_redirect_alias():
    from congress_api.retention.saved_responses import reviewed_error_bodies, saved_response
    assert reviewed_error_bodies()
    for body in reviewed_error_bodies():
        assert not saved_response(dict(source_url='https://another.example/redirect-target',
            body_key=body, http_status=['200'], response_usable=['true'], media_type=['text/html']))


def test_govinfo_homepage_is_not_a_saved_hearing_response():
    from congress_api.retention.saved_responses import saved_response
    row = dict(source_url='http://frwebgate.access.gpo.gov/cgi-bin/ getdoc.cgi?dbname=107_house_hearings&docid=f:80978.pdf',
               body_key='bodies/sha256/fc/fcdfbdddc99482aa9e7713ef97561448c14c6b8028d88e2ad6abc28c1c85333c.gz',
               media_type=['text/html'], http_status=['200'], response_body_complete=['true'],
               capture_outcome=['saved'], record_role=['document'])
    assert not saved_response(row)
    assert saved_response(dict(row, source_url='https://www.govinfo.gov/content/pkg/CHRG-107hhrg80978/pdf/CHRG-107hhrg80978.pdf',
        body_key='bodies/sha256/27/2719a915b0c73b9df39eb6344525f3680212d9c2b8ab596dfb6a4da4af7e32f7.gz',
        media_type=['application/pdf'], response_usable=['true']))
