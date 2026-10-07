"""Diagnostic candidates stay retained without becoming routine downloads."""

import pyarrow as pa
import pytest

from congress_api.parsers.archive_links import allowed_url, capture_links, json_links, related_links
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


@pytest.mark.parametrize('prefix', [
    'https://web.archive.org/web/20250610160415id_/',
    'https://web.archive.org/web/20250610160415/',
    'https://webarchive.loc.gov/all/20110707213402/',
])
def test_timestamped_archive_replay_retains_archive_and_original_urls(prefix):
    url = prefix + 'https://example.gov/statement.pdf?edition=1'
    assert allowed_url(url) == url
    assert capture_links({'url': url}) == [{'url': url}]


@pytest.mark.parametrize('url', [
    'https://web.archive.org.evil.example/web/20250610160415/https://example.gov/a.pdf',
    'https://web.archive.org:8443/web/20250610160415/https://example.gov/a.pdf',
    'https://web.archive.org/web/*/https://example.gov/a.pdf',
    'https://web.archive.org/web/2025/https://example.gov/a.pdf',
    'https://web.archive.org/save/https://example.gov/a.pdf',
    'https://webarchive.loc.gov/other/20110707213402/https://example.gov/a.pdf',
    'https://web.archive.org/web/20250610160415/http://127.0.0.1/a.pdf',
    'https://web.archive.org/web/20250610160415/http://localhost/a.pdf',
    'https://web.archive.org/web/20250610160415/https://user:pass@example.gov/a.pdf',
    'https://web.archive.org/web/20250610160415/https://example.gov/a.pdf?token=secret',
    'https://web.archive.org/web/20250610160415/https://example.gov/a.xmlhttps://example.gov/b.xml',
    'https://web.archive.org/web/20250610160415/https://example.gov/a.mp4',
    'https://web.archive.org/web/20250610160415/https://api.govinfo.gov/a.xml',
    'https://web.archive.org/web/20250610160415/https://webarchive.loc.gov/all/20110707213402/https://example.gov/a.pdf',
    'https://web.archive.org/web/20250610160415/https://[bad/a.pdf',
])
def test_archive_layout_does_not_bypass_original_url_restrictions(url):
    assert allowed_url(url) is None


def test_archived_capture_survives_checkpoint_without_replacing_original_failure():
    from test_raw_source_sync import response
    original = 'https://example.gov/statement.pdf'
    replay = 'https://web.archive.org/web/20250610160415id_/' + original
    store = MemoryStore()
    archive = Archive(store, 'archive-recovery')
    archive.record(response(original, b'not found', status=404), outcome='http_error', links=[])
    before = dict(archive.state[original])
    archived = response(replay, b'%PDF-1.7\nfixture\n%%EOF')
    archived['source_associations'] = [{'original_url': original,
        'target_url': replay, 'basis': 'archived_original_url'}]
    archive.record(archived, outcome='saved', links=[])
    archive.save()
    restored = Archive(store, 'reopen')
    assert restored.state[original] == before
    assert restored.state[replay]['outcome'] == 'saved'
    assert restored.state[replay]['family'] == 'external/wayback'


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


# Literal malformed publisher values found in failed CI run 37420553827.
GPO_PDF = 'https://www.gpo.gov/fdsys/pkg/BILLS-114hr456ih/pdf/BILLS-114hr456ih.pdf'
GPO_XML = [f'https://www.gpo.gov/fdsys/pkg/BILLS-115s585{version}/xml/BILLS-115s585{version}.xml'
           for version in ('rfh', 'es')]
LIS_WRAPPER = 'https://www.lis.gov/cgi-lis/t2GPO/' + GPO_PDF
CONCATENATED = ''.join(GPO_XML)


@pytest.mark.parametrize('original, targets, reason', [
    (LIS_WRAPPER, [GPO_PDF], 'lis_gpo_wrapper'),
    (CONCATENATED, GPO_XML, 'concatenated_file_urls'),
])
def test_known_source_defects_recover_literal_targets_with_provenance(original, targets, reason):
    item = {'url': original, 'pointer': ['documents', 0], 'text': 'Publisher label'}
    links = capture_links(item)
    assert [link['url'] for link in links] == targets
    for position, link in enumerate(links):
        assert link == {**item, 'url': targets[position], 'original_url': original,
                        'url_repair': reason, 'url_position': position}
    assert allowed_url(original) is None  # The transport guard remains strict.
    assert item['url'] == original


@pytest.mark.parametrize('value', [
    'https://example.gov/a.xmlhttps:/example.gov/b.xml',
    'https://example.gov/wrapper/https://example.gov/b.xml',
    'https://example.gov/a.xmlhttps://127.0.0.1/b.xml',
    'https://example.gov/a.xmlhttps://user:pass@example.gov/b.xml',
    'https://example.gov/a.xmlhttps://example.gov/b.mp4',
    'https://example.gov/a.xmlhttps://api.govinfo.gov/b.xml',
    'https://example.gov/a.xmlhttps://example.gov/b.xml?token=secret',
    'https://example.gov/a.xmlhttps://example.gov/b.xml#fragment',
    'https://example.gov/a.xml https://example.gov/b.xml',
    'https://www.lis.gov/cgi-lis/t2GPO/https://example.gov/b.pdf',
    'https://www.lis.gov/cgi-lis/t2GPO/https://www.gpo.gov/other/b.pdf',
    'https://www.lis.gov/cgi-lis/t2GPO/https://[bad/b.pdf',
    'https://lis.gov.evil.example/cgi-lis/t2GPO/' + GPO_PDF,
    'https://user:pass@www.lis.gov/cgi-lis/t2GPO/' + GPO_PDF,
    'not-a-url' + GPO_PDF,
])
def test_ambiguous_or_disallowed_values_are_not_partially_repaired(value):
    assert capture_links({'url': value}) == []


