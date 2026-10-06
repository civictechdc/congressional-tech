"""Diagnostic candidates stay retained without becoming routine downloads."""

import pyarrow as pa
import pytest

from congress_api.parsers.archive_links import allowed_url
from congress_api.retention.raw_archive import Archive, encode_table
from test_raw_source_sync import MemoryStore


def catalog_store(rows, *, provenance=True):
    schema = pa.schema([
        ('source_url', pa.string()), ('body_key', pa.string()),
        ('format', pa.list_(pa.string())), ('http_status', pa.list_(pa.string())),
        ('media_type', pa.list_(pa.string())),
    ] + ([
        ('source_association_basis', pa.list_(pa.string())),
        ('source_occurrences', pa.list_(pa.struct([
            ('source_association_basis', pa.list_(pa.string())),
            ('source_link_url', pa.list_(pa.string())),
        ]))),
    ] if provenance else []))
    store = MemoryStore()
    store.objects['indexes/document-filenames.parquet'] = encode_table(
        pa.Table.from_pylist(rows, schema=schema))
    return store


def test_probe_only_candidate_is_preserved_without_pending_download():
    url = 'https://www.govinfo.gov/content/pkg/BILLS-115s2322es/pdf/BILLS-115s2322es.xml'
    store = catalog_store([dict(
        source_url=url, source_association_basis=['generated_xml_probe'],
        source_occurrences=[dict(source_association_basis=['generated_xml_probe'])])])
    before = dict(store.objects)
    assert url not in Archive(store, 'read-probe').state
    assert store.objects == before


def test_independent_publisher_link_admits_url_despite_generated_probe():
    url = 'https://example.gov/statement.xml'
    store = catalog_store([dict(
        source_url=url, source_association_basis=['generated_xml_probe'],
        source_occurrences=[
            dict(source_association_basis=['generated_xml_probe']),
            dict(source_link_url=[url]),
        ])])
    assert Archive(store, 'read-publisher').state[url]['outcome'] == 'pending'


def test_probe_association_does_not_masquerade_as_independent_publisher_link():
    url = 'https://example.gov/generated.xml'
    store = catalog_store([dict(source_url=url, source_occurrences=[dict(
        source_association_basis=['generated_xml_probe'], source_link_url=[url])])])
    assert url not in Archive(store, 'read-associated-probe').state


def test_legacy_filename_catalog_without_optional_provenance_still_loads():
    url = 'https://example.gov/statement.xml'
    assert Archive(catalog_store([dict(source_url=url)], provenance=False),
                   'read-legacy').state[url]['outcome'] == 'pending'


@pytest.mark.parametrize('url', [
    'https://example.gov/a.xmlhttps://example.gov/b.xml',
    'https://example.gov/a.xmlhttps:/example.gov/b.xml',
    'https://example.gov/a.xmlhttp://example.gov/b.xml',
])
def test_concatenated_schemes_in_path_are_not_download_urls(url):
    assert allowed_url(url) is None


def test_query_embedded_url_remains_a_valid_download_url():
    url = 'https://example.gov/download?url=https://example.gov/file.xml'
    assert allowed_url(url) == url


def test_excluded_probe_stays_deferred_until_independent_publisher_seed():
    from congress_api.acquisition.raw_sync import run_sync
    from test_raw_source_sync import response
    store = MemoryStore()
    archive = Archive(store, 'excluded')
    url = 'https://example.gov/generated.xml'
    archive.seed({'url': url})
    archive.state[url]['outcome'] = 'excluded_probe'
    archive.save()
    result = run_sync(Archive(store, 'skip'), [], fetch=lambda _: pytest.fail('Excluded probe fetched'))
    assert result['attempted'] == result['remaining'] == 0
    result = run_sync(Archive(store, 'publisher'), [{'url': url}],
                      fetch=lambda u: response(u, b'<bill/>', media='application/xml'))
    assert result['saved'] == 1