def test_valid_query_embedded_url_is_not_split_or_unwrapped():
    url = 'https://example.gov/download?url=https://example.gov/file.xml'
    assert capture_links({'url': url}) == [{'url': url}]


@pytest.mark.parametrize('original, targets', [(LIS_WRAPPER, [GPO_PDF]), (CONCATENATED, GPO_XML)])
def test_discovery_repairs_json_xml_html_and_keeps_source_evidence(original, targets):
    import json
    native = {'url': original, 'label': 'Original label'}
    json_items = list(json_links({'documents': [native]}, 'fixture.json'))
    xml_items = related_links(f'<bill><document href="{original}"/></bill>'.encode(),
                             'https://example.gov/bill.xml', 'xml')
    html_items = related_links(f'<a href="{original}">Download</a>'.encode(),
                              'https://example.gov/bill.html', 'html')
    for links in (json_items, xml_items, html_items):
        assert [link['url'] for link in links] == targets
        assert all(link['original_url'] == original for link in links)
    assert json_items[0]['native'] == native
    assert xml_items[0]['attributes']['href'] == original
    assert html_items[0]['attributes']['href'] == original
    # The same JSON source path is used by retained body discovery.
    assert related_links(json.dumps({'documents': [native]}).encode(), 'fixture.json', 'json') == json_items


def legacy_pending(archive, url):
    """Simulate a checkpoint written before the current admission rules."""
    temporary = 'https://example.gov/temporary.xml'
    archive.seed({'url': temporary})
    archive.state[url] = {**archive.state.pop(temporary), 'url': url}


def test_legacy_pending_repairs_survive_batch_limits_without_resetting_saved_children():
    import gzip
    import json
    from congress_api.acquisition.raw_sync import run_sync
    from test_raw_source_sync import response

    store = MemoryStore()
    archive = Archive(store, 'old')
    for value in (LIS_WRAPPER, CONCATENATED, 'http://127.0.0.1/private.xml'):
        legacy_pending(archive, value)
    archive.save()
    fetched = []

    def fetch(url):
        assert allowed_url(url) == url
        fetched.append(url)
        return response(url, f'<document>{url}</document>'.encode(), media='application/xml')

    first = run_sync(Archive(store, 'first'), [], fetch=fetch, initial_only=True, limit=1)
    assert first['attempted'] == first['saved'] == 1
    checkpoint = Archive(store, 'second')
    saved_url = fetched[0]
    saved_state = dict(checkpoint.state[saved_url])
    second = run_sync(checkpoint, [], fetch=fetch, initial_only=True, limit=20)
    assert second['attempted'] == second['saved'] == 2
    assert sorted(fetched) == sorted([GPO_PDF, *GPO_XML])
    assert checkpoint.state[saved_url] == saved_state
    final = Archive(store, 'final')
    for original in (LIS_WRAPPER, CONCATENATED):
        assert final.state[original]['outcome'] == 'repaired_url'
        assert final.state[original]['attempts'] == 0
        assert final.state[original]['body_key'] is None
    assert final.state['http://127.0.0.1/private.xml']['outcome'] == 'excluded_scope'
    assert second['accounting']['url_outcomes'] == {'saved': 3, 'repaired_url': 2, 'excluded_scope': 1}
    assert run_sync(final, [], fetch=lambda _: pytest.fail('Unexpected retry'))['attempted'] == 0
    receipts = [json.loads(line) for key in store.keys('receipts/')
                for line in gzip.decompress(store.read(key)).splitlines()]
    assert len(receipts) == 3  # Repairing a source value is not a download attempt.
    for receipt in receipts:
        url = receipt['download_state']['url']
        observations = receipt['record']['source_context']['observations']
        assert any(item['original_url'] == (LIS_WRAPPER if url == GPO_PDF else CONCATENATED)
                   for item in observations)


@pytest.mark.parametrize('original, targets', [(LIS_WRAPPER, [GPO_PDF]), (CONCATENATED, GPO_XML)])
def test_catalog_repairs_never_assign_aggregate_body_to_derived_targets(original, targets):
    store = catalog_store([dict(source_url=original, body_key='bodies/unrelated.gz',
                               format=['pdf'], http_status=['200'])])
    archive = Archive(store, 'catalog-repair')
    assert archive.state[original]['outcome'] == 'repaired_url'
    for target in targets:
        assert archive.state[target]['outcome'] == 'pending'
        assert archive.state[target]['body_key'] is None


def test_new_seed_repairs_are_idempotent_and_ordinary_seeds_stay_ordinary():
    archive = Archive(MemoryStore(), 'seed')
    for _ in range(2):
        archive.seed_links({'url': CONCATENATED}, publisher_link=True)
    assert len(archive.state) == 3
    assert archive.seed_links({'url': GPO_XML[0]}) == [{'url': GPO_XML[0]}]
    assert archive.seed_links({'url': 'http://127.0.0.1/a.pdf'}) == []
